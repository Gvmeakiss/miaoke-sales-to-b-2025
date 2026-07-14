# -*- coding: utf-8 -*-
"""
DMS 三单匹配（统一脚本，由 config 配置时间范围、路径、筛选条件）

修改 config.TIME_RANGE 切换 1-9 月 / 全年。
- 全年：input/dingdan、input/fayundan 多 SQL，发票 pkl 或 Excel
- 1-9月：OMS25年1-9月订单及发货数据 单 SQL，发票 Excel
"""

import os
import numpy as np
import pandas as pd
import warnings
import chardet
from pathlib import Path
import pickle

from config import get_dms_config, get_output_prefix
from scenario_utils import assign_scenario_dms, SCENARIO_DESC
from export_utils import export_with_classification

warnings.filterwarnings('ignore')

BASE = Path(__file__).resolve().parent.parent
PKL_DIR = BASE / 'PKL'
PKL_DIR.mkdir(exist_ok=True)

print(f"开始 DMS 三单匹配（{get_output_prefix()}，从 SQL 文件直接读取）...")

# ============================================================================
# 解析工具：VALUES 行、订单 11/13 列、发货 7 列（含纠错）
# ============================================================================

def _detect_file_encoding(file_path):
    """检测 SQL 文件编码"""
    with open(file_path, 'rb') as f:
        return chardet.detect(f.read())['encoding']


def _parse_sql_values_line(line):
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

def _parse_sql_file_to_df(sql_path, expected_cols, min_cols=None):
    """解析 SQL 文件 VALUES 行，返回 DataFrame 及编码"""
    enc = _detect_file_encoding(sql_path)
    with open(sql_path, 'r', encoding=enc, errors='ignore') as f:
        lines = f.readlines()
    rows = []
    need = min_cols if min_cols is not None else len(expected_cols)
    for line in lines:
        vals = _parse_sql_values_line(line)
        if vals is None or len(vals) < need:
            continue
        rows.append(vals[: len(expected_cols)])
    df = pd.DataFrame(rows)
    if len(df.columns) != len(expected_cols):
        df = df.iloc[:, : len(expected_cols)]
    df.columns = expected_cols
    return df, enc

ORDER_COLS_11 = [
    'platform_order_no', 'main_order_no', 'sale_order_no', 'order_type', 'order_status',
    'create_time', 'update_time', 'channel_name', 'item_code', 'pay_amount', 'item_num'
]
ORDER_COLS_12 = [
    'platform_order_no', 'main_order_no', 'sale_order_no', 'order_type', 'order_status',
    'create_time', 'update_time', 'channel_name', 'item_code', 'line_amount', 'pay_amount', 'item_num'
]
ORDER_COLS_13 = [
    'platform_order_no', 'main_order_no', 'sale_order_no', 'order_type', 'order_status',
    'create_time', 'update_time', 'channel_name', 'item_code', 'line_amount', 'pay_amount', 'item_num', 'channel_name2'
]

def _parse_order_sql_11_cols(sql_path):
    """解析 11 列订单 SQL，补全为 13 列"""
    df, enc = _parse_sql_file_to_df(sql_path, ORDER_COLS_11, min_cols=11)
    df.insert(9, 'line_amount', np.nan)
    df['channel_name2'] = np.nan
    return df[ORDER_COLS_13], enc


def _parse_order_sql_12_cols(sql_path):
    """解析 12 列订单 SQL，补全为 13 列"""
    df, enc = _parse_sql_file_to_df(sql_path, ORDER_COLS_12, min_cols=12)
    df['channel_name2'] = np.nan
    return df[ORDER_COLS_13], enc


def _parse_order_sql_13_cols(sql_path):
    """解析 13 列订单 SQL"""
    return _parse_sql_file_to_df(sql_path, ORDER_COLS_13, min_cols=13)


DELIVERY_COLS_7 = ['business_type', '订单号', 'external_order_no', '业务时间', '料号', '名称', '已发货数量']
DELIVERY_COLS_8 = ['business_type', '主单号', '订单号', 'external_order_no', '业务时间', '料号', '名称', '已发货数量']
DELIVERY_COLS_9 = ['business_type', '订单号', 'external_order_no', '业务时间', '料号', '名称', '已发货数量', 'document_no', 'main_order_no']

