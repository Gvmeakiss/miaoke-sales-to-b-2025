#%%
import os
import pandas as pd
import warnings
import chardet
from pathlib import Path

from scenario_utils import assign_scenario_dms, SCENARIO_DESC

warnings.filterwarnings('ignore')

print('开始DMS三单匹配（2025年1-9月，从SQL文件直接读取）...')

# ============================================================================
# 1. 读取SQL文件
# ============================================================================
print('\n1. 读取SQL文件...')

def get_encoding(file_path):
    """检测文件编码"""
    with open(file_path, 'rb') as f:
        return chardet.detect(f.read())['encoding']

def parse_sql_file(sql_file_path, expected_cols):
    """解析SQL文件，返回DataFrame（从VALUES行提取数据）"""
    print(f"  读取: {sql_file_path}")
    
    if not os.path.exists(sql_file_path):
        raise FileNotFoundError(f"文件不存在: {sql_file_path}")
    
    # 检测编码
    encoding = get_encoding(sql_file_path)
    print(f"    编码: {encoding}")
    
    # 读取SQL文件
    with open(sql_file_path, 'r', encoding=encoding, errors='ignore') as f:
        lines = f.readlines()
    
    # 提取VALUES行的数据
    values_lines = []
    for line in lines:
        line = line.strip()
        if line.upper().startswith('VALUES'):
            # 提取VALUES后的数据部分
            # VALUES ('0015423756', NULL, 'DD2501010263', ...);
            values_part = line[6:].strip()  # 去掉'VALUES'
            values_part = values_part.strip(';')
            # 找到第一个'('和最后一个')'
            start_idx = values_part.find('(')
            end_idx = values_part.rfind(')')
            if start_idx >= 0 and end_idx > start_idx:
                values_part = values_part[start_idx+1:end_idx]
                if values_part:
                    values_lines.append(values_part)
    
    # 分割数据
    sql_txt = []
    for line in values_lines:
        # 按', '分割，但要处理NULL和字符串中的逗号
        parts = []
        current = ''
        in_quotes = False
        for char in line:
            if char == "'":
                in_quotes = not in_quotes
                current += char
            elif char == ',' and not in_quotes:
                if current.strip():
                    parts.append(current.strip())
                current = ''
            else:
                current += char
        if current.strip():
            parts.append(current.strip())
        
        # 清理每个部分
        cleaned_parts = []
        for part in parts:
            part = part.strip()
            if part.upper() == 'NULL':
                cleaned_parts.append(None)
            else:
                # 去掉引号
                if part.startswith("'") and part.endswith("'"):
                    part = part[1:-1]
                cleaned_parts.append(part)
        
        if len(cleaned_parts) >= len(expected_cols):  # 确保有足够的列
            sql_txt.append(cleaned_parts[:len(expected_cols)])
    
    # 创建DataFrame
    df = pd.DataFrame(sql_txt)
    
    # 根据实际列数设置列名
    if len(df.columns) == len(expected_cols):
        df.columns = expected_cols
    elif len(df.columns) > len(expected_cols):
        # 如果列数多于期望，使用前N列
        df = df.iloc[:, :len(expected_cols)]
        df.columns = expected_cols
    else:
        print(f"    警告: 列数不匹配！期望{len(expected_cols)}列，实际{len(df.columns)}列")
        print(f"    前3行数据样例:")
        if len(df) > 0:
            print(df.head(3))
        raise ValueError(f"列数不足: 期望{len(expected_cols)}列，实际{len(df.columns)}列")
    
    print(f"    行数: {len(df):,}, 列数: {len(df.columns)}")
    return df

# 1.1 读取订单SQL文件（优先 1-9 月目录，否则 1-12 月目录）
_orders_dir = Path('OMS25年1-9月订单及发货数据')
if not _orders_dir.exists():
    _orders_dir = Path('OMS25年1-12月订单及发货数据')
order_sql = str(_orders_dir / '25年1-9月订单数据.sql')
# 先读取数据，根据实际列数设置列名
print(f"  读取订单SQL文件: {order_sql}")
encoding = get_encoding(order_sql)
with open(order_sql, 'r', encoding=encoding, errors='ignore') as f:
    lines = f.readlines()

