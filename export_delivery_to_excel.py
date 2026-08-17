#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将发运单（2025年全年OMS发货.pkl）导出至 Excel。
"""

import pandas as pd
from pathlib import Path

from config import DELIVERY_PKL, OUTPUT_DIR, OUTPUT_PREFIX


def main():
    if not DELIVERY_PKL.exists():
        print(f"错误: 发运单 pkl 不存在: {DELIVERY_PKL}")
        print("请先运行 preprocess_oms_full_year.py 生成发运单数据。")
        return

    df = pd.read_pickle(DELIVERY_PKL)

    # 业务时间转为日期格式便于阅读
    if '业务时间' in df.columns:
        df = df.copy()
        df['业务时间'] = pd.to_datetime(df['业务时间'], format='mixed', errors='coerce')

    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f'{OUTPUT_PREFIX}发运单.xlsx'

    # Excel 单 sheet 最大行数限制，超出则分片
    EXCEL_MAX = 1_048_575
    if len(df) <= EXCEL_MAX:
        df.to_excel(out_path, index=False, engine='openpyxl')
        print(f"已导出: {out_path} ({len(df):,} 行, {len(df.columns)} 列)")
    else:
        with pd.ExcelWriter(out_path, engine='openpyxl') as w:
            for i, start in enumerate(range(0, len(df), EXCEL_MAX)):
                chunk = df.iloc[start : start + EXCEL_MAX]
                sheet_name = f'发运单_P{i+1}'
                chunk.to_excel(w, sheet_name=sheet_name, index=False)
        print(f"已导出: {out_path} (共 {len(df):,} 行, 分 {(len(df) + EXCEL_MAX - 1) // EXCEL_MAX} 个 sheet)")


if __name__ == '__main__':
    main()