def _fix_delivery_7col_column_swap(df):
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

def _parse_delivery_sql_file(sql_path):
    enc = _detect_file_encoding(sql_path)
    with open(sql_path, 'r', encoding=enc, errors='ignore') as f:
        lines = f.readlines()
    rows = []
    for line in lines:
        vals = _parse_sql_values_line(line)
        if vals is None:
            continue
        if len(vals) >= 9:
            rows.append(vals[:9])
        elif len(vals) >= 8:
            rows.append(vals[:8])
        elif len(vals) >= 7:
            rows.append(vals[:7])
    if not rows:
        return pd.DataFrame(columns=DELIVERY_COLS_7), enc
    n = len(rows[0])
    cols = DELIVERY_COLS_9 if n == 9 else (DELIVERY_COLS_8 if n == 8 else DELIVERY_COLS_7)
    df = pd.DataFrame(rows).iloc[:, : len(cols)]
    df.columns = cols
    if len(cols) == 7:
        _fix_delivery_7col_column_swap(df)
    if len(cols) == 9 and 'main_order_no' in df.columns:
        df['主单号'] = df['main_order_no']
    return df, enc

# ============================================================================
# 1. 读取订单、发货、发票（由 config 决定 single/multi 模式）
# ============================================================================
print('\n1. 读取 SQL 与发票...')

cfg = get_dms_config()
prefix = get_output_prefix()
use_cache = cfg.get('use_pkl_cache') and cfg.get('pkl_cache_dir')
cache_suffix = '1_9' if cfg.get('mode') == 'single' else 'full_year'
pkl_order = PKL_DIR / f'dms_order_{cache_suffix}.pkl'
pkl_delivery = PKL_DIR / f'dms_delivery_{cache_suffix}.pkl'
pkl_invoice = PKL_DIR / f'dms_invoice_{cache_suffix}.pkl'

if use_cache and pkl_order.exists() and pkl_delivery.exists() and pkl_invoice.exists():
    print('  从PKL缓存加载数据...')
    df_order_dms = pd.read_pickle(pkl_order)
    df_delivery_dms = pd.read_pickle(pkl_delivery)
    df_invoice = pd.read_pickle(pkl_invoice)
    print(f"  DMS 订单行数: {len(df_order_dms):,}")
    print(f"  DMS 发货行数: {len(df_delivery_dms):,}")
    print(f"  发票总行数: {len(df_invoice):,}, 列数: {len(df_invoice.columns)}")
