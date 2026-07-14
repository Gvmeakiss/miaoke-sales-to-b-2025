# -*- coding: utf-8 -*-
"""
OMS 三单匹配（统一脚本，由 config 配置时间范围、路径、筛选条件）

修改 config.TIME_RANGE 切换 1-9 月 / 全年。
"""

import pandas as pd
import warnings
from pathlib import Path

from config import get_oms_config, get_output_prefix, ORDER_STATUS_EXCLUDE, INVOICE_TYPES, OUTPUT_DIR
from scenario_utils import assign_scenario_oms, SCENARIO_DESC
from export_utils import export_with_classification

warnings.filterwarnings('ignore')

BASE = Path(__file__).resolve().parent.parent


def _normalize_material_code(ser):
    """物料/料号/item 转字符串并去掉因 float 产生的 '.0'。"""
    return ser.astype(str).str.replace(r'\.0$', '', regex=True)


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


def load_oms_order_delivery_invoice():
    """根据 config 加载订单、发货、发票数据"""
    cfg = get_oms_config()
    prefix = get_output_prefix()

    pkl_cache = cfg.get('use_pkl_cache') and cfg.get('pkl_cache_dir')
    if pkl_cache:
        pkl_dir = Path(pkl_cache)
        pkl_dir.mkdir(exist_ok=True)
        cache_order = pkl_dir / 'oms_order.pkl'
        cache_delivery = pkl_dir / 'oms_delivery.pkl'
        cache_invoice = pkl_dir / 'oms_invoice.pkl'
        if cache_order.exists() and cache_delivery.exists() and cache_invoice.exists():
            print('  从PKL缓存加载数据...')
            return pd.read_pickle(cache_order), pd.read_pickle(cache_delivery), pd.read_pickle(cache_invoice)

    order_pkl = Path(cfg['order_pkl'])
    delivery_pkl = Path(cfg['delivery_pkl'])
    invoice_pkl = Path(cfg['invoice_pkl'])

    for n, p in [('订单', order_pkl), ('发货', delivery_pkl), ('发票', invoice_pkl)]:
        if not p.exists():
            raise FileNotFoundError(f"未找到{n} pkl: {p}\n请先运行数据预处理生成 pkl 文件")

    print('  从PKL文件读取原始数据...')
    df_order = pd.read_pickle(str(order_pkl))
    df_delivery = pd.read_pickle(str(delivery_pkl))
    df_invoice = pd.read_pickle(str(invoice_pkl))

    if pkl_cache:
        pkl_dir = Path(pkl_cache)
        pkl_dir.mkdir(exist_ok=True)
        df_order.to_pickle(pkl_dir / 'oms_order.pkl')
        df_delivery.to_pickle(pkl_dir / 'oms_delivery.pkl')
        df_invoice.to_pickle(pkl_dir / 'oms_invoice.pkl')
        print('  已保存到PKL缓存')

    return df_order, df_delivery, df_invoice


