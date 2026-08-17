# -*- coding: utf-8 -*-
"""
DMS 全年三单匹配（2025年1-12月，从 SQL 与发票 Excel 直接读取）

- 订单：1-9 月 11 列 / 10-12 月 13 列分支，补列后合并，再筛 DMS（channel_name 含 DMS）
- 发货：1-9 与 10-12 月 SQL，7 列（或 8 列取前 7/8），7 列时做订单号/料号错位纠错，合并后筛 external_order_no 非空
- 发票：2025-01～12.XLSX，concat(join='outer')，类型与 DMS 销售单号过滤
- 导出：超 1,048,575 行时先 CSV 全量，xlsx 分 sheet

产出：
  - 2025年全年匹配结果-销售（toB DMS）明细-从SQL.xlsx（超限时+明细-从SQL.csv、分 sheet）
  - 2025年全年匹配结果-销售（toB DMS）明细-其他未匹配-从SQL.xlsx
"""

import os
import numpy as np
import pandas as pd
import warnings
import chardet
from pathlib import Path
import pickle

warnings.filterwarnings('ignore')

# PKL缓存目录
PKL_DIR = Path('PKL')
PKL_DIR.mkdir(exist_ok=True)

print('开始 DMS 三单匹配（2025年全年，从 SQL 文件直接读取）...')

# ============================================================================
# 解析工具：VALUES 行、订单 11/13 列、发货 7 列（含纠错）
# ============================================================================

def get_encoding(file_path):
    with open(file_path, 'rb') as f:
        return chardet.detect(f.read())['encoding']

def _parse_values_line(line):
    """从 VALUES 行解析出值列表。"""
    line = line.strip()
    if not line.upper().startswith('VALUES'):
        return None
    part = line[6:].strip().strip(';')
    start = part.find('(')
    end = part.rfind(')')
    if start < 0 or end <= start:
        return None
    part = part[start + 1 : end]
    if not part.strip():
        return None
    parts = []
    cur, in_q = '', False
    for c in part:
        if c == "'":
            in_q = not in_q
            cur += c
        elif c == ',' and not in_q:
            if cur.strip():
                parts.append(cur.strip())
            cur = ''
        else:
            cur += c
    if cur.strip():
        parts.append(cur.strip())
    out = []
    for p in parts:
        p = p.strip()
        if p.upper() == 'NULL':
            out.append(None)
        else:
            if p.startswith("'") and p.endswith("'"):
                p = p[1:-1]
            out.append(p)
    return out

def _parse_sql_values(sql_path, expected_cols, min_cols=None):
    enc = get_encoding(sql_path)
    with open(sql_path, 'r', encoding=enc, errors='ignore') as f:
        lines = f.readlines()
    rows = []
    need = min_cols if min_cols is not None else len(expected_cols)
    for line in lines:
        vals = _parse_values_line(line)
        if vals is None or len(vals) < need:
            continue
        rows.append(vals[: len(expected_cols)])
    df = pd.DataFrame(rows)
    if len(df.columns) != len(expected_cols):
        df = df.iloc[:, : len(expected_cols)]
    df.columns = expected_cols
    return df, enc

COLS_11 = [
    'platform_order_no', 'main_order_no', 'sale_order_no', 'order_type', 'order_status',
    'create_time', 'update_time', 'channel_name', 'item_code', 'pay_amount', 'item_num'
]
COLS_13 = [
    'platform_order_no', 'main_order_no', 'sale_order_no', 'order_type', 'order_status',
    'create_time', 'update_time', 'channel_name', 'item_code', 'line_amount', 'pay_amount', 'item_num', 'channel_name2'
]

def _process_order_11cols(sql_path):
    df, enc = _parse_sql_values(sql_path, COLS_11, min_cols=11)
    df.insert(9, 'line_amount', np.nan)
    df['channel_name2'] = np.nan
    return df[COLS_13], enc

def _process_order_13cols(sql_path):
    return _parse_sql_values(sql_path, COLS_13, min_cols=13)

COLS_7 = ['business_type', '订单号', 'external_order_no', '业务时间', '料号', '名称', '已发货数量']
COLS_8 = ['business_type', '主单号', '订单号', 'external_order_no', '业务时间', '料号', '名称', '已发货数量']

