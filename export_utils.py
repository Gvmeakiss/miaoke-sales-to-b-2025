# -*- coding: utf-8 -*-
"""
导出工具 - 参考 refer/difference_analysis.py

生成汇总表及各类型明细 sheet：
- 汇总表：固定行顺序，含四大类及细分、小记、5.not test、仅订单/发货单/订单及发货单/发票、总计、DMS/OMS发票清单
- 各类型明细：按细分场景拆分的明细 sheet
"""

import pandas as pd

from export_schema import apply_export_schema

# 汇总表固定行顺序（含空场景也显示）
SUB_4_1 = '4.1 未完全发货（订单数量>收货单数量=开票数量）'
FIXED_SUMMARY_ROW_ORDER = [
    '1.完全匹配',
    '2.数量一致金额有差异',
    '2.1 尾差<1',
    '2.2 其他',
    '3.金额一致数量有差异',
    '4.均有差异',
    '4.1 未完全发货',
    '4.2 未完全开票',
    '4.3 过量发货',
    '4.4 预制发票',
    '4.5 其他',
    '小记',
    '5. not test',
    '仅订单',
    '仅发货单',
    '仅订单及发货单',
    '仅发票',
    '总计',
]

# 四大类（用于小记统计）
CATEGORIES_FOR_XIAOJI = [
    '1.完全匹配',
    '2.数量一致金额有差异',
    '3.金额一致数量有差异',
    '4.均有差异',
]

# 4.1 在 categories 中的 key（细分场景全名）
SUB_4_1_KEY = SUB_4_1


def _pct_str(count, total):
    """安全计算占比，避免除零"""
    if total == 0:
        return 'N/A'
    return f"{(count / total * 100):.1f}%"


def _amt_pct_str(amt, total_amt, total_amt_positive=None):
    """金额占比。存在冲销(负数)时，分母用正数发票合计"""
    denom = total_amt_positive if (total_amt_positive is not None and total_amt_positive > 0) else total_amt
    if denom == 0 or (denom != denom):  # NaN check
        return 'N/A'
    try:
        return f"{(amt / denom * 100):.1f}%"
    except (ZeroDivisionError, TypeError):
        return 'N/A'


def _compute_order_inv_diff(df, order_inv_diff_col=None, inv_minus_order_col=None):
    """
    计算订单-发票金额差异合计。
    - OMS: order_inv_diff_col='订单-发票金额'
    - DMS: inv_minus_order_col='SAP-DMS订单金额'，订单-发票 = -该列
    """
    if order_inv_diff_col and order_inv_diff_col in df.columns:
        return pd.to_numeric(df[order_inv_diff_col], errors='coerce').fillna(0)
    if inv_minus_order_col and inv_minus_order_col in df.columns:
        return -pd.to_numeric(df[inv_minus_order_col], errors='coerce').fillna(0)
    return pd.Series(0.0, index=df.index)


def _row_from_df(cat_df, cat_name, amount_col, total_rows, total_amt, amt_denom,
                 order_inv_diff_col, inv_minus_order_col, amount_label):
    """从 DataFrame 计算单行汇总"""
    if len(cat_df) == 0:
        return {
            '分类': cat_name,
            '记录数': 0,
            '占比': _pct_str(0, total_rows),
            amount_label: 0.0,
            '发票金额占比': _amt_pct_str(0, total_amt, amt_denom),
            '订单发票金额差异': 0.0,
        }
    cnt = len(cat_df)
    amt = float(pd.to_numeric(cat_df[amount_col], errors='coerce').sum()) if amount_col in cat_df.columns else 0.0
    diff_series = _compute_order_inv_diff(cat_df, order_inv_diff_col, inv_minus_order_col)
    order_inv_diff = float(diff_series.sum())
    return {
        '分类': cat_name,
        '记录数': cnt,
        '占比': _pct_str(cnt, total_rows),
        amount_label: round(amt, 2),
        '发票金额占比': _amt_pct_str(amt, total_amt, amt_denom),
        '订单发票金额差异': round(order_inv_diff, 2),
    }