# ============================================================================
# 主流程
# ============================================================================
def main():
    prefix = get_output_prefix()
    print(f"开始 OMS 三单匹配（{prefix}）...")

    df_order, df_delivery, df_invoice = load_oms_order_delivery_invoice()
    print(f"  订单: {len(df_order):,} 行")
    print(f"  发货: {len(df_delivery):,} 行")
    print(f"  发票: {len(df_invoice):,} 行")

    # 发票列名兼容
    oms_col = next((c for c in ['OMS销售单号', 'OMS订单号', '销售单号'] if c in df_invoice.columns), 'OMS销售单号')
    mat_col = next((c for c in ['物料编码', '料号', '品号', '物料编号'] if c in df_invoice.columns), '物料编码')

    # 2. 数据预处理
    print("\n数据预处理...")
    for ex in ORDER_STATUS_EXCLUDE:
        df_order = df_order[df_order['order_status'] != ex]
    print(f"  订单过滤后: {len(df_order):,} 行")

    # 订单数据源规范：platform_order_no（DMS订单号）为空 = OMS 订单（直接 OMS 下单）
    if 'platform_order_no' in df_order.columns:
        oms_order_mask = df_order['platform_order_no'].isna() | (
            df_order['platform_order_no'].astype(str).str.strip() == ''
        )
        df_order = df_order[oms_order_mask]
        print(f"  订单数据源: OMS 订单（DMS订单号 为空）{len(df_order):,} 行")

    if '业务时间' in df_delivery.columns:
        df_delivery['业务时间'] = pd.to_datetime(df_delivery['业务时间'], format='mixed', errors='coerce')

    # 发票类型过滤
    invoice_type_col = None
    for col in df_invoice.columns:
        if '发票类型' in str(col):
            invoice_type_col = col
            break
    if not invoice_type_col and len(df_invoice.columns) > 14:
        invoice_type_col = df_invoice.columns[14]
    if invoice_type_col:
        ser = df_invoice[invoice_type_col].astype(str)
        is_code = ser.str.fullmatch(r'[A-Z]{2}\d{2}', na=False).mean() > 0.5
        if is_code:
            keep = ser.isin(INVOICE_TYPES)
        else:
            keep = (ser.str.contains(r'标准发票\s*[（(]?\s*2B', regex=True) |
                    ser.str.contains('标准退货发票', regex=False) |
                    ser.str.contains(r'取消标准发票\s*[（(]?\s*2B', regex=True) |
                    ser.str.contains('取消标准退货发票', regex=False))
        df_invoice = df_invoice[keep]
    print(f"  发票过滤后: {len(df_invoice):,} 行")

    # 发票数据源规范：DMS销售单号 为空 = OMS 发票，仅用于 OMS 匹配
    if 'DMS销售单号' in df_invoice.columns:
        dms_col = df_invoice['DMS销售单号']
        mask_oms = dms_col.isna() | (dms_col.astype(str).str.strip() == '')
        df_invoice = df_invoice[mask_oms].copy()
        print(f"  发票数据源: OMS 发票（DMS销售单号 为空）{len(df_invoice):,} 行")

    # 发票 → order-item
    inv_with_oms = pd.DataFrame()
    if oms_col in df_invoice.columns and mat_col in df_invoice.columns:
        inv_with_oms = df_invoice[df_invoice[oms_col].notna()].copy()
        inv_with_oms['order-item'] = inv_with_oms[oms_col].astype(str) + _normalize_material_code(inv_with_oms[mat_col])

    df_invoice_used = inv_with_oms

    # 3. 匹配键
    print("\n创建匹配键 order-item...")
    df_order['_oms_main'] = df_order['main_order_no'].fillna(df_order['sale_order_no'])
    df_order['order-item'] = df_order['_oms_main'].astype(str) + _normalize_material_code(df_order['item_code'])
    df_order.drop(columns=['_oms_main'], inplace=True)

    if '主单号' in df_delivery.columns and '订单号' in df_delivery.columns and '料号' in df_delivery.columns:
        df_delivery['_oms_main'] = df_delivery['主单号'].fillna(df_delivery['订单号'])
        df_delivery['order-item'] = df_delivery['_oms_main'].astype(str) + _normalize_material_code(df_delivery['料号'])
        df_delivery.drop(columns=['_oms_main'], inplace=True)
    elif '订单号' in df_delivery.columns and '料号' in df_delivery.columns:
        df_delivery['order-item'] = df_delivery['订单号'].astype(str) + _normalize_material_code(df_delivery['料号'])
    else:
        raise ValueError("发货缺少 订单号 或 料号")

    if oms_col in df_invoice.columns and mat_col in df_invoice.columns:
        df_invoice['order-item'] = df_invoice[oms_col].astype(str) + _normalize_material_code(df_invoice[mat_col])

    # 4. 聚合
    df_order['pay_amount'] = pd.to_numeric(df_order['pay_amount'], errors='coerce').round(2)
    df_order['item_num'] = pd.to_numeric(df_order['item_num'], errors='coerce').round(2)
    order_agg_dict = {'pay_amount': 'sum', 'item_num': 'sum'}
    for col in ['sale_order_no', 'platform_order_no', 'main_order_no', 'channel_name', 'order_type', 'order_status', 'create_time', 'update_time', 'item_code']:
        if col in df_order.columns:
            order_agg_dict[col] = 'first'
    order_agg = df_order.groupby('order-item', as_index=False).agg(order_agg_dict)
    order_agg.rename(columns={'pay_amount': '订单金额', 'item_num': '订单数量',
        'sale_order_no': '订单-销售订单号', 'platform_order_no': '订单-平台订单号', 'main_order_no': '订单-主订单号',
        'channel_name': '订单-渠道名称', 'order_type': '订单-订单类型', 'order_status': '订单-订单状态',
        'create_time': '订单-创建时间', 'update_time': '订单-更新时间', 'item_code': '订单-商品代码'}, inplace=True)

    df_delivery['已发货数量'] = pd.to_numeric(df_delivery['已发货数量'], errors='coerce').round(2)
    delivery_agg_dict = {'已发货数量': 'sum'}
    for col in ['订单号', '主单号', 'external_order_no', '业务时间', '料号', '名称', 'business_type', 'document_no']:
        if col in df_delivery.columns:
            delivery_agg_dict[col] = 'first'
    delivery_agg = df_delivery.groupby('order-item', as_index=False).agg(delivery_agg_dict)
    delivery_agg.rename(columns={'已发货数量': '发货数量', '订单号': '发货-订单号', '主单号': '发货-主单号',
        'external_order_no': '发货-外部订单号', '业务时间': '发货-业务时间', '料号': '发货-料号',
        '名称': '发货-商品名称', 'business_type': '发货-业务类型', 'document_no': '发货-发货单号'}, inplace=True)

    amount_col = quantity_col = None
    for c in df_invoice_used.columns:
        if '实际金额' in str(c) or ('金额' in str(c) and 'ZFN1' in str(c)):
            amount_col = c
        if '开票数量' in str(c) or ('数量' in str(c) and '基本单位' in str(c)):
            quantity_col = c

    if df_invoice_used.empty or not amount_col or not quantity_col:
        invoice_agg = pd.DataFrame({'order-item': [], '开票金额': [], '开票数量': []})
    else:
        df_invoice_used[amount_col] = pd.to_numeric(df_invoice_used[amount_col], errors='coerce').round(2)
        df_invoice_used[quantity_col] = pd.to_numeric(df_invoice_used[quantity_col], errors='coerce').round(2)
        invoice_agg_dict = {amount_col: 'sum', quantity_col: 'sum'}
        for candidates, label in [
            (['SAP发票号', 'SAP发票编号'], '发票-SAP发票号'),
            (['销售组织', '销售组织代码'], '发票-销售组织'),
            (['发票类型', '发票类型.1'], '发票-发票类型'),
            (['DMS销售单号'], '发票-DMS销售单号'),
        ]:
            for col in df_invoice_used.columns:
                if any(c in str(col) for c in candidates) and col not in invoice_agg_dict:
                    invoice_agg_dict[col] = 'first'
                    break
        if oms_col in df_invoice_used.columns and oms_col not in invoice_agg_dict:
            invoice_agg_dict[oms_col] = 'first'
        if mat_col in df_invoice_used.columns and mat_col not in invoice_agg_dict:
            invoice_agg_dict[mat_col] = 'first'
        invoice_agg = df_invoice_used.groupby('order-item', as_index=False).agg(invoice_agg_dict)
        invoice_agg.rename(columns={amount_col: '开票金额', quantity_col: '开票数量'}, inplace=True)
    for c in ['开票金额', '开票数量']:
        if c not in invoice_agg.columns:
            invoice_agg[c] = pd.Series(dtype=float)

    # 5. 匹配与分类
    df_matched = invoice_agg.merge(delivery_agg, on='order-item', how='left')
    df_matched = df_matched.merge(order_agg, on='order-item', how='left')
    df_nottested = order_agg.merge(delivery_agg, on='order-item', how='outer')
    df_nottested = df_nottested.merge(invoice_agg, on='order-item', how='outer')
    df_nottested = df_nottested[df_nottested['开票数量'].isna()]

    df_matched['订单-发货数量'] = pd.to_numeric(df_matched['订单数量'], errors='coerce') - pd.to_numeric(df_matched['发货数量'], errors='coerce')
    df_matched['订单-开票数量'] = pd.to_numeric(df_matched['订单数量'], errors='coerce') - pd.to_numeric(df_matched['开票数量'], errors='coerce')
    df_matched['发货-开票数量'] = pd.to_numeric(df_matched['发货数量'], errors='coerce') - pd.to_numeric(df_matched['开票数量'], errors='coerce')
    df_matched['订单-发票金额'] = (pd.to_numeric(df_matched['订单金额'], errors='coerce') - pd.to_numeric(df_matched['开票金额'], errors='coerce')).round(2)

    key_cols = ['订单金额', '订单数量', '发货数量', '开票金额', '开票数量']
    df_matched['2.Not test'] = df_matched[key_cols].isna().any(axis=1)
    df_matched = assign_scenario_oms(df_matched)

    print("\n分类统计:")
    for cat in ['1.完全匹配', '2.数量一致金额有差异', '3.金额一致数量有差异', '4.均有差异', '5.有缺失']:
        cnt = (df_matched['大类'] == cat).sum()
        print(f"  {cat}: {cnt:,}")

    # 6. 销售组织分组
    sales_org_col = None
    for col in df_matched.columns:
        if '销售组织' in str(col):
            sales_org_col = col
            break
    sales_org_str = [str(v) for v in [1240, 1250, 1260]]
    if sales_org_col:
        df_sales_org_123 = df_matched[df_matched[sales_org_col].astype(str).isin(sales_org_str)].copy()
        df_sales_org_other = df_matched[~df_matched[sales_org_col].astype(str).isin(sales_org_str)].copy()
    else:
        df_sales_org_123 = pd.DataFrame()
        df_sales_org_other = df_matched.copy()

    # 7. df_nottested 分类（仅订单、仅发货单、仅订单及发货单）及 2025 年过滤
    has_ord = '订单数量' in df_nottested.columns
    has_dlv = '发货数量' in df_nottested.columns
    ord_na = df_nottested['订单数量'].isna() if has_ord else pd.Series(True, index=df_nottested.index)
    dlv_na = df_nottested['发货数量'].isna() if has_dlv else pd.Series(True, index=df_nottested.index)

    date_cols_oms = ['订单-创建时间', '发货-业务时间', '发票-开票日期']
    extra_categories = {
        '仅订单': _filter_2025(df_nottested[~ord_na & dlv_na], date_cols_oms),
        '仅发货单': _filter_2025(df_nottested[ord_na & ~dlv_na], date_cols_oms),
        '仅订单及发货单': _filter_2025(df_nottested[~ord_na & ~dlv_na], date_cols_oms),
    }

    # OMS 发票总条数、总金额（df_invoice_used）
    amt_col_inv = amount_col if amount_col else next(
        (c for c in df_invoice_used.columns if '实际金额' in str(c) or ('金额' in str(c) and 'ZFN1' in str(c))), None
    )
    oms_inv_cnt = len(df_invoice_used)
    oms_inv_amt = float(pd.to_numeric(df_invoice_used[amt_col_inv], errors='coerce').sum()) if amt_col_inv and amt_col_inv in df_invoice_used.columns else 0.0
    invoice_stats = (oms_inv_cnt, oms_inv_amt)

    # 8. 导出
    print('\n导出...')
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_base = f'{prefix}匹配结果-销售（toB OMS）明细'
    if sales_org_col:
        out1 = OUTPUT_DIR / f'{out_base}（剔除三家）.xlsx'
        out2 = OUTPUT_DIR / f'{out_base}-其他未匹配（剔除三家）.xlsx'
        df_export = df_sales_org_other
    else:
        out1 = OUTPUT_DIR / f'{out_base}.xlsx'
        out2 = OUTPUT_DIR / f'{out_base}-其他未匹配.xlsx'
        df_export = df_matched

    export_with_classification(
        df_export, str(out1), "主明细",
        order_inv_diff_col='订单-发票金额',
        extra_categories=extra_categories,
        invoice_stats=invoice_stats,
        invoice_stats_label='OMS发票清单',
    )

    df_not_tested = df_export[df_export['大类'] == '5.有缺失'].copy()
    df_not_tested = _filter_2025(df_not_tested, date_cols_oms)
    export_with_classification(
        df_not_tested, str(out2), "未匹配",
        order_inv_diff_col='订单-发票金额',
        extra_categories=extra_categories,
        invoice_stats=invoice_stats,
        invoice_stats_label='OMS发票清单',
    )

    if sales_org_col and len(df_sales_org_123) > 0:
        out3 = OUTPUT_DIR / f'{out_base}（1240、1250、1260）.xlsx'
        out4 = OUTPUT_DIR / f'{out_base}-其他未匹配（1240、1250、1260）.xlsx'
        export_with_classification(
            df_sales_org_123, str(out3), "三家公司-主明细",
            order_inv_diff_col='订单-发票金额',
            extra_categories=extra_categories,
            invoice_stats=invoice_stats,
            invoice_stats_label='OMS发票清单',
        )
        df_not_tested_123 = _filter_2025(
            df_sales_org_123[df_sales_org_123['大类'] == '5.有缺失'].copy(),
            date_cols_oms,
        )
        export_with_classification(
            df_not_tested_123, str(out4), "三家公司-未匹配",
            order_inv_diff_col='订单-发票金额',
            extra_categories=extra_categories,
            invoice_stats=invoice_stats,
            invoice_stats_label='OMS发票清单',
        )

    print(f'\nOMS 三单匹配完成（{prefix}）')


if __name__ == '__main__':
    main()