def _apply_delivery_7col_fix(df):
    if df.shape[1] < 5:
        return
    s1 = df.iloc[:, 1].astype(str)
    s4 = df.iloc[:, 4].astype(str)
    n = len(df)
    dd1 = s1.str.match(r'^DD', na=False).sum()
    dd4 = s4.str.match(r'^DD', na=False).sum()
    dg1 = s1.str.match(r'^\d+$', na=False).sum()
    dg4 = s4.str.match(r'^\d+$', na=False).sum()
    if dg1 > n * 0.5 and dd4 > n * 0.5 and (dd1 <= n * 0.5 or dg4 <= n * 0.5):
        df.iloc[:, [1, 4]] = df.iloc[:, [4, 1]].values

def _process_delivery_sql_one(sql_path):
    enc = get_encoding(sql_path)
    with open(sql_path, 'r', encoding=enc, errors='ignore') as f:
        lines = f.readlines()
    rows = []
    for line in lines:
        vals = _parse_values_line(line)
        if vals is None:
            continue
        if len(vals) >= 8:
            rows.append(vals[:8])
        elif len(vals) >= 7:
            rows.append(vals[:7])
    if not rows:
        return pd.DataFrame(columns=COLS_7), enc
    n = len(rows[0])
    cols = COLS_8 if n == 8 else COLS_7
    df = pd.DataFrame(rows).iloc[:, : len(cols)]
    if len(cols) == 7:
        _apply_delivery_7col_fix(df)
    df.columns = cols
    return df, enc

# ============================================================================
# 1. 读取订单、发货、发票（带PKL缓存）
# ============================================================================
print('\n1. 读取 SQL 与发票...')

# 检查PKL缓存
pkl_order = PKL_DIR / 'dms_order_full_year.pkl'
pkl_delivery = PKL_DIR / 'dms_delivery_full_year.pkl'
pkl_invoice = PKL_DIR / 'dms_invoice_full_year.pkl'

if pkl_order.exists() and pkl_delivery.exists() and pkl_invoice.exists():
    print('  从PKL缓存加载数据...')
    df_order_dms = pd.read_pickle(pkl_order)
    df_delivery_dms = pd.read_pickle(pkl_delivery)
    df_invoice = pd.read_pickle(pkl_invoice)
    print(f"  DMS 订单行数: {len(df_order_dms):,}")
    print(f"  DMS 发货行数: {len(df_delivery_dms):,}")
    print(f"  发票总行数: {len(df_invoice):,}, 列数: {len(df_invoice.columns)}")