def generate_summary_report(
    categories, amount_col, total_rows, total_amt,
    order_inv_diff_col=None, inv_minus_order_col=None,
    amount_label='发票金额',
    extra_categories=None,
    invoice_stats=None,
    invoice_stats_label=None,
):
    """
    按固定顺序生成汇总表行（含空场景）。
    小记=四大类合计，总计=小记+仅发票，最后追加发票清单。
    """
    extra_categories = extra_categories or {}
    total_rows = total_rows or 0
    total_amt = total_amt or 0.0

    # 金额占比分母
    all_df = pd.concat([v for v in categories.values() if len(v) > 0], ignore_index=True) if categories else pd.DataFrame()
    amt_denom = total_amt
    if amount_col and amount_col in all_df.columns and len(all_df) > 0:
        pos_amt = pd.to_numeric(all_df[amount_col], errors='coerce').fillna(0)
        if (pos_amt > 0).any():
            amt_denom = pos_amt[pos_amt > 0].sum()

    cat_map = dict(categories) if categories else {}

    def _get_cat(name):
        return cat_map.get(name, pd.DataFrame())

    rows = []
    for cat_name in FIXED_SUMMARY_ROW_ORDER:
        if cat_name == '小记':
            # 小记 = 四大类合计
            xj_cnt = xj_amt = xj_diff = 0
            for c in CATEGORIES_FOR_XIAOJI:
                df_c = _get_cat(c)
                if len(df_c) > 0:
                    xj_cnt += len(df_c)
                    xj_amt += float(pd.to_numeric(df_c[amount_col], errors='coerce').sum()) if amount_col in df_c.columns else 0
                    xj_diff += float(_compute_order_inv_diff(df_c, order_inv_diff_col, inv_minus_order_col).sum())
            rows.append({
                '分类': '小记',
                '记录数': xj_cnt,
                '占比': _pct_str(xj_cnt, total_rows),
                amount_label: round(xj_amt, 2),
                '发票金额占比': _amt_pct_str(xj_amt, total_amt, amt_denom),
                '订单发票金额差异': round(xj_diff, 2),
            })
            continue
        if cat_name == '5. not test':
            df_c = _get_cat('5.有缺失')
            row = _row_from_df(df_c, '5. not test', amount_col, total_rows, total_amt, amt_denom,
                               order_inv_diff_col, inv_minus_order_col, amount_label)
            rows.append(row)
            continue
        if cat_name in ('仅订单', '仅发货单', '仅订单及发货单'):
            df_ec = extra_categories.get(cat_name, pd.DataFrame())
            cnt = len(df_ec)
            rows.append({
                '分类': cat_name,
                '记录数': cnt,
                '占比': _pct_str(cnt, total_rows),
                amount_label: 0.0,
                '发票金额占比': _amt_pct_str(0, total_amt, amt_denom),
                '订单发票金额差异': 0.0,
            })
            continue
        if cat_name == '仅发票':
            df_c = _get_cat('5.有缺失')
            row = _row_from_df(df_c, '仅发票', amount_col, total_rows, total_amt, amt_denom,
                               order_inv_diff_col, inv_minus_order_col, amount_label)
            rows.append(row)
            continue
        if cat_name == '总计':
            xj_cnt = xj_amt = xj_diff = 0
            for r in rows:
                if r['分类'] == '小记':
                    xj_cnt = r['记录数']
                    xj_amt = r[amount_label]
                    xj_diff = r['订单发票金额差异']
                    break
            jy_cnt = jy_amt = jy_diff = 0
            for r in rows:
                if r['分类'] == '仅发票':
                    jy_cnt = r['记录数']
                    jy_amt = r[amount_label]
                    jy_diff = r['订单发票金额差异']
                    break
            zj_cnt = xj_cnt + jy_cnt
            zj_amt = xj_amt + jy_amt
            zj_diff = xj_diff + jy_diff
            rows.append({
                '分类': '总计',
                '记录数': zj_cnt,
                '占比': _pct_str(zj_cnt, total_rows),
                amount_label: round(zj_amt, 2),
                '发票金额占比': _amt_pct_str(zj_amt, total_amt, amt_denom),
                '订单发票金额差异': round(zj_diff, 2),
            })
            continue
        # 普通分类
        df_c = _get_cat(cat_name)
        row = _row_from_df(df_c, cat_name, amount_col, total_rows, total_amt, amt_denom,
                           order_inv_diff_col, inv_minus_order_col, amount_label)
        rows.append(row)

    # 差异占发票小记比例：需小记开票金额
    xiaoji_amt = 0.0
    for r in rows:
        if r['分类'] == '小记':
            xiaoji_amt = r.get(amount_label, 0) or 0
            break

    for r in rows:
        diff_val = r.get('订单发票金额差异', 0) or 0
        if xiaoji_amt != 0 and xiaoji_amt == xiaoji_amt:
            r['差异占发票小记比例'] = f"{(diff_val / xiaoji_amt * 100):.2f}%"
        else:
            r['差异占发票小记比例'] = 'N/A'

    # 发票清单行
    if invoice_stats is not None and invoice_stats_label:
        inv_cnt, inv_amt = invoice_stats[0], invoice_stats[1]
        rows.append({
            '分类': invoice_stats_label,
            '记录数': int(inv_cnt),
            '占比': _pct_str(inv_cnt, total_rows) if total_rows > 0 else 'N/A',
            amount_label: round(float(inv_amt), 2),
            '发票金额占比': _amt_pct_str(inv_amt, total_amt, amt_denom),
            '订单发票金额差异': 0.0,
            '差异占发票小记比例': 'N/A',
        })

    return rows


