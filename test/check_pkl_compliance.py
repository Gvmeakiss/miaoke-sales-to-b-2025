# -*- coding: utf-8 -*-
"""
检查全年 订单、发货、发票 pkl 是否按规范生成（列结构、匹配键等）。
"""
import os
import sys
from pathlib import Path

# 确保可导入 code 下的 config
CODE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE_DIR))
os.chdir(CODE_DIR.parent)

from config import ORDER_PKL, DELIVERY_PKL, INVOICE_PKL

# 文档约定的 schema
ORDER_COLS_13 = [
    'platform_order_no', 'main_order_no', 'sale_order_no', 'order_type', 'order_status',
    'create_time', 'update_time', 'channel_name', 'item_code', 'line_amount', 'pay_amount', 'item_num', 'channel_name2'
]
DELIVERY_COLS_7 = ['business_type', '订单号', 'external_order_no', '业务时间', '料号', '名称', '已发货数量']


def main():
    import pandas as pd

    print("=" * 60)
    print("全年 pkl 合规检查（依据 1-9与10-12月字段差异核对结果.md）")
    print("=" * 60)

    all_ok = True

    # ---- 订单 ----
    order_pkl = ORDER_PKL
    print("\n【1. 订单】2025年全年OMS订单.pkl")
    if not order_pkl.exists():
        print("  缺失：文件不存在。请先运行 preprocess_oms_full_year.py")
        all_ok = False
    else:
        df = pd.read_pickle(order_pkl)
        want = ORDER_COLS_13
        got = list(df.columns)
        if got != want:
            missing = set(want) - set(got)
            extra = set(got) - set(want)
            if missing:
                print(f"  列缺失: {missing}")
                all_ok = False
            if extra:
                print(f"  列多余: {extra}")
            if not missing and not extra and got != want:
                print(f"  列顺序与文档不一致。文档顺序: {want[:5]}...")
                all_ok = False
        else:
            print(f"  列数=13, 列名与顺序符合文档（含 line_amount、channel_name2）")
        df['ct'] = pd.to_datetime(df.get('create_time'), errors='coerce')
        early = df[df['ct'].dt.month <= 9] if 'ct' in df.columns and df['ct'].notna().any() else pd.DataFrame()
        if len(early) > 0 and 'line_amount' in df.columns:
            na_line = early['line_amount'].isna().sum()
            if na_line >= len(early) * 0.9:
                print(f"  合理性：1-9 月区段 line_amount 多为 NaN（符合 1-9 补空）")
            else:
                print(f"  提示：1-9 月区段 line_amount 非空较多，请确认来源")
        print(f"  行数: {len(df):,}")

    # ---- 发货 ----
    delivery_pkl = DELIVERY_PKL
    print("\n【2. 发货】2025年全年OMS发货.pkl")
    if not delivery_pkl.exists():
        print("  缺失：文件不存在。请先运行 preprocess_oms_full_year.py")
        all_ok = False
    else:
        df = pd.read_pickle(delivery_pkl)
        want = DELIVERY_COLS_7
        got = list(df.columns)
        if set(got) != set(want) or len(got) != 7:
            missing = set(want) - set(got)
            extra = set(got) - set(want)
            if missing:
                print(f"  列缺失: {missing}")
                all_ok = False
            if extra:
                print(f"  列多余: {extra}")
            if len(got) != 7:
                print(f"  列数={len(got)}，文档要求 7 列")
                all_ok = False
        else:
            if got == want:
                print(f"  列数=7, 列名与顺序符合文档")
            else:
                print(f"  列数=7, 列名齐全但顺序与文档可能不同: {got}")
        if '订单号' in df.columns and '料号' in df.columns:
            print(f"  匹配键 订单号+料号 可用")
        else:
            print(f"  匹配键 订单号 或 料号 缺失")
            all_ok = False
        print(f"  行数: {len(df):,}")

    # ---- 发票 ----
    invoice_pkl = INVOICE_PKL
    print("\n【3. 发票】2025年全年SAP原始数据.pkl")
    if not invoice_pkl.exists():
        print("  缺失：文件不存在。请先运行 preprocess_oms_full_year.py 生成全年发票 pkl。")
        all_ok = False
    else:
        df = pd.read_pickle(invoice_pkl)
        oms = 'OMS销售单号' in df.columns or 'OMS订单号' in df.columns
        mat = '物料编码' in df.columns or '料号' in df.columns
        if not (oms and mat):
            print(f"  匹配用列不足: OMS销售单号/OMS订单号={oms}, 物料编码/料号={mat}")
            all_ok = False
        else:
            print(f"  匹配用列 OMS销售单号/物料编码（或兼容列）存在")
        if 'DMS销售单号' in df.columns:
            print(f"  DMS销售单号 存在，可做 DMS 映射")
        if '发票类型' in df.columns or any('发票类型' in str(c) for c in df.columns):
            print(f"  发票类型 存在，可做类型过滤")
        print(f"  列数: {len(df.columns)}（文档：1-9 约 97–98，10-12 多 1 列，concat join=outer 后 >=97）")
        if '数据源文件' in df.columns:
            print(f"  已含 数据源文件 列，可区分月份")
        print(f"  行数: {len(df):,}")

    print("\n" + "=" * 60)
    if all_ok:
        print("结论：三个全年 pkl 均符合文档规范。")
    else:
        print("结论：存在缺失或不符合项，请根据上文补齐或重新运行 preprocess_oms_full_year.py。")
    print("=" * 60)


if __name__ == "__main__":
    main()