else:
    print('  从SQL和Excel文件读取数据...')
    _orders_dir = Path('OMS25年1-12月订单及发货数据')
    if not _orders_dir.exists():
        raise FileNotFoundError(f"目录不存在: {_orders_dir}，全年需 1-9 与 10-12 月 SQL")

    # 1.1 订单：1-9 为 11 列补列，10-12 为 13 列，合并后筛 DMS
    sql_19 = _orders_dir / '25年1-9月订单数据.sql'
    sql_1012 = _orders_dir / '25年10-12月订单数据.sql'
    if not sql_19.exists():
        raise FileNotFoundError(f"订单 SQL 不存在: {sql_19}")
    if not sql_1012.exists():
        raise FileNotFoundError(f"订单 SQL 不存在: {sql_1012}")

    df_19, e19 = _process_order_11cols(str(sql_19))
    print(f"  1-9 月订单: 编码={e19}, 行数={len(df_19):,}, 已补 line_amount/channel_name2")
    df_1012, e1012 = _process_order_13cols(str(sql_1012))
    df_1012 = df_1012[COLS_13]
    print(f"  10-12 月订单: 编码={e1012}, 行数={len(df_1012):,}")

    df_order = pd.concat([df_19, df_1012], ignore_index=True)
    if 'channel_name' in df_order.columns:
        df_order_dms = df_order[df_order['channel_name'].astype(str).str.contains('DMS', case=False, na=False)].copy()
    else:
        print("  警告: 缺少 channel_name，使用全部订单")
        df_order_dms = df_order.copy()
    print(f"  DMS 订单行数: {len(df_order_dms):,}")

    # 1.2 发货：1-9 与 10-12，7/8 列解析与纠错，合并后筛 external_order_no 非空
    d19 = _orders_dir / '25年1-9月发货数据.sql'
    d1012 = _orders_dir / '25年10-12月发货数据.sql'
    if not d19.exists():
        raise FileNotFoundError(f"发货 SQL 不存在: {d19}")
    if not d1012.exists():
        raise FileNotFoundError(f"发货 SQL 不存在: {d1012}")

    df_d19, ed19 = _process_delivery_sql_one(str(d19))
    print(f"  1-9 月发货: 编码={ed19}, 行数={len(df_d19):,}, 列数={len(df_d19.columns)}")
    df_d1012, ed1012 = _process_delivery_sql_one(str(d1012))
    print(f"  10-12 月发货: 编码={ed1012}, 行数={len(df_d1012):,}, 列数={len(df_d1012.columns)}")

    df_delivery = pd.concat([df_d19, df_d1012], ignore_index=True)
    df_delivery_dms = df_delivery[df_delivery['external_order_no'].notna()].copy()
    print(f"  DMS 发货行数: {len(df_delivery_dms):,}")

    # 1.3 发票：2025-01～12.XLSX，concat(join='outer')
    invoice_dir = Path('SAP开票数据')
    if not invoice_dir.exists():
        invoice_dir = Path('妙可 SAP发票拆分月份')
    if not invoice_dir.exists():
        raise FileNotFoundError('未找到发票目录: SAP开票数据 或 妙可 SAP发票拆分月份')

    invoice_list = []
    for m in [f'{i:02d}' for i in range(1, 13)]:
        for ext in ('XLSX', 'xlsx'):
            p = invoice_dir / f'2025-{m}.{ext}'
            if p.exists():
                try:
                    df_inv = pd.read_excel(p, engine='openpyxl')
                    df_inv['数据源文件'] = p.name
                    invoice_list.append(df_inv)
                    print(f"  读取: {p.name} 行数={len(df_inv):,} 列数={len(df_inv.columns)}")
                except Exception as e:
                    print(f"  读取失败 {p.name}: {e}")
                break
    if not invoice_list:
        raise ValueError('未成功读取任何 2025-01～12 月发票 Excel')

    df_invoice = pd.concat(invoice_list, ignore_index=True, join='outer')
    print(f"  发票总行数: {len(df_invoice):,}, 列数: {len(df_invoice.columns)}")
    
    # 保存到PKL缓存
    print('\n  保存数据到PKL缓存...')
    df_order_dms.to_pickle(pkl_order)
    df_delivery_dms.to_pickle(pkl_delivery)
    df_invoice.to_pickle(pkl_invoice)
    print(f"  已保存: {pkl_order}")
    print(f"  已保存: {pkl_delivery}")
    print(f"  已保存: {pkl_invoice}")

# ============================================================================
# 2. 发票过滤：类型（标准发票 2B、排除退货）、DMS 销售单号非空
# ============================================================================
print('\n2. 发票过滤...')

invoice_type_col = None
if '发票类型.1' in df_invoice.columns:
    invoice_type_col = '发票类型.1'
elif '发票类型' in df_invoice.columns:
    sample = df_invoice['发票类型'].dropna().astype(str).head(100)
    if any(('发票' in v) for v in sample):
        invoice_type_col = '发票类型'

if invoice_type_col:
    ser = df_invoice[invoice_type_col].astype(str)
    keep = ser.str.contains('标准发票', regex=False) & ser.str.contains('2B', regex=False) & ~ser.str.contains('退货', regex=False)
    df_invoice = df_invoice[keep]
    print(f"  使用列: {invoice_type_col}，过滤后: {len(df_invoice):,}")
else:
    print('  警告: 未找到发票类型列，跳过类型过滤')

dms_order_col = None
for c in df_invoice.columns:
    if str(c) == 'DMS销售单号':
        dms_order_col = c
        break
if not dms_order_col:
    for c in df_invoice.columns:
        if 'DMS' in str(c) and '销售' in str(c) and '单号' in str(c):
            dms_order_col = c
            break
if not dms_order_col:
    raise ValueError('发票数据缺少 DMS销售单号 字段')

df_invoice_dms = df_invoice[df_invoice[dms_order_col].notna()].copy()
print(f"  DMS 发票行数: {len(df_invoice_dms):,}")

# ============================================================================
# 3. 聚合（DMS 订单 + 物料编码）
# ============================================================================
print('\n3. 按 DMS 订单 + 物料 聚合...')

