# -*- coding: utf-8 -*-
"""
DMS 三单匹配（统一脚本，由 config 配置时间范围、路径、筛选条件）

输入：order_pkl、delivery_pkl、invoice_pkl（与 OMS 共用，由 preprocess 产出）。
取数：订单 platform_order_no（DMS订单号）非空 = DMS 订单；发货 external_order_no 非空；排除 OBSOLETE/CANCEL。
"""

import numpy as np
import pandas as pd
import warnings
from pathlib import Path

from config import get_dms_config, get_output_prefix, OUTPUT_DIR
from scenario_utils import assign_scenario_dms, SCENARIO_DESC
from export_utils import export_with_classification

warnings.filterwarnings('ignore')

BASE = Path(__file__).resolve().parent.parent


def _filter_2025(df, date_cols=None):
    """仅保留任一日期的年份为 2025 的行。"""
    if df.empty:
        return df
    date_cols = date_cols or ['订单-创建时间', '发货-业务时间', '发票-开票日期']
    keep = pd.Series(False, index=df.index)
    for col in date_cols:
        if col not in df.columns:
            continue
        dt = pd.to_datetime(df[col], errors='coerce')
        keep = keep | (dt.dt.year == 2025)
    return df[keep]


print(f"开始 DMS 三单匹配（{get_output_prefix()}）...")

# ============================================================================
# 1. 读取订单、发货、发票（与 OMS 共用 pkl）
# ============================================================================
print('\n1. 读取数据...')

cfg = get_dms_config()
prefix = get_output_prefix()
order_pkl = Path(cfg.get('order_pkl')) if cfg.get('order_pkl') else None
delivery_pkl = Path(cfg.get('delivery_pkl')) if cfg.get('delivery_pkl') else None
invoice_pkl = Path(cfg.get('invoice_pkl')) if cfg.get('invoice_pkl') else None

if order_pkl and delivery_pkl and invoice_pkl and order_pkl.exists() and delivery_pkl.exists() and invoice_pkl.exists():
    print('  从 PKL 文件读取（与 OMS 共用）...')
    df_order = pd.read_pickle(str(order_pkl))
    df_delivery = pd.read_pickle(str(delivery_pkl))
    df_invoice = pd.read_pickle(str(invoice_pkl))
    # 订单数据源规范：platform_order_no（DMS订单号）非空 = DMS 订单（通过 DMS 下单）
    if 'platform_order_no' in df_order.columns:
        dms_order_mask = df_order['platform_order_no'].notna() & (
            df_order['platform_order_no'].astype(str).str.strip() != ''
        )
        df_order_dms = df_order[dms_order_mask].copy()
    else:
        print("  警告: 缺少 platform_order_no，无法按 DMS订单号 区分，使用全部订单")
        df_order_dms = df_order.copy()
    df_order_dms = df_order_dms[df_order_dms['order_status'] != 'OBSOLETE']
    df_order_dms = df_order_dms[df_order_dms['order_status'] != 'CANCEL']
    df_delivery_dms = df_delivery[df_delivery['external_order_no'].notna()].copy()
    print(f"  DMS 订单行数: {len(df_order_dms):,}")
    print(f"  DMS 发货行数: {len(df_delivery_dms):,}")
    print(f"  发票总行数: {len(df_invoice):,}, 列数: {len(df_invoice.columns)}")
else:
    raise FileNotFoundError(
        f"未找到 pkl 文件，请先运行 preprocess_oms_full_year.py 生成：\n"
        f"  - {order_pkl}\n  - {delivery_pkl}\n  - {invoice_pkl}"
    )

# ============================================================================
# 2. 发票过滤：类型 + 数据源规范（DMS销售单号 非空 = DMS 发票）
# ============================================================================
print('\n2. 发票过滤...')

# 发票数据源规范：DMS销售单号 非空 = DMS 发票，仅用于 DMS 三单匹配
invoice_type_col = None
if '发票类型.1' in df_invoice.columns:
    invoice_type_col = '发票类型.1'
elif '发票类型' in df_invoice.columns:
    sample = df_invoice['发票类型'].dropna().astype(str).head(100)
    if any(('发票' in v) for v in sample):
        invoice_type_col = '发票类型'

if invoice_type_col:
    ser = df_invoice[invoice_type_col].astype(str)
    is_code = ser.str.fullmatch(r'[A-Z]{2}\d{2}', na=False).mean() > 0.5
    if is_code:
        keep = ser.isin({'ZA01','ZB02','ZQ01','ZQ07'})
    else:
        keep = (ser.str.contains(r'标准发票\s*[（(]?\s*2B', regex=True) |
                ser.str.contains('标准退货发票', regex=False) |
                ser.str.contains(r'取消标准发票\s*[（(]?\s*2B', regex=True) |
                ser.str.contains('取消标准退货发票', regex=False))
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
    (['document_no'], '发货-发货单号'),
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

# 四大类+细分场景（统一规范，参考 refer/difference_analysis.py）
df_join['2.Not test'] = df_join[['DMS订单金额', 'DMS发货数量']].isna().any(axis=1)
df_join = assign_scenario_dms(df_join)