else:
    cfg = get_dms_config()
    print('  从SQL和发票读取数据...')
    if cfg.get('mode') == 'single':
        _order_dir = Path(cfg.get('order_sql_dir', BASE / 'OMS25年1-9月订单及发货数据'))
        if not _order_dir.exists():
            _order_dir = Path(cfg.get('order_sql_dir_fallback', BASE / 'OMS25年1-12月订单及发货数据'))
        order_sql = _order_dir / cfg.get('order_sql_file', '25年1-9月订单数据.sql')
        delivery_sql = _order_dir / cfg.get('delivery_sql_file', '25年1-9月发货数据.sql')
        if not order_sql.exists():
            raise FileNotFoundError(f"订单 SQL 不存在: {order_sql}")
        if not delivery_sql.exists():
            raise FileNotFoundError(f"发货 SQL 不存在: {delivery_sql}")
        df_order, _ = _parse_order_sql_11_cols(str(order_sql))
        df_delivery, _ = _parse_delivery_sql_file(str(delivery_sql))
        if 'channel_name' in df_order.columns:
            df_order_dms = df_order[df_order['channel_name'].astype(str).str.contains('DMS', case=False, na=False)].copy()
        else:
            df_order_dms = df_order.copy()
        df_order_dms = df_order_dms[df_order_dms['order_status'] != 'OBSOLETE']
        df_order_dms = df_order_dms[df_order_dms['order_status'] != 'CANCEL']
        df_delivery_dms = df_delivery[df_delivery['external_order_no'].notna()].copy()
        print(f"  DMS 订单行数: {len(df_order_dms):,}")
        print(f"  DMS 发货行数: {len(df_delivery_dms):,}")
        # 发票：Excel
        inv_dir = Path(cfg.get('invoice_dir', BASE / 'SAP开票数据'))
        if not inv_dir.exists():
            inv_dir = Path(cfg.get('invoice_dir_fallback', BASE / '妙可 SAP发票拆分月份'))
        invoice_files = list(inv_dir.glob(cfg.get('invoice_glob', '2025-*.XLSX')))
        if not invoice_files:
            raise FileNotFoundError(f"未找到发票: {inv_dir}")
        invoice_list = []
        for fp in sorted(invoice_files):
            try:
                df_inv = pd.read_excel(fp, engine='openpyxl')
                df_inv['数据源文件'] = fp.name
                invoice_list.append(df_inv)
            except Exception as e:
                print(f"  读取失败 {fp.name}: {e}")
        if not invoice_list:
            raise ValueError('未成功读取任何发票')
        df_invoice = pd.concat(invoice_list, ignore_index=True, join='outer')
        print(f"  发票总行数: {len(df_invoice):,}")
    else:
        _order_dir = Path(cfg.get('order_sql_dir', BASE / 'input' / 'dingdan'))
        _delivery_dir = Path(cfg.get('delivery_sql_dir', BASE / 'input' / 'fayundan'))
        if not _order_dir.exists():
            raise FileNotFoundError(f"目录不存在: {_order_dir}，需 24年12月到25年6月 + 25年7月到25年12月 订单 SQL")
        order_files = cfg.get('order_sql_files', ['24年12月到25年6月订单数据.sql', '25年7月到25年12月订单数据.sql'])
        sql_1 = _order_dir / order_files[0]
        sql_2 = _order_dir / order_files[1]
        if not sql_1.exists():
            raise FileNotFoundError(f"订单 SQL 不存在: {sql_1}")
        if not sql_2.exists():
            raise FileNotFoundError(f"订单 SQL 不存在: {sql_2}")

        df_1, e1 = _parse_order_sql_12_cols(str(sql_1))
        print(f"  24年12月-25年6月订单: 编码={e1}, 行数={len(df_1):,}")
        df_2, e2 = _parse_order_sql_12_cols(str(sql_2))
        print(f"  25年7月-25年12月订单: 编码={e2}, 行数={len(df_2):,}")

        df_order = pd.concat([df_1, df_2], ignore_index=True)
        if 'channel_name' in df_order.columns:
            df_order_dms = df_order[df_order['channel_name'].astype(str).str.contains('DMS', case=False, na=False)].copy()
        else:
            print("  警告: 缺少 channel_name，使用全部订单")
            df_order_dms = df_order.copy()
        # 与 OMS 一致：排除 OBSOLETE、CANCEL
        df_order_dms = df_order_dms[df_order_dms['order_status'] != 'OBSOLETE']
        df_order_dms = df_order_dms[df_order_dms['order_status'] != 'CANCEL']
        print(f"  DMS 订单行数: {len(df_order_dms):,}")

        # 1.2 发货：新数据源 9 列（24年12月-25年6月 + 25年7月-26年1月）
        if not _delivery_dir.exists():
            raise FileNotFoundError(f"目录不存在: {_delivery_dir}")
        d_files = cfg.get('delivery_sql_files', ['24年12月到25年6月发货数据.sql', '25年7月到26年1月发货数据.sql'])
        d1 = _delivery_dir / d_files[0]
        d2 = _delivery_dir / d_files[1]
        if not d1.exists():
            raise FileNotFoundError(f"发货 SQL 不存在: {d1}")
        if not d2.exists():
            raise FileNotFoundError(f"发货 SQL 不存在: {d2}")

        df_d1, ed1 = _parse_delivery_sql_file(str(d1))
        print(f"  24年12月-25年6月发货: 编码={ed1}, 行数={len(df_d1):,}, 列数={len(df_d1.columns)}")
        df_d2, ed2 = _parse_delivery_sql_file(str(d2))
        print(f"  25年7月-26年1月发货: 编码={ed2}, 行数={len(df_d2):,}, 列数={len(df_d2.columns)}")

        df_delivery = pd.concat([df_d1, df_d2], ignore_index=True)
        df_delivery_dms = df_delivery[df_delivery['external_order_no'].notna()].copy()
        print(f"  DMS 发货行数: {len(df_delivery_dms):,}")

        # 1.3 发票：优先 output/fapiao_2025_filtered.pkl，否则 Excel
        invoice_pkl_path = BASE / 'output' / 'fapiao_2025_filtered.pkl'
        if invoice_pkl_path.exists():
            df_invoice = pd.read_pickle(invoice_pkl_path)
            print(f"  从 {invoice_pkl_path.name} 加载: {len(df_invoice):,} 行, 列数={len(df_invoice.columns)}")
        else:
            invoice_dir = Path('SAP开票数据')
            if not invoice_dir.exists():
                invoice_dir = Path('妙可 SAP发票拆分月份')
            if not invoice_dir.exists():
                raise FileNotFoundError('未找到发票: output/fapiao_2025_filtered.pkl 或 SAP开票数据 或 妙可 SAP发票拆分月份')
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

        # 保存到PKL缓存（仅 use_cache 时）
        if cfg.get('use_cache', False):
            print('\n  保存数据到PKL缓存...')
            df_order_dms.to_pickle(pkl_order)
            df_delivery_dms.to_pickle(pkl_delivery)
            df_invoice.to_pickle(pkl_invoice)
            print(f"  已保存: {pkl_order}")
            print(f"  已保存: {pkl_delivery}")
            print(f"  已保存: {pkl_invoice}")