amount_col = quantity_sales_col = quantity_base_col = material_col = None
for c in df_invoice_dms.columns:
    cs = str(c)
    if cs == '含税金额': amount_col = c
    elif cs == '开票数量（销售单位）': quantity_sales_col = c
    elif cs == '开票数量（基本单位数量）': quantity_base_col = c
    elif cs == '物料编码': material_col = c
if not amount_col:
    for c in df_invoice_dms.columns:
        if '含税金额' in str(c): amount_col = c; break
if not quantity_sales_col:
    for c in df_invoice_dms.columns:
        if '开票数量' in str(c) and '销售单位' in str(c): quantity_sales_col = c; break
if not quantity_base_col:
    for c in df_invoice_dms.columns:
        if '开票数量' in str(c) and '基本单位' in str(c): quantity_base_col = c; break
if not material_col:
    for c in df_invoice_dms.columns:
        if str(c) == '物料编码' or ('物料' in str(c) and '编码' in str(c)): material_col = c; break

if not amount_col:
    raise ValueError('未找到发票金额列（含税金额）')
if not quantity_sales_col or not quantity_base_col:
    raise ValueError('未找到发票数量列（开票数量 销售/基本单位）')
if not material_col:
    raise ValueError('未找到发票物料编码列')

df_invoice_dms[amount_col] = pd.to_numeric(df_invoice_dms[amount_col], errors='coerce')
df_invoice_dms[quantity_sales_col] = pd.to_numeric(df_invoice_dms[quantity_sales_col], errors='coerce')
df_invoice_dms[quantity_base_col] = pd.to_numeric(df_invoice_dms[quantity_base_col], errors='coerce')
df_invoice_dms[material_col] = df_invoice_dms[material_col].astype(str)

# 发票聚合：金额和数量用sum，其他字段用first保留
invoice_agg_dict = {
    amount_col: 'sum',
    quantity_sales_col: 'sum',
    quantity_base_col: 'sum'
}

invoice_extra_candidates = [
    (['SAP发票号', 'SAP发票编号', 'SAP账单号', '发票号', '发票编号'], '发票-SAP发票号'),
    (['SAP订单号'], '发票-SAP订单号'),
    (['OMS订单号', 'OMS主订单号', 'OMS系统订单号'], '发票-OMS订单号'),
    (['公司代码', '公司'], '发票-公司代码'),
    (['发票备注', '备注', '发票说明'], '发票-发票备注'),
    (['发票类型', '发票类型.1'], '发票-发票类型'),
    (['销售组织', '销售组织代码'], '发票-销售组织'),
    (['客户名称', '客户'], '发票-客户名称'),
    (['名称', '物料名称'], '发票-物料名称'),
    (['开票日期', '发票日期'], '发票-开票日期'),
    (['数据源文件'], '发票-数据源文件')
]
invoice_extra_map, invoice_extra_cols = {}, []
for candidates, label in invoice_extra_candidates:
    for col in candidates:
        if col in df_invoice_dms.columns:
            invoice_agg_dict[col] = 'first'
            invoice_extra_map[col] = label
            invoice_extra_cols.append(col)
            break

pivot_invoice = df_invoice_dms.groupby([dms_order_col, material_col], as_index=False).agg(invoice_agg_dict)
pivot_invoice.rename(columns={
    dms_order_col: 'DMS订单',
    material_col: '物料编码',
    amount_col: 'SAP开票含税金额',
    quantity_sales_col: 'SAP开票销售数量',
    quantity_base_col: 'SAP开票基本数量'
}, inplace=True)

# 重命名额外字段
for col in invoice_extra_cols:
    if col in pivot_invoice.columns:
        pivot_invoice.rename(columns={col: invoice_extra_map[col]}, inplace=True)

pivot_invoice['SAP开票含税金额'] = pivot_invoice['SAP开票含税金额'].round(2)
pivot_invoice['SAP开票销售数量'] = pivot_invoice['SAP开票销售数量'].round(2)
pivot_invoice['SAP开票基本数量'] = pivot_invoice['SAP开票基本数量'].round(2)
print(f"  发票聚合: {len(pivot_invoice):,} 条")

# 订单聚合
df_order_dms['pay_amount'] = pd.to_numeric(df_order_dms['pay_amount'], errors='coerce')
df_order_dms['item_num'] = pd.to_numeric(df_order_dms['item_num'], errors='coerce')
df_order_dms['item_code'] = df_order_dms['item_code'].astype(str)