# 提取VALUES行的数据
values_lines = []
for line in lines:
    line = line.strip()
    if line.upper().startswith('VALUES'):
        # 提取VALUES后的数据部分
        # VALUES ('0015423756', NULL, 'DD2501010263', ...);
        values_part = line[6:].strip()  # 去掉'VALUES'
        values_part = values_part.strip(';')
        # 找到第一个'('和最后一个')'
        start_idx = values_part.find('(')
        end_idx = values_part.rfind(')')
        if start_idx >= 0 and end_idx > start_idx:
            values_part = values_part[start_idx+1:end_idx]
            if values_part:
                values_lines.append(values_part)

# 分割数据
sql_txt = []
for line in values_lines:
    # 按', '分割，但要处理NULL和字符串中的逗号
    parts = []
    current = ''
    in_quotes = False
    for char in line:
        if char == "'":
            in_quotes = not in_quotes
            current += char
        elif char == ',' and not in_quotes:
            if current.strip():
                parts.append(current.strip())
            current = ''
        else:
            current += char
    if current.strip():
        parts.append(current.strip())
    
    # 清理每个部分
    cleaned_parts = []
    for part in parts:
        part = part.strip()
        if part.upper() == 'NULL':
            cleaned_parts.append(None)
        else:
            # 去掉引号
            if part.startswith("'") and part.endswith("'"):
                part = part[1:-1]
            cleaned_parts.append(part)
    
    if len(cleaned_parts) >= 11:  # 确保有足够的列
        sql_txt.append(cleaned_parts[:11])  # 只取前11列

# 创建DataFrame
df_order = pd.DataFrame(sql_txt)

# 根据实际列数设置列名
# 从SQL文件可以看到，11列格式包含channel_name（第8列），字段顺序为：
# platform_order_no, main_order_no, sale_order_no, order_type, order_status, 
# create_time, update_time, channel_name, item_code, pay_amount, item_num
if len(df_order.columns) == 13:
    df_order.columns = ['platform_order_no', 'main_order_no', 'sale_order_no', 'order_type', 'order_status', 
                       'create_time', 'update_time', 'channel_name', 'item_code', 'line_amount', 'pay_amount', 'item_num', 'channel_name2']
elif len(df_order.columns) == 11:
    # 11列格式包含channel_name（第8列），不包含line_amount
    df_order.columns = ['platform_order_no', 'main_order_no', 'sale_order_no', 'order_type', 'order_status', 
                       'create_time', 'update_time', 'channel_name', 'item_code', 'pay_amount', 'item_num']
    print(f"  检测到11列格式（包含channel_name）")
else:
    print(f"  警告: 订单数据列数: {len(df_order.columns)}")
    if len(df_order.columns) >= 11:
        # 使用前11列（包含channel_name）
        df_order = df_order.iloc[:, :11]
        df_order.columns = ['platform_order_no', 'main_order_no', 'sale_order_no', 'order_type', 'order_status', 
                           'create_time', 'update_time', 'channel_name', 'item_code', 'pay_amount', 'item_num']
    else:
        raise ValueError(f"订单数据列数不足: {len(df_order.columns)}列")

print(f"  订单数据行数: {len(df_order):,}, 列数: {len(df_order.columns)}")

# 过滤DMS订单（如果有channel_name字段，使用它；否则所有订单都可能是DMS）
if 'channel_name' in df_order.columns:
    df_order_dms = df_order[df_order['channel_name'].astype(str).str.contains('DMS', case=False, na=False)].copy()
else:
    # 如果没有channel_name字段，假设所有订单都是DMS（或者需要其他判断逻辑）
    print("  警告: 订单数据缺少channel_name字段，无法过滤DMS订单，使用全部订单")
    df_order_dms = df_order.copy()
# 与 OMS 一致：排除 OBSOLETE、CANCEL
df_order_dms = df_order_dms[df_order_dms['order_status'] != 'OBSOLETE']
df_order_dms = df_order_dms[df_order_dms['order_status'] != 'CANCEL']
print(f"  DMS订单行数: {len(df_order_dms):,}")