# df_nottested: 订单+发货 无发票（DMS 订单 outer join 发货 outer join 发票，过滤无开票）
df_nottested = pivot_order.merge(pivot_delivery, on=['DMS订单', '物料编码'], how='outer')
df_nottested = df_nottested.merge(pivot_invoice, on=['DMS订单', '物料编码'], how='outer')
df_nottested = df_nottested[df_nottested['SAP开票基本数量'].isna()].copy()

date_cols_dms = ['订单-创建时间', '发货-业务时间', '发票-开票日期']
has_ord = df_nottested['DMS订单金额'].notna()
has_dlv = df_nottested['DMS发货数量'].notna()
extra_categories = {
    '仅订单': _filter_2025(df_nottested[has_ord & ~has_dlv], date_cols_dms),
    '仅发货单': _filter_2025(df_nottested[~has_ord & has_dlv], date_cols_dms),
    '仅订单及发货单': _filter_2025(df_nottested[has_ord & has_dlv], date_cols_dms),
}

# DMS 发票总条数、总金额（pivot_invoice）
dms_inv_cnt = len(pivot_invoice)
dms_inv_amt = float(pivot_invoice['SAP开票含税金额'].sum()) if 'SAP开票含税金额' in pivot_invoice.columns else 0.0
invoice_stats = (dms_inv_cnt, dms_inv_amt)

print('  分类统计（四大类+细分场景）:')
for cat in ['1.完全匹配', '2.数量一致金额有差异', '3.金额一致数量有差异', '4.均有差异', '5.有缺失']:
    cnt = (df_join['大类'] == cat).sum()
    print(f"    {cat}: {cnt:,}")

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
# 6. 导出（按分类拆分到独立sheet + 汇总表，参考 refer/difference_analysis.py）
# ============================================================================
print('\n6. 导出（按分类拆分）...')

EXCEL_MAX = 1_048_575

# 6.1 导出剔除三家公司的主明细和未匹配文件
OUTPUT_DIR.mkdir(exist_ok=True)
_prefix = get_output_prefix()
if sales_org_col:
    out1 = OUTPUT_DIR / f'{_prefix}匹配结果-销售（toB DMS）明细（剔除三家）.xlsx'
    out2 = OUTPUT_DIR / f'{_prefix}匹配结果-销售（toB DMS）明细-其他未匹配（剔除三家）.xlsx'
    df_export = df_sales_org_other
else:
    out1 = OUTPUT_DIR / f'{_prefix}匹配结果-销售（toB DMS）明细.xlsx'
    out2 = OUTPUT_DIR / f'{_prefix}匹配结果-销售（toB DMS）明细-其他未匹配.xlsx'
    df_export = df_join

# 超限时先保存 CSV 全量（参考原逻辑）
if len(df_export) > EXCEL_MAX:
    csv_path = out1.with_suffix('.csv')
    df_export.to_csv(str(csv_path), index=False, encoding='utf-8-sig')
    print(f"  剔除三家-主明细: 已保存CSV全量 {csv_path} ({len(df_export):,} 行)")

export_with_classification(
    df_export, str(out1), "剔除三家-主明细",
    inv_minus_order_col='SAP-DMS订单金额',
    amount_label='SAP开票含税金额',
    extra_categories=extra_categories,
    invoice_stats=invoice_stats,
    invoice_stats_label='DMS发票清单',
)

df_not_tested_other = _filter_2025(
    df_export[df_export['大类'] == '5.有缺失'].copy(),
    date_cols_dms,
)
export_with_classification(
    df_not_tested_other, str(out2), "剔除三家-未匹配",
    inv_minus_order_col='SAP-DMS订单金额',
    amount_label='SAP开票含税金额',
    extra_categories=extra_categories,
    invoice_stats=invoice_stats,
    invoice_stats_label='DMS发票清单',
)

# 6.2 导出三家公司的明细和未匹配文件
if sales_org_col and len(df_sales_org_123) > 0:
    print('\n7. 导出三家公司的数据（1240、1250、1260）...')
    
    out3 = OUTPUT_DIR / f'{_prefix}匹配结果-销售（toB DMS）明细（1240、1250、1260）.xlsx'
    out4 = OUTPUT_DIR / f'{_prefix}匹配结果-销售（toB DMS）明细-其他未匹配（1240、1250、1260）.xlsx'
    
    export_with_classification(
        df_sales_org_123, str(out3), "三家公司-主明细",
        inv_minus_order_col='SAP-DMS订单金额',
        amount_label='SAP开票含税金额',
        extra_categories=extra_categories,
        invoice_stats=invoice_stats,
        invoice_stats_label='DMS发票清单',
    )
    
    df_not_tested_123 = _filter_2025(
        df_sales_org_123[df_sales_org_123['大类'] == '5.有缺失'].copy(),
        date_cols_dms,
    )
    export_with_classification(
        df_not_tested_123, str(out4), "三家公司-未匹配",
        inv_minus_order_col='SAP-DMS订单金额',
        amount_label='SAP开票含税金额',
        extra_categories=extra_categories,
        invoice_stats=invoice_stats,
        invoice_stats_label='DMS发票清单',
    )
elif sales_org_col:
    print('\n7. 警告: 未找到销售组织为1240、1250、1260的数据，跳过三家公司的导出')

print('\nDMS 全年三单匹配完成。')