# 订单聚合：金额和数量用sum，其他字段用first保留
order_agg_dict = {'pay_amount': 'sum', 'item_num': 'sum'}
order_extra_candidates = [
    (['sale_order_no'], '订单-销售订单号'),
    (['main_order_no'], '订单-主订单号'),
    (['channel_name'], '订单-渠道名称'),
    (['order_type'], '订单-订单类型'),
    (['order_status'], '订单-订单状态'),
    (['create_time'], '订单-创建时间'),
    (['update_time'], '订单-更新时间')
]
order_extra_map, order_extra_cols = {}, []
for candidates, label in order_extra_candidates:
    for col in candidates:
        if col in df_order_dms.columns:
            order_agg_dict[col] = 'first'
            order_extra_map[col] = label
            order_extra_cols.append(col)
            break

pivot_order = df_order_dms.groupby(['platform_order_no', 'item_code'], as_index=False).agg(order_agg_dict)
pivot_order.rename(columns={
    'platform_order_no': 'DMS订单',
    'item_code': '物料编码',
    'pay_amount': 'DMS订单金额',
    'item_num': 'DMS订单数量'
}, inplace=True)

# 重命名额外字段
for col in order_extra_cols:
    if col in pivot_order.columns:
        pivot_order.rename(columns={col: order_extra_map[col]}, inplace=True)

# 添加平台订单号和商品代码作为订单字段（虽然它们已经在DMS订单和物料编码中）
pivot_order['订单-平台订单号'] = pivot_order['DMS订单']
pivot_order['订单-商品代码'] = pivot_order['物料编码']

pivot_order['DMS订单金额'] = pivot_order['DMS订单金额'].round(2)
pivot_order['DMS订单数量'] = pivot_order['DMS订单数量'].round(2)
print(f"  DMS 订单聚合: {len(pivot_order):,} 条")

# 发货聚合：数量用sum，其他字段用first保留
df_delivery_dms['已发货数量'] = pd.to_numeric(df_delivery_dms['已发货数量'], errors='coerce')
df_delivery_dms['料号'] = df_delivery_dms['料号'].astype(str)

delivery_agg_dict = {'已发货数量': 'sum'}
delivery_extra_candidates = [
    (['订单号'], '发货-订单号'),
    (['主单号'], '发货-主单号'),
    (['业务时间'], '发货-业务时间'),
    (['名称'], '发货-物料名称'),
    (['business_type'], '发货-业务类型')
]
delivery_extra_map, delivery_extra_cols = {}, []
for candidates, label in delivery_extra_candidates:
    for col in candidates:
        if col in df_delivery_dms.columns:
            delivery_agg_dict[col] = 'first'
            delivery_extra_map[col] = label
            delivery_extra_cols.append(col)
            break

pivot_delivery = df_delivery_dms.groupby(['external_order_no', '料号'], as_index=False).agg(delivery_agg_dict)
pivot_delivery.rename(columns={
    'external_order_no': 'DMS订单',
    '料号': '物料编码',
    '已发货数量': 'DMS发货数量'
}, inplace=True)

# 重命名额外字段
for col in delivery_extra_cols:
    if col in pivot_delivery.columns:
        pivot_delivery.rename(columns={col: delivery_extra_map[col]}, inplace=True)

# 添加外部订单号和料号作为发货字段
pivot_delivery['发货-外部订单号'] = pivot_delivery['DMS订单']
pivot_delivery['发货-料号'] = pivot_delivery['物料编码']

pivot_delivery['DMS发货数量'] = pivot_delivery['DMS发货数量'].round(2)
print(f"  DMS 发货聚合: {len(pivot_delivery):,} 条")

# ============================================================================
# 4. 匹配、差异、分类
# ============================================================================
print('\n4. 匹配与差异计算...')

df_join = pivot_invoice.merge(pivot_order, on=['DMS订单', '物料编码'], how='left')
df_join = df_join.merge(pivot_delivery, on=['DMS订单', '物料编码'], how='left')

df_join['SAP-DMS订单金额'] = (df_join['SAP开票含税金额'] - df_join['DMS订单金额']).round(2)
df_join['SAP-DMS订单数量(基本单位)'] = (df_join['SAP开票基本数量'] - df_join['DMS订单数量']).round(2)
df_join['SAP-DMS发货数量(基本单位)'] = (df_join['SAP开票基本数量'] - df_join['DMS发货数量']).round(2)
df_join['SAP-DMS发货数量'] = df_join['SAP-DMS发货数量(基本单位)']

