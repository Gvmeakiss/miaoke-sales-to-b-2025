#%%
import os
import pandas as pd
import warnings
from pathlib import Path
import glob

from scenario_utils import assign_scenario_oms, SCENARIO_DESC

warnings.filterwarnings('ignore')

# ============================================================================
# 数据导入 - 2025年1-9月数据（从pkl文件加载）
# ============================================================================

print("开始加载2025年1-9月数据...")

# 1. 订单数据 - 从pkl文件加载
print("\n1. 加载订单数据...")
order_pkl = '25年1-9月OMS订单.pkl'

if not os.path.exists(order_pkl):
    raise FileNotFoundError(f"未找到订单数据pkl文件: {order_pkl}\n请先运行 数据预处理_25年1-9月.py 生成pkl文件")

df_order = pd.read_pickle(order_pkl)
print(f"  订单数据总行数: {len(df_order)}")
print(f"  订单数据列名: {list(df_order.columns)}")

# 2. 发货数据 - 从pkl文件加载
print("\n2. 加载发货数据...")
delivery_pkl = '25年1-9月OMS发货.pkl'

if not os.path.exists(delivery_pkl):
    raise FileNotFoundError(f"未找到发货数据pkl文件: {delivery_pkl}\n请先运行 数据预处理_25年1-9月.py 生成pkl文件")

df_delivery = pd.read_pickle(delivery_pkl)
print(f"  发货数据总行数: {len(df_delivery)}")
print(f"  发货数据列名: {list(df_delivery.columns)}")

# 检查发货数据是否有主单号列（用于匹配键生成）
if '主单号' not in df_delivery.columns:
    print("  警告: 发货数据中没有'主单号'列，将使用'订单号'作为匹配键")

# 3. 发票数据 - 从pkl文件加载
print("\n3. 加载发票数据...")
invoice_pkl = '2025年1-9月SAP原始数据.pkl'

if not os.path.exists(invoice_pkl):
    raise FileNotFoundError(f"未找到发票数据pkl文件: {invoice_pkl}\n请先运行 数据预处理_25年1-9月.py 生成pkl文件")

df_invoice = pd.read_pickle(invoice_pkl)
print(f"  发票数据总行数: {len(df_invoice)}")
print(f"  发票数据列名（前10个）: {list(df_invoice.columns[:10])}")

# ============================================================================
# 数据预处理
# ============================================================================

print("\n开始数据预处理...")

# 订单数据过滤：仅排除 OBSOLETE、CANCEL；不限制 order_type、不限制 create_time
print("\n4. 订单数据过滤...")
df_order = df_order[df_order['order_status'] != 'OBSOLETE']
df_order = df_order[df_order['order_status'] != 'CANCEL']
print(f"  过滤后订单数据行数: {len(df_order)}")

# 发货：取消业务时间限制
print("\n5. 发货数据...")
if '业务时间' in df_delivery.columns:
    df_delivery['业务时间'] = pd.to_datetime(df_delivery['业务时间'], format='mixed', errors='coerce')
print(f"  发货数据行数: {len(df_delivery)}")

# 发票数据过滤
print("\n6. 发票数据过滤...")
# 过滤发票类型（只保留To B OMS相关发票类型）
invoice_type_col = None
for col in df_invoice.columns:
    if '发票类型' in str(col):
        invoice_type_col = col
        break

