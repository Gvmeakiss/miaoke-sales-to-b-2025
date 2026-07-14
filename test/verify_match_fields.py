#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核对三单（订单、发货、发票）pkl 中的字段是否满足匹配要求。

匹配键（OMS）：
- 订单：main_order_no + item_code，主订单号空时用 sale_order_no
- 发货：主单号 + 料号，主单号空时用 订单号
- 发票：OMS销售单号（主订单号）+ 物料编码

匹配键（DMS）：
- 订单：platform_order_no + item_code
- 发货：external_order_no + 料号
- 发票：DMS销售单号 + 物料编码

关键数值字段：
- 订单：pay_amount, item_num
- 发货：已发货数量
- 发票：实际金额(ZFN1)/含税金额, 开票数量(基本单位)
"""

import pandas as pd
from pathlib import Path

from config import ORDER_PKL, DELIVERY_PKL, INVOICE_PKL

REQUIRED_ORDER = ['sale_order_no', 'main_order_no', 'item_code', 'pay_amount', 'item_num', 'channel_name', 'create_time']
REQUIRED_DELIVERY = ['订单号', '料号', '已发货数量', 'external_order_no', '业务时间']
REQUIRED_DELIVERY_ALT = ['主单号']  # 主单号可选，用于order-item优化
REQUIRED_INVOICE_OMS = ['OMS销售单号', '物料编码', 'DMS销售单号']
REQUIRED_INVOICE_AMOUNT = ['实际金额（ZFN1）', '含税金额']  # 至少其一
REQUIRED_INVOICE_QTY = ['开票数量（基本单位数量）', '开票数量（销售单位）']  # 至少其一


def check_order(df):
    missing = [c for c in REQUIRED_ORDER if c not in df.columns]
    ok = len(missing) == 0
    print(f"  订单: {'✓ 满足' if ok else '✗ 缺失 ' + str(missing)}")
    if ok:
        print(f"    行数={len(df):,}, 列数={len(df.columns)}")
    return ok


def check_delivery(df):
    missing = [c for c in REQUIRED_DELIVERY if c not in df.columns]
    has_main = '主单号' in df.columns
    ok = len(missing) == 0
    print(f"  发货: {'✓ 满足' if ok else '✗ 缺失 ' + str(missing)}")
    if has_main:
        print(f"    含主单号列，可优化order-item")
    if ok:
        print(f"    行数={len(df):,}, 列数={len(df.columns)}")
    return ok


def check_invoice(df):
    oms_ok = all(c in df.columns for c in REQUIRED_INVOICE_OMS)
    amt_ok = any(c in df.columns for c in REQUIRED_INVOICE_AMOUNT)
    qty_ok = any(c in df.columns for c in REQUIRED_INVOICE_QTY)
    ok = oms_ok and amt_ok and qty_ok
    print(f"  发票: {'✓ 满足' if ok else '✗ 有缺失'}")
    if not oms_ok:
        print(f"    匹配键缺失: OMS销售单号/物料编码/DMS销售单号")
    if not amt_ok:
        print(f"    金额列缺失: 需 实际金额（ZFN1）或 含税金额")
    if not qty_ok:
        print(f"    数量列缺失: 需 开票数量（基本单位数量）或 开票数量（销售单位）")
    if ok:
        print(f"    行数={len(df):,}, 列数={len(df.columns)}")
    return ok


def main():
    print("=" * 60)
    print("三单字段匹配要求核对")
    print("=" * 60)

    order_pkl = ORDER_PKL
    delivery_pkl = DELIVERY_PKL
    invoice_pkl = INVOICE_PKL

    all_ok = True

    if order_pkl.exists():
        print("\n【1. 订单】")
        df = pd.read_pickle(order_pkl)
        all_ok = check_order(df) and all_ok
    else:
        print(f"\n【1. 订单】 文件不存在: {order_pkl}\n  请先运行 preprocess_oms_full_year.py")

    if delivery_pkl.exists():
        print("\n【2. 发货】")
        df = pd.read_pickle(delivery_pkl)
        all_ok = check_delivery(df) and all_ok
    else:
        print(f"\n【2. 发货】 文件不存在: {delivery_pkl}\n  请先运行 preprocess_oms_full_year.py")

    if invoice_pkl.exists():
        print("\n【3. 发票】")
        df = pd.read_pickle(invoice_pkl)
        all_ok = check_invoice(df) and all_ok
    else:
        print(f"\n【3. 发票】 文件不存在: {invoice_pkl}\n  请先运行 preprocess_oms_full_year.py 并确保 output/fapiao_2025_filtered.pkl 存在")

    print("\n" + "=" * 60)
    print("结论: 三单字段满足匹配要求" if all_ok else "结论: 存在缺失，请检查上述输出")
    print("=" * 60)


if __name__ == "__main__":
    main()