df_join['2.Not test'] = df_join[['DMS订单金额', 'DMS发货数量']].isna().any(axis=1)
df_join['1.1完全匹配'] = (df_join['SAP-DMS订单金额'].abs() < 1) & (df_join['SAP-DMS发货数量'].abs() < 0.01) & ~df_join['2.Not test']
df_join['1.2金额不一致'] = (df_join['SAP-DMS订单金额'].abs() >= 1) & (df_join['SAP-DMS发货数量'].abs() < 0.01) & ~df_join['2.Not test']
df_join['1.3数量不一致'] = (df_join['SAP-DMS发货数量'].abs() >= 0.01) & (df_join['SAP-DMS订单金额'].abs() < 1) & ~df_join['2.Not test']
df_join['1.4均不一致'] = (df_join['SAP-DMS发货数量'].abs() >= 0.01) & (df_join['SAP-DMS订单金额'].abs() >= 1) & ~df_join['2.Not test']

print('  分类统计:')
print(f"    1.1 完全匹配: {df_join['1.1完全匹配'].sum():,}")
print(f"    1.2 金额不一致: {df_join['1.2金额不一致'].sum():,}")
print(f"    1.3 数量不一致: {df_join['1.3数量不一致'].sum():,}")
print(f"    1.4 均不一致: {df_join['1.4均不一致'].sum():,}")
print(f"    2. 未测试(有缺失): {df_join['2.Not test'].sum():,}")

# ============================================================================
# 5. 按销售组织分组（1240、1250、1260 与 其他）
# ============================================================================
print('\n5. 按销售组织分组...')

# 查找销售组织字段
sales_org_col = None
for col in df_join.columns:
    if '销售组织' in str(col):
        sales_org_col = col
        break

if sales_org_col:
    # 销售组织值（支持字符串和数字格式）
    sales_org_values = ['1240', '1250', '1260', 1240, 1250, 1260]
    sales_org_str_values = [str(v) for v in sales_org_values]
    
    # 筛选出1240、1250、1260的数据
    df_sales_org_123 = df_join[df_join[sales_org_col].astype(str).isin(sales_org_str_values)].copy()
    # 剔除1240、1250、1260的数据（保留其他公司）
    df_sales_org_other = df_join[~df_join[sales_org_col].astype(str).isin(sales_org_str_values)].copy()
    
    print(f"  销售组织（1240、1250、1260）数据: {len(df_sales_org_123):,} 条")
    print(f"  其他销售组织数据: {len(df_sales_org_other):,} 条")
else:
    print(f"  警告: 未找到销售组织字段，使用全部数据")
    df_sales_org_123 = pd.DataFrame()
    df_sales_org_other = df_join.copy()

# ============================================================================
# 6. 导出（按分类拆分到独立sheet + 汇总表）
# ============================================================================
print('\n6. 导出（按分类拆分）...')

EXCEL_MAX = 1_048_575