if invoice_type_col:
    print(f"  发票类型列名: {invoice_type_col}")
    # 构建更稳健的类型筛选：优先中文描述，兼容不同括号/空格/半角
    ser = df_invoice[invoice_type_col].astype(str)
    # 识别是否为代码列（如 ZA01/ZB02）
    is_code_like = ser.str.fullmatch(r'[A-Z]{2}\d{2}').fillna(False).mean() > 0.5
    if not is_code_like:
        # 中文描述：包含“标准发票 2B”或“标准退货发票”，兼容取消类与中英文括号
        keep_mask = ser.str.contains('标准发票\s*[（(]?\s*2B', regex=True) | \
                    ser.str.contains('标准退货发票', regex=False) | \
                    ser.str.contains('取消标准发票\s*[（(]?\s*2B', regex=True) | \
                    ser.str.contains('取消标准退货发票', regex=False)
    else:
        # 代码列：保留常见ToB代码（可按需要扩展）
        keep_codes = {'ZA01','ZB02','ZQ01','ZQ07'}  # 标准发票2B/标准退货/取消标准发票2B/取消标准退货
        keep_mask = ser.isin(keep_codes)
    df_invoice = df_invoice[keep_mask]
    print(f"  过滤后发票数据行数: {len(df_invoice)}")
else:
    # 索引回退：部分环境列名可能乱码，采用第15列(O列)作为发票类型
    if len(df_invoice.columns) > 14:
        invoice_type_col = df_invoice.columns[14]
        print(f"  警告: 名称匹配失败，使用索引列作为发票类型: {invoice_type_col}")
        ser = df_invoice[invoice_type_col].astype(str)
        keep_mask = ser.str.contains('标准发票\s*[（(]?\s*2B', regex=True) | \
                    ser.str.contains('标准退货发票', regex=False) | \
                    ser.str.contains('取消标准发票\s*[（(]?\s*2B', regex=True) | \
                    ser.str.contains('取消标准退货发票', regex=False)
        df_invoice = df_invoice[keep_mask]
        print(f"  过滤后发票数据行数: {len(df_invoice)}")
    else:
        print("  警告: 未找到发票类型列，跳过发票类型过滤")

# 将发票统一转为使用OMS订单号+物料编码的order-item：
# 1) 先用已有的OMS销售单号（无论是否来自DMS来源）
inv_with_oms = pd.DataFrame()
if {'OMS销售单号','物料编码'}.issubset(df_invoice.columns):
    inv_with_oms = df_invoice[df_invoice['OMS销售单号'].notna()].copy()
    inv_with_oms['order-item'] = inv_with_oms['OMS销售单号'].astype(str) + inv_with_oms['物料编码'].astype(str)
    print(f"  直接使用OMS销售单号的发票条数: {len(inv_with_oms)}")

# 2) 对缺少OMS销售单号且具备DMS销售单号的发票，尝试用 external_order_no+item_code 映射为 OMS主订单号（main_order_no 或 sale_order_no）
inv_need_map = pd.DataFrame()
if 'DMS销售单号' in df_invoice.columns:
    inv_need_map = df_invoice[df_invoice['OMS销售单号'].isna() & df_invoice['DMS销售单号'].notna()].copy()

mapped_df = pd.DataFrame(columns=df_invoice.columns)
if not inv_need_map.empty and {'external_order_no','item_code','sale_order_no','main_order_no'}.issubset(df_order.columns):
    order_map = df_order[['external_order_no','item_code','sale_order_no','main_order_no']].dropna(subset=['external_order_no']).copy()
    order_map['dms-order-item'] = order_map['external_order_no'].astype(str) + order_map['item_code'].astype(str)
    order_map['oms_main'] = order_map['main_order_no'].fillna(order_map['sale_order_no'])
    inv_need_map = inv_need_map.copy()
    inv_need_map['dms-order-item'] = inv_need_map['DMS销售单号'].astype(str) + inv_need_map['物料编码'].astype(str)
    mapped_df = inv_need_map.merge(order_map[['dms-order-item','oms_main']], on='dms-order-item', how='left')
    mapped_cnt = mapped_df['oms_main'].notna().sum()
    print(f"  DMS映射成功: {mapped_cnt} / {len(inv_need_map)}")
    mapped_df = mapped_df[mapped_df['oms_main'].notna()].copy()
    if not mapped_df.empty:
        mapped_df['order-item'] = mapped_df['oms_main'].astype(str) + mapped_df['物料编码'].astype(str)
