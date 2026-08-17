#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2025年全年订单、发货、SAP 发票数据预处理脚本

数据源（新）：
- 订单：input/dingdan 下 24年12月到25年6月、25年7月到25年12月 SQL（12 列）
- 发货：input/fayundan 下 24年12月到25年6月、25年7月到26年1月 SQL（9 列）
- 发票：output/fapiao_2025_filtered.pkl（已筛选 ZA01/ZQ01/ZB02/ZQ07）

产出：
- 2025年全年OMS订单.pkl（13 列，兼容匹配逻辑）
- 2025年全年OMS发货.pkl（含 主单号 映射）
- 2025年全年SAP原始数据.pkl（直接复制/加载 fapiao_2025_filtered.pkl）
"""

import pandas as pd
import numpy as np
import os
from pathlib import Path
import chardet

def detect_file_encoding(file_path):
    """检测文件编码"""
    with open(file_path, 'rb') as f:
        return chardet.detect(f.read())['encoding']


get_encoding = detect_file_encoding  # 别名，供内部调用


def _parse_sql_values_line(line):
    """从 SQL VALUES 行解析出值列表，处理引号与 NULL"""
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
    cur = ''
    in_q = False
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
    """解析 SQL 文件中的 VALUES 行，返回 DataFrame 及检测到的编码。"""
    enc = get_encoding(sql_path)
    with open(sql_path, 'r', encoding=enc, errors='ignore') as f:
        lines = f.readlines()
    rows = []
    for line in lines:
        vals = _parse_sql_values_line(line)
        if vals is None:
            continue
        need = min_cols if min_cols is not None else len(expected_cols)
        if len(vals) < need:
            continue
        rows.append(vals[: len(expected_cols)])
    df = pd.DataFrame(rows)
    if len(df.columns) != len(expected_cols):
        df = df.iloc[:, : len(expected_cols)]
    df.columns = expected_cols
    return df, enc

# ---------------------------------------------------------------------------
# 订单：11 列 / 12 列（新数据源）/ 13 列分支，统一为 13 列后合并
# ---------------------------------------------------------------------------

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

def parse_order_sql_11_cols(sql_path):
    """解析 11 列订单 SQL，补 line_amount、channel_name2 为 13 列。"""
    df, enc = _parse_sql_file_to_df(sql_path, ORDER_COLS_11, min_cols=11)
    df.insert(9, 'line_amount', np.nan)
    df['channel_name2'] = np.nan
    df = df[ORDER_COLS_13]
    return df, enc

def parse_order_sql_12_cols(sql_path):
    """解析 12 列订单 SQL（新数据源），补 channel_name2 为 13 列。"""
    df, enc = _parse_sql_file_to_df(sql_path, ORDER_COLS_12, min_cols=12)
    df['channel_name2'] = np.nan
    df = df[ORDER_COLS_13]
    return df, enc

def parse_order_sql_13_cols(sql_path):
    """解析 13 列订单 SQL。"""
    return _parse_sql_file_to_df(sql_path, ORDER_COLS_13, min_cols=13)

def build_oms_order_pkl_full_year(order_dir, output_pkl):
    """合并订单为全年 pkl。新数据源：24年12月到25年6月 + 25年7月到25年12月（12 列）。"""
    order_dir = Path(order_dir)
    out = Path(output_pkl)

    # 新数据源：12 列格式
    sql_1 = order_dir / "24年12月到25年6月订单数据.sql"
    sql_2 = order_dir / "25年7月到25年12月订单数据.sql"
    if not sql_1.exists():
        raise FileNotFoundError(f"订单 SQL 不存在: {sql_1}")
    if not sql_2.exists():
        raise FileNotFoundError(f"订单 SQL 不存在: {sql_2}")

    df_1, enc_1 = parse_order_sql_12_cols(str(sql_1))
    print(f"  24年12月-25年6月订单: 编码={enc_1}, 行数={len(df_1):,}, 已补 channel_name2 为 13 列")
    df_2, enc_2 = parse_order_sql_12_cols(str(sql_2))
    print(f"  25年7月-25年12月订单: 编码={enc_2}, 行数={len(df_2):,}")

    combined = pd.concat([df_1, df_2], ignore_index=True)
    combined.to_pickle(out)
    print(f"  已保存: {out} (总行数: {len(combined):,})")
    return combined

# ---------------------------------------------------------------------------
# 发货：7 列 / 8 列 / 9 列（新数据源），9 列时 main_order_no 映射为 主单号
# ---------------------------------------------------------------------------

DELIVERY_COLS_7 = ['business_type', '订单号', 'external_order_no', '业务时间', '料号', '名称', '已发货数量']
DELIVERY_COLS_8 = ['business_type', '主单号', '订单号', 'external_order_no', '业务时间', '料号', '名称', '已发货数量']
DELIVERY_COLS_9 = ['business_type', '订单号', 'external_order_no', '业务时间', '料号', '名称', '已发货数量', 'document_no', 'main_order_no']

def _fix_delivery_7col_column_swap(df):
    """7 列时：若第 2 列多为数字、第 5 列多为 DD 开头，则对调第 2 与 第 5 列。"""
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

def parse_delivery_sql_file(sql_path):
    """解析单个发货 SQL 文件，返回 DataFrame。支持 7/8/9 列，9 列时新增 主单号=main_order_no。"""
    enc = get_encoding(sql_path)
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
        return pd.DataFrame(), enc
    n = len(rows[0])
    if n == 9:
        cols = DELIVERY_COLS_9
    elif n == 8:
        cols = DELIVERY_COLS_8
    else:
        cols = DELIVERY_COLS_7
    df = pd.DataFrame(rows).iloc[:, : len(cols)]
    df.columns = cols
    if len(cols) == 7:
        _fix_delivery_7col_column_swap(df)
    # 9 列时添加 主单号 以兼容匹配逻辑（order-item 用主单号或订单号）
    if len(cols) == 9 and 'main_order_no' in df.columns:
        df['主单号'] = df['main_order_no']
    return df, enc

def build_oms_delivery_pkl_full_year(delivery_dir, output_pkl):
    """合并发货为全年 pkl。新数据源：24年12月到25年6月 + 25年7月到26年1月（9 列）。"""
    delivery_dir = Path(delivery_dir)
    out = Path(output_pkl)

    d1 = delivery_dir / "24年12月到25年6月发货数据.sql"
    d2 = delivery_dir / "25年7月到26年1月发货数据.sql"
    if not d1.exists():
        raise FileNotFoundError(f"发货 SQL 不存在: {d1}")
    if not d2.exists():
        raise FileNotFoundError(f"发货 SQL 不存在: {d2}")

    df_1, e1 = parse_delivery_sql_file(str(d1))
    print(f"  24年12月-25年6月发货: 编码={e1}, 行数={len(df_1):,}, 列数={len(df_1.columns)}")
    df_2, e2 = parse_delivery_sql_file(str(d2))
    print(f"  25年7月-26年1月发货: 编码={e2}, 行数={len(df_2):,}, 列数={len(df_2.columns)}")

    combined = pd.concat([df_1, df_2], ignore_index=True)
    combined.to_pickle(out)
    print(f"  已保存: {out} (总行数: {len(combined):,})")
    return combined

# ---------------------------------------------------------------------------
# 发票：优先使用 output/fapiao_2025_filtered.pkl，否则读取 Excel
# ---------------------------------------------------------------------------

def process_invoice_from_pkl(input_pkl, output_pkl):
    """从已筛选的发票 pkl 加载并保存为标准路径。"""
    inp = Path(input_pkl)
    out = Path(output_pkl)
    if not inp.exists():
        raise FileNotFoundError(f"发票 pkl 不存在: {inp}")
    df = pd.read_pickle(inp)
    df.to_pickle(out)
    print(f"  已从 {inp.name} 加载: {len(df):,} 行, {len(df.columns)} 列")
    print(f"  已保存: {out}")
    return df

def process_invoice_from_excel(invoice_dir, output_pkl):
    """读取 2025-01～12 月 Excel，concat(join='outer') 后保存为 pkl。"""
    invoice_dir = Path(invoice_dir)
    out = Path(output_pkl)
    if not invoice_dir.exists():
        raise FileNotFoundError(f"发票目录不存在: {invoice_dir}")

    months = [f"{i:02d}" for i in range(1, 13)]
    all_dfs = []
    for m in months:
        for ext in ('XLSX', 'xlsx'):
            p = invoice_dir / f"2025-{m}.{ext}"
            if p.exists():
                try:
                    df = pd.read_excel(p, engine="openpyxl")
                    df["数据源文件"] = p.name
                    all_dfs.append(df)
                    print(f"  读取: {p.name} 行数={len(df):,} 列数={len(df.columns)}")
                except Exception as e:
                    print(f"  读取失败 {p.name}: {e}")
                break
    if not all_dfs:
        raise ValueError("未成功读取任何 1–12 月发票 Excel")

    combined = pd.concat(all_dfs, ignore_index=True, join="outer")
    combined.to_pickle(out)
    print(f"  已保存: {out} (总行数: {len(combined):,}, 列数: {len(combined.columns)})")
    return combined

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("2025年全年 订单、发货、SAP 发票 预处理")
    print("=" * 60)

    base = Path(__file__).resolve().parent.parent
    order_dir = base / "input" / "dingdan"
    delivery_dir = base / "input" / "fayundan"
    invoice_pkl_input = base / "output" / "fapiao_2025_filtered.pkl"
    invoice_dir = base / "妙可 SAP发票拆分月份"
    if not invoice_dir.exists():
        invoice_dir = base / "SAP开票数据"

    if not order_dir.exists():
        raise FileNotFoundError(f"订单目录不存在: {order_dir}")

    if not delivery_dir.exists():
        raise FileNotFoundError(f"发货目录不存在: {delivery_dir}")

    order_pkl = base / "2025年全年OMS订单.pkl"
    delivery_pkl = base / "2025年全年OMS发货.pkl"
    invoice_pkl = base / "2025年全年SAP原始数据.pkl"

    # 1. 订单
    print("\n【1. 订单】")
    build_oms_order_pkl_full_year(str(order_dir), str(order_pkl))

    # 2. 发货
    print("\n【2. 发货】")
    build_oms_delivery_pkl_full_year(str(delivery_dir), str(delivery_pkl))

    # 3. 发票：优先 pkl，否则 Excel
    print("\n【3. 发票】")
    if invoice_pkl_input.exists():
        process_invoice_from_pkl(str(invoice_pkl_input), str(invoice_pkl))
    elif invoice_dir.exists():
        process_invoice_from_excel(str(invoice_dir), str(invoice_pkl))
    else:
        raise FileNotFoundError("未找到发票: output/fapiao_2025_filtered.pkl 或 妙可 SAP发票拆分月份 或 SAP开票数据")

    print("\n" + "=" * 60)
    print("全年预处理完成，产出：")
    for p in (order_pkl, delivery_pkl, invoice_pkl):
        print(f"  - {p}")
    print("=" * 60)

if __name__ == "__main__":
    main()