# 1.2 读取发货SQL文件
delivery_sql = str(_orders_dir / '25年1-9月发货数据.sql')
delivery_cols = ['business_type', '订单号', 'external_order_no', '业务时间', '料号', '名称', '已发货数量']
df_delivery = parse_sql_file(delivery_sql, delivery_cols)

# 过滤DMS发货（external_order_no不为空）
df_delivery_dms = df_delivery[df_delivery['external_order_no'].notna()].copy()
print(f"  DMS发货行数: {len(df_delivery_dms):,}")

# 1.3 读取发票数据（Excel文件，优先 SAP开票数据，否则 妙可 SAP发票拆分月份）
print('\n1.3 读取发票数据...')
invoice_dir = Path('SAP开票数据')
if not invoice_dir.exists():
    invoice_dir = Path('妙可 SAP发票拆分月份')
invoice_files = list(invoice_dir.glob('2025-*.XLSX'))
if not invoice_files:
    raise FileNotFoundError(f'未找到发票文件: {invoice_dir}')

invoice_list = []
for file_path in sorted(invoice_files):
    print(f"  读取: {file_path.name}")
    try:
        df_inv = pd.read_excel(file_path, engine='openpyxl')
        invoice_list.append(df_inv)
        print(f"    行数: {len(df_inv):,}, 列数: {len(df_inv.columns)}")
    except Exception as e:
        print(f"    读取失败: {e}")
        continue

if not invoice_list:
    raise ValueError('未成功读取任何发票文件')

df_invoice = pd.concat(invoice_list, ignore_index=True)
print(f"  发票总行数: {len(df_invoice):,}")

# ============================================================================
# 2. 发票数据过滤
# ============================================================================
print('\n2. 发票数据过滤...')

# 2.1 发票类型过滤
invoice_type_col = None
if '发票类型.1' in df_invoice.columns:
    invoice_type_col = '发票类型.1'
elif '发票类型' in df_invoice.columns:
    sample = df_invoice['发票类型'].dropna().astype(str).head(100)
    if any(('发票' in v) for v in sample):
        invoice_type_col = '发票类型'

if invoice_type_col:
    # 统一保留 ZA01/ZB02/ZQ01/ZQ07（与 OMS 一致）
    ser = df_invoice[invoice_type_col].astype(str)
    is_code = ser.str.fullmatch(r'[A-Z]{2}\d{2}', na=False).mean() > 0.5
    if is_code:
        keep_mask = ser.isin({'ZA01','ZB02','ZQ01','ZQ07'})
    else:
        keep_mask = (ser.str.contains(r'标准发票\s*[（(]?\s*2B', regex=True) |
                     ser.str.contains('标准退货发票', regex=False) |
                     ser.str.contains(r'取消标准发票\s*[（(]?\s*2B', regex=True) |
                     ser.str.contains('取消标准退货发票', regex=False))
    df_invoice = df_invoice[keep_mask]
    print(f"  使用发票类型列: {invoice_type_col}，过滤后: {len(df_invoice):,}")
else:
    print('  警告: 未找到发票类型列，跳过类型过滤')

# 2.2 过滤DMS发票（DMS销售单号不为空）
# 从检查结果：DMS销售单号(列3)
dms_order_col = None
for c in df_invoice.columns:
    if str(c) == 'DMS销售单号':
        dms_order_col = c
        break

if not dms_order_col:
    # 模糊匹配
    for c in df_invoice.columns:
        if 'DMS' in str(c) and '销售' in str(c) and '单号' in str(c):
            dms_order_col = c
            break

if not dms_order_col:
    raise ValueError('发票数据缺少DMS销售单号字段')

df_invoice_dms = df_invoice[df_invoice[dms_order_col].notna()].copy()
print(f"  DMS发票行数: {len(df_invoice_dms):,}")
print(f"  使用DMS销售单号列: {dms_order_col}")

# ============================================================================
# 3. 按订单+物料级别聚合（DMS订单号 + 物料编码）
# ============================================================================
print('\n3. 按订单+物料级别聚合（DMS订单号 + 物料编码）...')

# 3.1 发票聚合：按DMS销售单号 + 物料编码聚合（订单+物料级别）
print('\n3.1 发票聚合...')

