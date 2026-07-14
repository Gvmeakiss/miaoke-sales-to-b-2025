# -*- coding: utf-8 -*-
"""
导出字段规范 - 参考 refer/three_lists.py

统一命名：订单日期、订单类型、发票类型、匹配订单号、发货单号 等，使导出清单规范化。
"""

import pandas as pd

# 规范字段优先顺序（核心标识与业务关键字段优先）
EXPORT_COLUMN_ORDER = [
    # 分类与匹配键
    '大类', '细分场景', '2.Not test',
    'order-item', 'DMS订单', '物料编码',
    # 订单核心
    '匹配订单号', '订单日期', '订单类型', '订单-主订单号', '订单-销售订单号', '订单-平台订单号',
    '订单-渠道名称', '订单-商品代码', '订单-创建时间', '订单-更新时间', '订单-订单状态',
    '订单金额', '订单数量',
    # 发货核心
    '发货单号', '发货-订单号', '发货-主单号', '发货-外部订单号', '发货-业务时间', '发货-料号', '发货-商品名称', '发货-业务类型',
    '发货数量', 'DMS发货数量',
    # 发票核心
    '发票类型', '发票-发票类型', '发票-SAP发票号', '发票-销售组织', '发票-开票日期',
    '开票金额', 'SAP开票含税金额', '开票数量', 'SAP开票销售数量', 'SAP开票基本数量',
    # 差异
    '订单-发票金额', 'SAP-DMS订单金额', '订单-发货数量', '订单-开票数量', '发货-开票数量',
    'SAP-DMS订单数量(基本单位)', 'SAP-DMS发货数量(基本单位)', 'SAP-DMS发货数量',
]

# 旧列名 → 规范列名（清晰业务含义，重命名后删除旧列）
EXPORT_RENAME = {
    '订单-创建时间': '订单日期',
    '订单-订单类型': '订单类型',
}


def _resolve_match_order_column(df):
    """获取匹配订单号列：OMS 用 订单-主订单号，DMS 用 DMS订单"""
    if '订单-主订单号' in df.columns:
        return '订单-主订单号'
    if 'DMS订单' in df.columns:
        return 'DMS订单'
    return None


def apply_export_schema(df):
    """
    对匹配结果 DataFrame 应用导出规范：
    1. 添加/规范 匹配订单号、订单日期、订单类型、发票类型、发货单号
    2. 重命名部分列
    3. 按优先顺序调整列顺序（不删除列）
    """
    if df.empty:
        return df
    out = df.copy()

    # 1. 匹配订单号（用于对账追踪）
    match_col = _resolve_match_order_column(out)
    if match_col and '匹配订单号' not in out.columns:
        out['匹配订单号'] = out[match_col]

    # 2. 订单日期、订单类型（统一命名，替换旧列）
    if '订单-创建时间' in out.columns:
        out['订单日期'] = out['订单-创建时间']
        out = out.drop(columns=['订单-创建时间'], errors='ignore')
    if '订单-订单类型' in out.columns:
        out['订单类型'] = out['订单-订单类型']
        out = out.drop(columns=['订单-订单类型'], errors='ignore')

    # 3. 发票类型（统一命名，可能来自 发票-发票类型 或 发票类型.1）
    inv_type_col = next((c for c in out.columns if '发票' in str(c) and '类型' in str(c)), None)
    if inv_type_col and '发票类型' not in out.columns:
        out['发票类型'] = out[inv_type_col]
        out = out.drop(columns=[inv_type_col], errors='ignore')

    # 4. 发货单号（匹配行对应的发货单据号，优先 document_no，否则订单号/主单号）
    if '发货-发货单号' in out.columns:
        out['发货单号'] = out['发货-发货单号']
    elif '发货-订单号' in out.columns:
        out['发货单号'] = out['发货-订单号']
    elif '发货-主单号' in out.columns:
        out['发货单号'] = out['发货-主单号']

    # 7. 列顺序：优先展示的列靠前，其余保持
    order_set = [c for c in EXPORT_COLUMN_ORDER if c in out.columns]
    rest = [c for c in out.columns if c not in order_set]
    out = out[order_set + rest]
    return out
