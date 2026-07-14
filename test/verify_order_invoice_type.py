#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全量验证：在 channel 与 platform_order_no 两种判据下归属不同的订单，
在发票中属于哪一类（DMS销售单号 非空=DMS发票，为空=OMS发票）。
"""

import pandas as pd
from pathlib import Path

from config import OUTPUT_DIR, PKL_DIR, ORDER_PKL, INVOICE_PKL


def _is_empty(ser):
    return ser.isna() | (ser.astype(str).str.strip() == "")


def _is_nonempty(ser):
    return ser.notna() & (ser.astype(str).str.strip() != "")


def main():
    df_order = pd.read_pickle(ORDER_PKL)
    df_inv = pd.read_pickle(INVOICE_PKL)

    # 排除作废/取消
    df_order = df_order[~df_order["order_status"].isin(["OBSOLETE", "CANCEL"])]

    # 判据
    has_platform = _is_nonempty(df_order["platform_order_no"])
    channel_dms = df_order["channel_name"].astype(str).str.contains("DMS", case=False, na=False)

    # 不一致的订单
    # A: channel=OMS 但 platform 非空 → channel判OMS，业务判DMS
    type_a = ~channel_dms & has_platform
    # B: channel=DMS 但 platform 空 → channel判DMS，业务判OMS
    type_b = channel_dms & ~has_platform

    df_a = df_order[type_a]
    df_b = df_order[type_b]

    print("=" * 70)
    print("两种判据归属不同的订单验证")
    print("=" * 70)
    print(f"订单总数: {len(df_order):,}")
    print(f"A 类 (channel=OMS 但 platform_order_no 非空): {len(df_a):,} 行")
    print(f"B 类 (channel=DMS 但 platform_order_no 为空): {len(df_b):,} 行")
    print()

    # 发票列
    dms_col = next((c for c in df_inv.columns if "DMS" in str(c) and "销售" in str(c) and "单号" in str(c)), None)
    oms_col = next((c for c in ["OMS销售单号", "OMS订单号", "销售单号"] if c in df_inv.columns), None)
    mat_col = next((c for c in ["物料编码", "料号"] if c in df_inv.columns), None)

    if not dms_col or not oms_col or not mat_col:
        print("发票缺少必要列，无法验证")
        return

    inv_dms = df_inv[_is_nonempty(df_inv[dms_col])]
    inv_oms = df_inv[_is_empty(df_inv[dms_col])]
    print(f"发票: DMS发票(DMS销售单号非空) {len(inv_dms):,} 行, OMS发票(DMS销售单号为空) {len(inv_oms):,} 行")
    print()

    def check_matches(df_ord, label, order_key_col, order_key_name):
        """检查订单在发票中的匹配情况（全量）"""
        if df_ord.empty:
            print(f"{label}: 无样本")
            return
        df_ord = df_ord.copy()
        df_ord["item_code"] = df_ord["item_code"].astype(str).str.replace(r"\.0$", "", regex=True)
        df_ord["_key"] = df_ord[order_key_col].astype(str) + "_" + df_ord["item_code"]

        # 匹配 DMS 发票
        inv_dms["_key"] = inv_dms[dms_col].astype(str) + "_" + inv_dms[mat_col].astype(str).str.replace(r"\.0$", "", regex=True)
        match_dms = df_ord["_key"].isin(inv_dms["_key"])

        # 匹配 OMS 发票 (OMS销售单号 + 物料；主订单号优先)
        oms_main = df_ord.get("main_order_no", df_ord.get("sale_order_no"))
        df_ord["_oms_key"] = oms_main.fillna(df_ord.get("sale_order_no", pd.Series(dtype=object))).astype(str) + "_" + df_ord["item_code"]
        inv_oms["_key"] = inv_oms[oms_col].astype(str) + "_" + inv_oms[mat_col].astype(str).str.replace(r"\.0$", "", regex=True)
        match_oms = df_ord["_oms_key"].isin(inv_oms["_key"])

        n_dms = match_dms.sum()
        n_oms = match_oms.sum()
        n_both = (match_dms & match_oms).sum()
        n_none = (~match_dms & ~match_oms).sum()

        print(f"{label} 全量 ({len(df_ord):,} 行，按 {order_key_name} 匹配):")
        print(f"  匹配 DMS 发票（属 DMS 订单）: {n_dms:,} 条 ({100*n_dms/len(df_ord):.1f}%)")
        print(f"  匹配 OMS 发票（属 OMS 订单）: {n_oms:,} 条 ({100*n_oms/len(df_ord):.1f}%)")
        print(f"  两者都匹配: {n_both:,} 条")
        print(f"  两者都不匹配: {n_none:,} 条 ({100*n_none/len(df_ord):.1f}%)")
        print()

    # A 类：channel=OMS 但 platform 非空
    print("-" * 70)
    print("A 类: channel_name 不含 DMS（OMS） 但 platform_order_no 非空")
    print("  业务逻辑: 应视为 DMS 订单（有 DMS 订单号）")
    check_matches(df_a, "A 类订单", "platform_order_no", "platform_order_no")

    # B 类：channel=DMS 但 platform 空
    print("-" * 70)
    print("B 类: channel_name 含 DMS 但 platform_order_no 为空")
    print("  业务逻辑: 应视为 OMS 订单（无 DMS 订单号）")
    check_matches(df_b, "B 类订单", "sale_order_no", "sale_order_no(OMS子订单号)")

    # A 类补充：按 OMS 键（sale_order_no/main_order_no）匹配的结果
    if not df_a.empty:
        print("-" * 70)
        print("A 类补充：若按 OMS 键（sale_order_no）匹配 OMS 发票")
        check_matches(df_a, "A 类订单", "sale_order_no", "sale_order_no(OMS)")

    # 导出：与业务逻辑违和的订单
    # 导出：与业务逻辑违和的订单
    if not df_a.empty:
        df_a = df_a.copy()
        df_a.insert(0, "违和类型", "A: channel=OMS 但 platform_order_no 非空（业务视为DMS）")
    if not df_b.empty:
        df_b = df_b.copy()
        df_b.insert(0, "违和类型", "B: channel=DMS 但 platform_order_no 为空（业务视为OMS）")
    df_ab = pd.concat([df_a, df_b], ignore_index=True)
    if not df_ab.empty:
        OUTPUT_DIR.mkdir(exist_ok=True)
        out_path = OUTPUT_DIR / "与业务逻辑违和的订单.xlsx"
        df_ab.to_excel(out_path, index=False, engine="openpyxl")
        print("-" * 70)
        print(f"已导出: {out_path} ({len(df_ab):,} 行)")
    else:
        print("-" * 70)
        print("无与业务逻辑违和的订单，未生成导出文件。")


if __name__ == "__main__":
    main()