# 识别发票金额和数量列（根据实际字段结构）
# 从检查结果：物料编码(列33), 含税金额(列50), 开票数量（销售单位）(列44), 开票数量（基本单位数量）(列46)
amount_col = None
quantity_sales_col = None  # 销售单位数量
quantity_base_col = None   # 基本单位数量
material_col = None  # 物料编码列

for c in df_invoice_dms.columns:
    cs = str(c)
    # 精确匹配字段名
    if cs == '含税金额' and amount_col is None:
        amount_col = c
    elif cs == '开票数量（销售单位）' and quantity_sales_col is None:
        quantity_sales_col = c
    elif cs == '开票数量（基本单位数量）' and quantity_base_col is None:
        quantity_base_col = c
    elif cs == '物料编码' and material_col is None:
        material_col = c

# 如果精确匹配失败，使用模糊匹配
if not amount_col:
    for c in df_invoice_dms.columns:
        cs = str(c)
        if '含税金额' in cs and amount_col is None:
            amount_col = c
            break

if not quantity_sales_col:
    for c in df_invoice_dms.columns:
        cs = str(c)
        if '开票数量' in cs and '销售单位' in cs and quantity_sales_col is None:
            quantity_sales_col = c
            break

if not quantity_base_col:
    for c in df_invoice_dms.columns:
        cs = str(c)
        if '开票数量' in cs and '基本单位' in cs and quantity_base_col is None:
            quantity_base_col = c
            break

if not material_col:
    for c in df_invoice_dms.columns:
        cs = str(c)
        if cs == '物料编码' or ('物料' in cs and '编码' in cs):
            material_col = c
            break

if not amount_col:
    raise ValueError('未找到发票金额列（含税金额）')
if not quantity_sales_col or not quantity_base_col:
    raise ValueError('未找到发票数量列（开票数量（销售单位）和开票数量（基本单位数量））')
if not material_col:
    raise ValueError('未找到发票物料编码列')

print(f"  使用发票金额列: {amount_col}")
print(f"  使用发票销售数量列: {quantity_sales_col}")
print(f"  使用发票基本数量列: {quantity_base_col}")
print(f"  使用发票物料编码列: {material_col}")

# 转换为数值类型
df_invoice_dms[amount_col] = pd.to_numeric(df_invoice_dms[amount_col], errors='coerce')
df_invoice_dms[quantity_sales_col] = pd.to_numeric(df_invoice_dms[quantity_sales_col], errors='coerce')
df_invoice_dms[quantity_base_col] = pd.to_numeric(df_invoice_dms[quantity_base_col], errors='coerce')
df_invoice_dms[material_col] = df_invoice_dms[material_col].astype(str)

# 按DMS销售单号 + 物料编码聚合（订单+物料级别）
# 使用实际字段名
pivot_invoice = df_invoice_dms.groupby([dms_order_col, material_col], as_index=False).agg({
    amount_col: 'sum',
    quantity_sales_col: 'sum',
    quantity_base_col: 'sum'
}).rename(columns={
    dms_order_col: 'DMS订单',
    material_col: '物料编码',
    amount_col: 'SAP开票含税金额',
    quantity_sales_col: 'SAP开票销售数量',
    quantity_base_col: 'SAP开票基本数量'
})

# 发票侧补充字段（首条记录）
invoice_extra_candidates = [
    (['SAP发票号', 'SAP发票编号', 'SAP账单号'], '发票-SAP发票号'),
    (['SAP订单号'], '发票-SAP订单号'),
    (['OMS订单号', 'OMS主订单号', 'OMS系统订单号'], '发票-OMS订单号'),
    (['客户名称', '客户'], '发票-客户名称'),
    (['名称', '物料名称'], '发票-物料名称'),
    (['开票日期', '发票日期'], '发票-开票日期'),
    (['数据源文件'], '发票-数据源文件')
]
invoice_extra_map = {}
invoice_extra_cols = []
for candidates, label in invoice_extra_candidates:
    for col in candidates:
        if col in df_invoice_dms.columns:
            invoice_extra_map[col] = label
            invoice_extra_cols.append(col)
            break