# ============================================================================
# 2. 发票过滤：类型（统一保留 ZA01/ZB02/ZQ01/ZQ07）、DMS 销售单号非空
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
_prefix = get_output_prefix()
if sales_org_col:
    out1 = f'{_prefix}匹配结果-销售（toB DMS）明细-从SQL（剔除三家）.xlsx'
    out2 = f'{_prefix}匹配结果-销售（toB DMS）明细-其他未匹配-从SQL（剔除三家）.xlsx'
    df_export = df_sales_org_other
else:
    out1 = f'{_prefix}匹配结果-销售（toB DMS）明细-从SQL.xlsx'
    out2 = f'{_prefix}匹配结果-销售（toB DMS）明细-其他未匹配-从SQL.xlsx'
    df_export = df_join

# 超限时先保存 CSV 全量（参考原逻辑）
if len(df_export) > EXCEL_MAX:
    csv_name = out1.replace('.xlsx', '.csv')
    df_export.to_csv(csv_name, index=False, encoding='utf-8-sig')
    print(f"  剔除三家-主明细: 已保存CSV全量 {csv_name} ({len(df_export):,} 行)")

export_with_classification(df_export, out1, "剔除三家-主明细",
                          inv_minus_order_col='SAP-DMS订单金额',
                          amount_label='SAP开票含税金额')

df_not_tested_other = df_export[df_export['大类'] == '5.有缺失'].copy()
export_with_classification(df_not_tested_other, out2, "剔除三家-未匹配",
                          inv_minus_order_col='SAP-DMS订单金额',
                          amount_label='SAP开票含税金额')

# 6.2 导出三家公司的明细和未匹配文件
if sales_org_col and len(df_sales_org_123) > 0:
    print('\n7. 导出三家公司的数据（1240、1250、1260）...')
    
    out3 = f'{_prefix}匹配结果-销售（toB DMS）明细-从SQL（1240、1250、1260）.xlsx'
    out4 = f'{_prefix}匹配结果-销售（toB DMS）明细-其他未匹配-从SQL（1240、1250、1260）.xlsx'
    
    export_with_classification(df_sales_org_123, out3, "三家公司-主明细",
                              inv_minus_order_col='SAP-DMS订单金额',
                              amount_label='SAP开票含税金额')
    
    df_not_tested_123 = df_sales_org_123[df_sales_org_123['大类'] == '5.有缺失'].copy()
    export_with_classification(df_not_tested_123, out4, "三家公司-未匹配",
                              inv_minus_order_col='SAP-DMS订单金额',
                              amount_label='SAP开票含税金额')
elif sales_org_col:
    print('\n7. 警告: 未找到销售组织为1240、1250、1260的数据，跳过三家公司的导出')

print('\nDMS 全年三单匹配完成。')