elif not inv_need_map.empty:
    print("  警告: 订单数据缺少 external_order_no/item_code/sale_order_no/main_order_no，无法对DMS发票做映射")

# 合并两部分为用于聚合的发票集
df_invoice_used = pd.concat([inv_with_oms, mapped_df], ignore_index=True)
print(f"  用于聚合的发票条数: {len(df_invoice_used)}")

# 过滤DMS销售单号为空（确保是OMS订单）
if 'DMS销售单号' in df_invoice.columns:
    df_invoice = df_invoice[df_invoice['DMS销售单号'].isna()]
    print(f"  过滤DMS后发票数据行数: {len(df_invoice)}")

# ============================================================================
# 创建匹配键 order-item
# ============================================================================

print("\n7. 创建匹配键...")

# 订单匹配键：主订单号(main_order_no) + item_code，为空时用 sale_order_no 兜底
if 'sale_order_no' in df_order.columns and 'item_code' in df_order.columns:
    if 'main_order_no' in df_order.columns:
        df_order['order-item'] = df_order['main_order_no'].fillna(df_order['sale_order_no']).astype(str) + df_order['item_code'].astype(str)
    else:
        df_order['order-item'] = df_order['sale_order_no'].astype(str) + df_order['item_code'].astype(str)
    print("  订单匹配键创建完成（主订单号+物料，主订单号空时用子订单号）")
else:
    print(f"  警告: 订单数据缺少必要列，现有列: {list(df_order.columns)}")

# 发货匹配键：主单号(OMS主订单号) + 料号，为空时用 订单号(子订单号) 兜底
if '主单号' in df_delivery.columns and '订单号' in df_delivery.columns and '料号' in df_delivery.columns:
    df_delivery['order-item'] = df_delivery['主单号'].fillna(df_delivery['订单号']).astype(str) + df_delivery['料号'].astype(str)
    print("  发货匹配键创建完成（主单号+料号，主单号空时用订单号）")
elif '订单号' in df_delivery.columns and '料号' in df_delivery.columns:
    # 如果没有主单号列，只使用订单号
    df_delivery['order-item'] = df_delivery['订单号'].astype(str) + df_delivery['料号'].astype(str)
    print("  发货匹配键创建完成（使用订单号）")
else:
    print(f"  警告: 发货数据缺少必要列，现有列: {list(df_delivery.columns)}")

# 发票匹配键：OMS销售单号 + 物料编码
if 'OMS销售单号' in df_invoice.columns and '物料编码' in df_invoice.columns:
    df_invoice['order-item'] = df_invoice['OMS销售单号'].astype(str) + df_invoice['物料编码'].astype(str)
    print("  发票匹配键创建完成")
else:
    print(f"  警告: 发票数据缺少必要列，现有列: {list(df_invoice.columns)}")

# ============================================================================
# 数据聚合（按order-item分组汇总）
# ============================================================================

print("\n8. 数据聚合...")

# 订单数据聚合
df_order['pay_amount'] = pd.to_numeric(df_order['pay_amount'], errors='coerce').round(2)
df_order['item_num'] = pd.to_numeric(df_order['item_num'], errors='coerce').round(2)

pivot_order = df_order.pivot_table(
    index='order-item',
    values=['pay_amount', 'item_num'],
    aggfunc='sum'
).reset_index()
pivot_order.rename(columns={'pay_amount': '订单金额', 'item_num': '订单数量'}, inplace=True)
print(f"  订单聚合后行数: {len(pivot_order)}")

# 发货数据聚合（含 business_type 用于三单匹配结果）
df_delivery['已发货数量'] = pd.to_numeric(df_delivery['已发货数量'], errors='coerce').round(2)
delivery_agg = {'已发货数量': 'sum'}
if 'business_type' in df_delivery.columns:
    delivery_agg['business_type'] = 'first'