if invoice_extra_cols:
    invoice_extra = df_invoice_dms[[dms_order_col, material_col] + invoice_extra_cols].copy()
    invoice_extra = invoice_extra.drop_duplicates(subset=[dms_order_col, material_col])
    invoice_extra = invoice_extra.rename(columns={col: invoice_extra_map[col] for col in invoice_extra_cols})
    invoice_extra = invoice_extra.rename(columns={dms_order_col: 'DMS订单', material_col: '物料编码'})
    pivot_invoice = pivot_invoice.merge(invoice_extra, on=['DMS订单', '物料编码'], how='left')

# 四舍五入
pivot_invoice['SAP开票含税金额'] = pivot_invoice['SAP开票含税金额'].round(2)
pivot_invoice['SAP开票销售数量'] = pivot_invoice['SAP开票销售数量'].round(2)
pivot_invoice['SAP开票基本数量'] = pivot_invoice['SAP开票基本数量'].round(2)

print(f"  发票聚合后: {len(pivot_invoice):,} 条（订单+物料）")

# 3.2 DMS订单聚合：按platform_order_no + item_code聚合（订单+物料级别）
print('\n3.2 DMS订单聚合...')

# 转换为数值类型
df_order_dms['pay_amount'] = pd.to_numeric(df_order_dms['pay_amount'], errors='coerce')
df_order_dms['item_num'] = pd.to_numeric(df_order_dms['item_num'], errors='coerce')
df_order_dms['item_code'] = df_order_dms['item_code'].astype(str)

# 按platform_order_no + item_code聚合（订单+物料级别）
pivot_order = df_order_dms.groupby(['platform_order_no', 'item_code'], as_index=False).agg({
    'pay_amount': 'sum',
    'item_num': 'sum'
}).rename(columns={
    'platform_order_no': 'DMS订单',
    'item_code': '物料编码',
    'pay_amount': 'DMS订单金额',
    'item_num': 'DMS订单数量'
})

# 订单侧补充字段（首条记录）
order_extra_candidates = [
    (['channel_name'], '订单-channel_name'),
    (['order_type'], '订单-order_type'),
    (['order_status'], '订单-order_status'),
    (['main_order_no'], '订单-main_order_no'),
    (['sale_order_no'], '订单-sale_order_no'),
    (['create_time'], '订单-create_time'),
    (['update_time'], '订单-update_time')
]
order_extra_map = {}
order_extra_cols = []
for candidates, label in order_extra_candidates:
    for col in candidates:
        if col in df_order_dms.columns:
            order_extra_map[col] = label
            order_extra_cols.append(col)
            break

if order_extra_cols:
    order_extra = df_order_dms[['platform_order_no', 'item_code'] + order_extra_cols].copy()
    order_extra = order_extra.groupby(['platform_order_no', 'item_code'], as_index=False).first()
    order_extra = order_extra.rename(columns={col: order_extra_map[col] for col in order_extra_cols})
    order_extra = order_extra.rename(columns={'platform_order_no': 'DMS订单', 'item_code': '物料编码'})
    pivot_order = pivot_order.merge(order_extra, on=['DMS订单', '物料编码'], how='left')

# 四舍五入
pivot_order['DMS订单金额'] = pivot_order['DMS订单金额'].round(2)
pivot_order['DMS订单数量'] = pivot_order['DMS订单数量'].round(2)

print(f"  DMS订单聚合后: {len(pivot_order):,} 条（订单+物料）")

# 3.3 DMS发货聚合：按external_order_no + 料号聚合（订单+物料级别）
print('\n3.3 DMS发货聚合...')

# 转换为数值类型
df_delivery_dms['已发货数量'] = pd.to_numeric(df_delivery_dms['已发货数量'], errors='coerce')
df_delivery_dms['料号'] = df_delivery_dms['料号'].astype(str)

# 按external_order_no + 料号聚合（订单+物料级别）
pivot_delivery = df_delivery_dms.groupby(['external_order_no', '料号'], as_index=False).agg({
    '已发货数量': 'sum'
}).rename(columns={
    'external_order_no': 'DMS订单',
    '料号': '物料编码',
    '已发货数量': 'DMS发货数量'
})