def get_classification_categories(df_data):
    """按四大类+细分场景构建分类字典"""
    has_big_cat = '大类' in df_data.columns
    has_sub = '细分场景' in df_data.columns
    if not (has_big_cat and has_sub):
        return {'全部数据': df_data}

    return {
        '全部数据': df_data,
        '5.有缺失': df_data[df_data['大类'] == '5.有缺失'].copy(),
        '1.完全匹配': df_data[df_data['细分场景'] == '1.完全匹配'].copy(),
        '2.数量一致金额有差异': df_data[df_data['大类'] == '2.数量一致金额有差异'].copy(),
        '2.1 尾差<1': df_data[df_data['细分场景'] == '2.1 尾差<1'].copy(),
        '2.2 其他': df_data[df_data['细分场景'] == '2.2 其他'].copy(),
        '3.金额一致数量有差异': df_data[df_data['细分场景'] == '3.金额一致数量有差异'].copy(),
        '4.均有差异': df_data[df_data['大类'] == '4.均有差异'].copy(),
        '4.1 未完全发货': df_data[df_data['细分场景'] == SUB_4_1].copy(),
        '4.2 未完全开票': df_data[df_data['细分场景'] == '4.2 未完全开票'].copy(),
        '4.3 过量发货': df_data[df_data['细分场景'] == '4.3 过量发货'].copy(),
        '4.4 预制发票': df_data[df_data['细分场景'] == '4.4 预制发票'].copy(),
        '4.5 其他': df_data[df_data['细分场景'] == '4.5 其他'].copy(),
    }


def export_with_classification(df_data, output_file, file_label='',
                               amount_col=None, amount_label='开票金额',
                               order_inv_diff_col=None, inv_minus_order_col=None,
                               drop_cols=None,
                               extra_categories=None,
                               invoice_stats=None,
                               invoice_stats_label=None):
    """
    导出数据：汇总表 + 各类型明细 sheet。

    Parameters
    ----------
    extra_categories : dict, optional
        {仅订单: df, 仅发货单: df, 仅订单及发货单: df}
    invoice_stats : tuple, optional
        (total_count, total_amount) 用于 DMS/OMS 发票清单
    invoice_stats_label : str, optional
        'DMS发票清单' 或 'OMS发票清单'
    """
    EXCEL_MAX = 1_048_575

    if len(df_data) == 0:
        print(f"  {file_label}: 无数据，跳过导出")
        return

    if amount_col is None:
        for col in df_data.columns:
            if '开票金额' in str(col) or 'SAP开票含税金额' in str(col):
                amount_col = col
                amount_label = '开票金额' if '开票' in str(col) and 'SAP' not in str(col) else 'SAP开票含税金额'
                break

    categories = get_classification_categories(df_data)

    total_rows = len(df_data)
    total_amt = float(pd.to_numeric(df_data[amount_col], errors='coerce').sum()) if amount_col and amount_col in df_data.columns else 0.0

    summary_rows = generate_summary_report(
        categories, amount_col, total_rows, total_amt,
        order_inv_diff_col=order_inv_diff_col,
        inv_minus_order_col=inv_minus_order_col,
        amount_label=amount_label,
        extra_categories=extra_categories or {},
        invoice_stats=invoice_stats,
        invoice_stats_label=invoice_stats_label,
    )
    df_summary = pd.DataFrame(summary_rows)

    # 列顺序：分类、记录数、占比、金额、发票金额占比、订单发票金额差异、差异占发票小记比例
    col_order = ['分类', '记录数', '占比', amount_label, '发票金额占比', '订单发票金额差异', '差异占发票小记比例']
    df_summary = df_summary[[c for c in col_order if c in df_summary.columns]]

    drop_cols = drop_cols or []

    with pd.ExcelWriter(output_file, engine='openpyxl') as w:
        df_summary.to_excel(w, sheet_name='汇总表', index=False)

        for cat_name, cat_df in categories.items():
            if cat_name == '全部数据':
                continue
            if len(cat_df) == 0:
                continue
            export_df = cat_df.copy()
            for dc in drop_cols:
                if dc in export_df.columns:
                    export_df = export_df.drop(columns=[dc])
            export_df = apply_export_schema(export_df)
            if '发票-DMS销售单号' in export_df.columns:
                cols = [c for c in export_df.columns if c != '发票-DMS销售单号']
                cols.append('发票-DMS销售单号')
                export_df = export_df[cols]

            sheet_name = cat_name[:31]
            if len(export_df) <= EXCEL_MAX:
                export_df.to_excel(w, sheet_name=sheet_name, index=False, na_rep='N/A')
            else:
                for i, start in enumerate(range(0, len(export_df), EXCEL_MAX)):
                    part_sheet_name = f"{sheet_name[:25]}_P{i+1}"[:31]
                    export_df.iloc[start:start + EXCEL_MAX].to_excel(w, sheet_name=part_sheet_name, index=False, na_rep='N/A')
                print(f"    {cat_name}: 数据量 {len(export_df):,} 行，已分割为 {(len(export_df) + EXCEL_MAX - 1) // EXCEL_MAX} 个sheet")

    sheet_count = len([(k, c) for k, c in categories.items() if k != '全部数据' and len(c) > 0])
    print(f"  {file_label}: 已保存 {output_file} (汇总表 + {sheet_count} 个分类明细)")
