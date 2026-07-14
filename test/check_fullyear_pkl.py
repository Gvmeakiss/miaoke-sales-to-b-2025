# -*- coding: utf-8 -*-
"""Check 2025 full-year order/delivery/invoice pkl vs 1-9与10-12月字段差异核对结果.md"""
import os
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.chdir(BASE)

ORDER_COLS_13 = [
    'platform_order_no', 'main_order_no', 'sale_order_no', 'order_type', 'order_status',
    'create_time', 'update_time', 'channel_name', 'item_code', 'line_amount', 'pay_amount', 'item_num', 'channel_name2'
]
DELIVERY_COLS_7 = ['business_type', '订单号', 'external_order_no', '业务时间', '料号', '名称', '已发货数量']

def main():
    print("=" * 60)
    print("全年 pkl 合规检查（依据 1-9与10-12月字段差异核对结果.md）")
    print("=" * 60)
    all_ok = True

    order_pkl = BASE / "2025年全年OMS订单.pkl"
    print("\n【1. 订单】2025年全年OMS订单.pkl")
    if not order_pkl.exists():
        print("  缺失。请先运行 数据预处理_25年全年.py"); all_ok = False
    else:
        df = pd.read_pickle(order_pkl)
        got = list(df.columns)
        if got != ORDER_COLS_13:
            if set(got) != set(ORDER_COLS_13):
                print("  列缺失:", set(ORDER_COLS_13)-set(got)); print("  列多余:", set(got)-set(ORDER_COLS_13)); all_ok = False
            else:
                print("  列顺序与文档不一致")
        else:
            print("  列数=13, 列名与顺序符合（含 line_amount, channel_name2）")
        ct = pd.to_datetime(df.get('create_time'), errors='coerce')
        early = df.loc[ct.dt.month <= 9] if ct.notna().any() else pd.DataFrame()
        if len(early) and 'line_amount' in df.columns:
            print("  1-9月 line_amount 多为 NaN:", early['line_amount'].isna().mean() > 0.9)
        print("  行数:", len(df))

    delivery_pkl = BASE / "2025年全年OMS发货.pkl"
    print("\n【2. 发货】2025年全年OMS发货.pkl")
    if not delivery_pkl.exists():
        print("  缺失。请先运行 数据预处理_25年全年.py"); all_ok = False
    else:
        df = pd.read_pickle(delivery_pkl)
        got = list(df.columns)
        if set(got) != set(DELIVERY_COLS_7) or len(got) != 7:
            print("  列异常: 要求7列", DELIVERY_COLS_7); all_ok = False
        else:
            print("  列数=7, 列名符合。匹配键 订单号+料号 可用")
        print("  行数:", len(df))

    invoice_pkl = BASE / "2025年全年SAP原始数据.pkl"
    print("\n【3. 发票】2025年全年SAP原始数据.pkl")
    if not invoice_pkl.exists():
        print("  缺失。请先运行 数据预处理_25年全年.py 生成全年发票 pkl。"); all_ok = False
    else:
        df = pd.read_pickle(invoice_pkl)
        oms = 'OMS销售单号' in df.columns or 'OMS订单号' in df.columns
        mat = '物料编码' in df.columns or '料号' in df.columns
        if not (oms and mat): print("  匹配用列不足"); all_ok = False
        else: print("  匹配用列 OMS+物料 存在。列数:", len(df.columns), "行数:", len(df))
        if '数据源文件' in df.columns: print("  含 数据源文件")

    print("\n" + "=" * 60)
    print("结论: 三个全年 pkl 均符合" if all_ok else "结论: 存在缺失或不符合，请运行 数据预处理_25年全年.py")
    print("=" * 60)

if __name__ == "__main__":
    main()