def export_with_classification(df_data, output_file, file_label=""):
    """导出数据，按分类拆分到独立sheet，并创建汇总表"""
    if len(df_data) == 0:
        print(f"  {file_label}: 无数据，跳过导出")
        return
    
    # 查找SAP开票含税金额字段
    amount_col = None
    for col in df_data.columns:
        if 'SAP开票含税金额' in str(col):
            amount_col = col
            break
    
    # 准备分类数据
    categories = {
        '全部数据': df_data,
        '2.Not test': df_data[df_data['2.Not test']].copy() if '2.Not test' in df_data.columns else pd.DataFrame(),
        '1.1完全匹配': df_data[df_data['1.1完全匹配']].copy() if '1.1完全匹配' in df_data.columns else pd.DataFrame(),
        '1.2金额不一致': df_data[df_data['1.2金额不一致']].copy() if '1.2金额不一致' in df_data.columns else pd.DataFrame(),
        '1.3数量不一致': df_data[df_data['1.3数量不一致']].copy() if '1.3数量不一致' in df_data.columns else pd.DataFrame(),
        '1.4均不一致': df_data[df_data['1.4均不一致']].copy() if '1.4均不一致' in df_data.columns else pd.DataFrame(),
    }
    
    # 创建汇总表
    summary_data = []
    for cat_name, cat_df in categories.items():
        if len(cat_df) > 0:
            row_count = len(cat_df)
            if amount_col and amount_col in cat_df.columns:
                total_amount = pd.to_numeric(cat_df[amount_col], errors='coerce').sum()
                summary_data.append({
                    '分类': cat_name,
                    '记录数': row_count,
                    'SAP开票含税金额': round(total_amount, 2) if not pd.isna(total_amount) else 0
                })
            else:
                summary_data.append({
                    '分类': cat_name,
                    '记录数': row_count,
                    'SAP开票含税金额': 0
                })
    
    df_summary = pd.DataFrame(summary_data)
    
    # 添加总计行
    if len(df_summary) > 0:
        total_row = {
            '分类': '总计',
            '记录数': df_summary['记录数'].sum(),
            'SAP开票含税金额': df_summary['SAP开票含税金额'].sum()
        }
        df_summary = pd.concat([df_summary, pd.DataFrame([total_row])], ignore_index=True)
    
    # 导出到Excel
    csv_name = output_file.replace('.xlsx', '.csv')
    if len(df_data) > EXCEL_MAX:
        df_data.to_csv(csv_name, index=False, encoding='utf-8-sig')
        print(f"  {file_label}: 已保存CSV全量 {csv_name} ({len(df_data):,} 行)")
    
    with pd.ExcelWriter(output_file, engine='openpyxl') as w:
        # 汇总表（第一个sheet）
        df_summary.to_excel(w, sheet_name='汇总表', index=False)
        
        # 各分类数据
        for cat_name, cat_df in categories.items():
            if len(cat_df) == 0:
                continue
            
            # Excel sheet名称限制31个字符，需要截断
            sheet_name = cat_name[:31]
            
            if len(cat_df) <= EXCEL_MAX:
                cat_df.to_excel(w, sheet_name=sheet_name, index=False, na_rep='N/A')
            else:
                # 如果单个分类也超限，分多个sheet
                for i, start in enumerate(range(0, len(cat_df), EXCEL_MAX)):
                    part_sheet_name = f"{sheet_name[:25]}_P{i+1}"[:31]
                    cat_df.iloc[start:start + EXCEL_MAX].to_excel(w, sheet_name=part_sheet_name, index=False, na_rep='N/A')
        
        print(f"  {file_label}: 已保存 {output_file} ({len(df_summary)} 个分类sheet + 汇总表)")
        if len(df_data) > EXCEL_MAX:
            print(f"  {file_label}: CSV全量文件 {csv_name}")

# 6.1 导出剔除三家公司的主明细和未匹配文件
if sales_org_col:
    out1 = '2025年全年匹配结果-销售（toB DMS）明细-从SQL（剔除三家）.xlsx'
    out2 = '2025年全年匹配结果-销售（toB DMS）明细-其他未匹配-从SQL（剔除三家）.xlsx'
    df_export = df_sales_org_other
else:
    out1 = '2025年全年匹配结果-销售（toB DMS）明细-从SQL.xlsx'
    out2 = '2025年全年匹配结果-销售（toB DMS）明细-其他未匹配-从SQL.xlsx'
    df_export = df_join

export_with_classification(df_export, out1, "剔除三家-主明细")

df_not_tested_other = df_export[df_export['2.Not test']].copy()
export_with_classification(df_not_tested_other, out2, "剔除三家-未匹配")

# 6.2 导出三家公司的明细和未匹配文件
if sales_org_col and len(df_sales_org_123) > 0:
    print('\n7. 导出三家公司的数据（1240、1250、1260）...')
    
    out3 = '2025年全年匹配结果-销售（toB DMS）明细-从SQL（1240、1250、1260）.xlsx'
    out4 = '2025年全年匹配结果-销售（toB DMS）明细-其他未匹配-从SQL（1240、1250、1260）.xlsx'
    
    export_with_classification(df_sales_org_123, out3, "三家公司-主明细")
    
    df_not_tested_123 = df_sales_org_123[df_sales_org_123['2.Not test']].copy()
    export_with_classification(df_not_tested_123, out4, "三家公司-未匹配")
elif sales_org_col:
    print('\n7. 警告: 未找到销售组织为1240、1250、1260的数据，跳过三家公司的导出')

print('\nDMS 全年三单匹配完成。')
