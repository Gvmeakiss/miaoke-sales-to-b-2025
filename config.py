# -*- coding: utf-8 -*-
"""
三单匹配配置 - 时间范围、路径、筛选条件

修改 TIME_RANGE 切换 1-9 月 / 全年，或直接修改下方路径覆盖默认值。
"""

from pathlib import Path

# 项目根目录（code 的上一级）
BASE = Path(__file__).resolve().parent.parent

# =============================================================================
# 输出与缓存目录（规范项目结构）
# =============================================================================
OUTPUT_DIR = BASE / 'output'   # 匹配结果 xlsx、违和订单等导出文件
PKL_DIR = BASE / 'pkl'         # 源 pkl、缓存 pkl（oms_order.pkl 等）

# =============================================================================
# 2025 全年：OMS 与 DMS 共用同一套 pkl
# =============================================================================
OUTPUT_PREFIX = '2025年全年'
ORDER_PKL = PKL_DIR / '2025年全年OMS订单.pkl'
DELIVERY_PKL = PKL_DIR / '2025年全年OMS发货.pkl'
INVOICE_PKL = PKL_DIR / '2025年全年SAP原始数据.pkl'


def get_oms_config():
    """OMS 配置"""
    return {
        'order_pkl': ORDER_PKL,
        'delivery_pkl': DELIVERY_PKL,
        'invoice_pkl': INVOICE_PKL,
        'use_pkl_cache': True,
        'pkl_cache_dir': PKL_DIR,
    }


def get_dms_config():
    """DMS 配置（与 OMS 共用 pkl）"""
    return {
        'order_pkl': ORDER_PKL,
        'delivery_pkl': DELIVERY_PKL,
        'invoice_pkl': INVOICE_PKL,
    }


def get_output_prefix():
    """输出文件名前缀"""
    return OUTPUT_PREFIX


# =============================================================================
# 发票数据源规范（OMS、DMS 共用同一 pkl，按 DMS销售单号 区分）
# =============================================================================
# DMS销售单号 非空 → DMS 发票，仅用于 DMS 三单匹配
# DMS销售单号 为空  → OMS 发票，仅用于 OMS 三单匹配

# =============================================================================
# 订单数据源规范（依业务流程：通过 DMS 下单生成 DMS 订单号，直接 OMS 下单无 DMS 订单号）
# =============================================================================
# 订单表 platform_order_no = DMS 订单号（匹配键核对-依客户确认字段.md）
# platform_order_no 非空 → DMS 订单（通过 DMS 下单，DMS 传 OMS 发货后生成 OMS 子订单）
# platform_order_no 为空  → OMS 订单（直接 OMS 下单，仅 OMS 子订单号、主订单号）

# =============================================================================
# 筛选条件（OMS、DMS 共用）
# =============================================================================
ORDER_STATUS_EXCLUDE = ['OBSOLETE', 'CANCEL']
SALES_ORG_123 = ['1240', '1250', '1260', 1240, 1250, 1260]
INVOICE_TYPES = ['ZA01', 'ZB02', 'ZQ01', 'ZQ07']