# 发货侧补充字段（首条记录，含 business_type）
delivery_extra_candidates = [
    (['订单号'], '发货-订单号'),
    (['业务时间'], '发货-业务时间'),
    (['名称'], '发货-物料名称'),
    (['business_type'], '发货-业务类型')
]
delivery_extra_map = {}
delivery_extra_cols = []
for candidates, label in delivery_extra_candidates:
    for col in candidates:
        if col in df_delivery_dms.columns:
            delivery_extra_map[col] = label
            delivery_extra_cols.append(col)
            break

if delivery_extra_cols:
    delivery_extra = df_delivery_dms[['external_order_no', '料号'] + delivery_extra_cols].copy()
    delivery_extra = delivery_extra.groupby(['external_order_no', '料号'], as_index=False).first()
    delivery_extra = delivery_extra.rename(columns={col: delivery_extra_map[col] for col in delivery_extra_cols})
    delivery_extra = delivery_extra.rename(columns={'external_order_no': 'DMS订单', '料号': '物料编码'})
    pivot_delivery = pivot_delivery.merge(delivery_extra, on=['DMS订单', '物料编码'], how='left')

# 四舍五入
pivot_delivery['DMS发货数量'] = pivot_delivery['DMS发货数量'].round(2)

print(f"  DMS发货聚合后: {len(pivot_delivery):,} 条（订单+物料）")

# ============================================================================
# 4. 匹配（按DMS订单号 + 物料编码）
# ============================================================================
print('\n4. 匹配（按DMS订单号 + 物料编码）...')

# 4.1 发票与DMS订单匹配
print('\n4.1 发票与DMS订单匹配...')
df_join = pivot_invoice.merge(
    pivot_order,
    on=['DMS订单', '物料编码'],
    how='left'
)
print(f"  匹配后: {len(df_join):,} 条（订单+物料）")
print(f"  成功匹配DMS订单: {df_join['DMS订单金额'].notna().sum():,} 条")

# 4.2 发票与DMS发货匹配
print('\n4.2 发票与DMS发货匹配...')
df_join = df_join.merge(
    pivot_delivery,
    on=['DMS订单', '物料编码'],
    how='left'
)
print(f"  匹配后: {len(df_join):,} 条（订单+物料）")
print(f"  成功匹配DMS发货: {df_join['DMS发货数量'].notna().sum():,} 条")

# ============================================================================
# 5. 差异计算（Alteryx逻辑）
# ============================================================================
print('\n5. 差异计算（Alteryx逻辑）...')
df_join['SAP-DMS订单金额'] = (df_join['SAP开票含税金额'] - df_join['DMS订单金额']).round(2)
df_join['SAP-DMS订单数量(基本单位)'] = (df_join['SAP开票基本数量'] - df_join['DMS订单数量']).round(2)
df_join['SAP-DMS发货数量(基本单位)'] = (df_join['SAP开票基本数量'] - df_join['DMS发货数量']).round(2)
df_join['SAP-DMS发货数量'] = df_join['SAP-DMS发货数量(基本单位)']

# ============================================================================
# 6. 四大类+细分场景（统一规范，参考 refer/difference_analysis.py）
# ============================================================================
print('\n6. 场景分类（四大类+细分场景）...')

df_join['2.Not test'] = df_join[['DMS订单金额', 'DMS发货数量']].isna().any(axis=1)
df_join = assign_scenario_dms(df_join)

print('  分类统计（四大类+细分场景）:')
for cat in ['1.完全匹配', '2.数量一致金额有差异', '3.金额一致数量有差异', '4.均有差异', '5.有缺失']:
    cnt = (df_join['大类'] == cat).sum()
    print(f"    {cat}: {cnt:,}")

# ============================================================================
# 7. 导出
# ============================================================================
print('\n7. 导出...')
out1 = '2025年1-9月匹配结果-销售（toB DMS）明细-从SQL.xlsx'
out2 = '2025年1-9月匹配结果-销售（toB DMS）明细-其他未匹配-从SQL.xlsx'

# 已匹配的数据
df_join.to_excel(out1, index=False, na_rep='N/A')
print(f"  已保存: {out1}")

# 未匹配的数据（5.有缺失）
df_not_tested = df_join[df_join['大类'] == '5.有缺失'].copy()
df_not_tested.to_excel(out2, index=False, na_rep='N/A')
print(f"  已保存: {out2}")

print('\nDMS三单匹配完成。')
#%%