pivot_delivery = df_delivery.groupby('order-item', as_index=False).agg(delivery_agg)
pivot_delivery.rename(columns={'已发货数量': '发货数量'}, inplace=True)
if 'business_type' in pivot_delivery.columns:
    pivot_delivery.rename(columns={'business_type': '发货-业务类型'}, inplace=True)
print(f"  发货聚合后行数: {len(pivot_delivery)}")

# 发票数据聚合（使用合并后的 df_invoice_used）
# 查找金额和数量列（可能有不同的列名）
amount_col = None
quantity_col = None

if df_invoice_used is None or len(df_invoice_used) == 0:
    pivot_invoice = pd.DataFrame({'order-item': [], '开票金额': [], '开票数量': []})
    print("  发票数据为空，创建空的发票聚合结果")
else:
    for col in df_invoice_used.columns:
        if '实际金额' in str(col) or ('金额' in str(col) and 'ZFN1' in str(col)):
            amount_col = col
        if '开票数量' in str(col) or ('数量' in str(col) and '基本单位' in str(col)):
            quantity_col = col

    if amount_col and quantity_col:
        df_invoice_used[amount_col] = pd.to_numeric(df_invoice_used[amount_col], errors='coerce').round(2)
        df_invoice_used[quantity_col] = pd.to_numeric(df_invoice_used[quantity_col], errors='coerce').round(2)
        
        pivot_invoice = df_invoice_used.pivot_table(
            index='order-item',
            values=[amount_col, quantity_col],
            aggfunc='sum'
        ).reset_index()
        pivot_invoice.rename(columns={amount_col: '开票金额', quantity_col: '开票数量'}, inplace=True)
        print(f"  发票聚合后行数: {len(pivot_invoice)}")
    else:
        print(f"  警告: 未找到发票金额或数量列，金额列: {amount_col}, 数量列: {quantity_col}。创建空的发票聚合结果以继续流程")
        pivot_invoice = pd.DataFrame({'order-item': [], '开票金额': [], '开票数量': []})

# 确保聚合列存在
for col in ['开票金额','开票数量']:
    if col not in pivot_invoice.columns:
        pivot_invoice[col] = pd.Series(dtype='float')

# ============================================================================
# 数据匹配
# ============================================================================

print("\n9. 数据匹配...")

# 以发票为主表，左连接发货和订单
df_join = pivot_invoice.merge(pivot_delivery, on='order-item', how='left')
df_join = df_join.merge(pivot_order, on='order-item', how='left')
print(f"  匹配后数据行数: {len(df_join)}")

# 找出未开票的记录（订单+发货但没有发票）
df_join_nottested = pivot_order.merge(pivot_delivery, on='order-item', how='outer')
df_join_nottested = df_join_nottested.merge(pivot_invoice, on='order-item', how='outer')
df_join_nottested = df_join_nottested[df_join_nottested['开票数量'].isna()]
print(f"  未开票记录数: {len(df_join_nottested)}")

# ============================================================================
# 差异计算
# ============================================================================

print("\n10. 计算差异...")

df_join['订单-发货数量'] = pd.to_numeric(df_join['订单数量'], errors='coerce') - pd.to_numeric(df_join['发货数量'], errors='coerce')
df_join['订单-开票数量'] = pd.to_numeric(df_join['订单数量'], errors='coerce') - pd.to_numeric(df_join['开票数量'], errors='coerce')
df_join['发货-开票数量'] = pd.to_numeric(df_join['发货数量'], errors='coerce') - pd.to_numeric(df_join['开票数量'], errors='coerce')
df_join['订单-发票金额'] = pd.to_numeric(df_join['订单金额'], errors='coerce') - pd.to_numeric(df_join['开票金额'], errors='coerce')
df_join['订单-发票金额'] = df_join['订单-发票金额'].round(2)

# ============================================================================
# 分类标记（四大类+细分场景，统一规范 refer/difference_analysis.py）
# ============================================================================

print("\n11. 分类标记...")

key_cols = ['订单金额', '订单数量', '发货数量', '开票金额', '开票数量']
df_join['2.Not test'] = df_join[key_cols].isna().any(axis=1)

df_join = assign_scenario_oms(df_join)

print("  分类统计（四大类+细分场景）:")
for cat in ['1.完全匹配', '2.数量一致金额有差异', '3.金额一致数量有差异', '4.均有差异', '5.有缺失']:
    cnt = (df_join['大类'] == cat).sum()
    print(f"  {cat}: {cnt:,}")

# ============================================================================
# 导出结果
# ============================================================================

print("\n12. 导出结果...")

output_file1 = '2025年1-9月匹配结果-销售（toB OMS）明细.xlsx'
output_file2 = '2025年1-9月匹配结果-销售（toB OMS）明细-其他未匹配.xlsx'

df_join.to_excel(output_file1, index=False)
print(f"  已保存: {output_file1}")

df_join_nottested.to_excel(output_file2, na_rep='N/A', index=False)
print(f"  已保存: {output_file2}")

print("\n处理完成！")

#%%

# ============================================================================
# 额外功能：对SAP发票场景进行区分（可选）
# ============================================================================

print("\n开始发票场景分类...")

# 重新读取完整发票数据（如果需要分类所有发票类型）
invoice_pkl = '2025年1-9月SAP原始数据.pkl'
if os.path.exists(invoice_pkl):
    df_invoice_all = pd.read_pickle(invoice_pkl)
else:
    # 如果没有pkl文件，尝试从Excel文件读取
    invoice_files = glob.glob('SAP开票数据/2025-*.XLSX')
    invoice_files.sort()
    df_invoice_list = []
    for file in invoice_files:
        df_temp = pd.read_excel(file)
        df_invoice_list.append(df_temp)
    df_invoice_all = pd.concat(df_invoice_list, ignore_index=True)

# 分类
df_invoice_all['分类'] = '其他'

# 重新查找发票类型列（如果之前未找到）
if not invoice_type_col:
    for col in df_invoice_all.columns:
        if '发票类型' in str(col):
            invoice_type_col = col
            break
    if not invoice_type_col and len(df_invoice_all.columns) > 14:
        invoice_type_col = df_invoice_all.columns[14]
        print(f"  警告: 分类阶段使用索引列作为发票类型: {invoice_type_col}")

if invoice_type_col:
    df_invoice_all.loc[df_invoice_all[invoice_type_col].isin(
        ['标准发票（2B)', '标准退货发票', '取消标准发票（2B)', '取消标准退货发票']), '分类'] = 'To B (DMS)'
    
    df_invoice_all.loc[(df_invoice_all[invoice_type_col].isin(
        ['标准发票（2B)', '标准退货发票', '取消标准发票（2B)', '取消标准退货发票'])) & 
        (df_invoice_all['DMS销售单号'].isna()), '分类'] = 'To B (OMS)'
    
    df_invoice_all.loc[df_invoice_all[invoice_type_col].isin(
        ['取消传统贸易发票', '期货贸易发票']), '分类'] = '期货'
    
    df_invoice_all.loc[df_invoice_all[invoice_type_col].isin(['标准发票（2C)']), '分类'] = 'To C'

print("\n发票分类统计:")
print(df_invoice_all['分类'].value_counts())

# 导出分类结果
with pd.ExcelWriter('2025年1-9月SAP发票-分场景.xlsx') as wt:
    for category in df_invoice_all['分类'].unique():
        df_category = df_invoice_all[df_invoice_all['分类'] == category]
        sheet_name = f'场景：{category}'
        df_category.to_excel(wt, sheet_name=sheet_name, index=False)
        print(f"  已保存分类: {category} ({len(df_category)} 条)")

print("\n所有处理完成！")

#%%