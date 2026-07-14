# 销售三单匹配系统（妙可 toB）

> 销售订单、发货、SAP 开票三单匹配系统，支持 OMS 与 DMS 数据匹配，用于对账和差异分析。

**运行环境**：macOS。Windows 兼容性未保证。

---

## 快速开始

```bash
cd code
pip install pandas openpyxl chardet

# 首次运行：预处理
python preprocess_oms_full_year.py

# 三单匹配
python match_oms.py          # OMS
python match_dms.py          # DMS

# 发运单导出 Excel
python export_delivery_to_excel.py

# 批量运行
python launch_all.py
```

---

## 项目简介

- **三单数据匹配**：订单、发货、发票
- **差异计算与分类**：完全匹配、金额/数量不一致、数据缺失等
- **按销售组织分组**：1240/1250/1260 vs 剔除三家
- **支持**：2025 年全年 OMS / DMS 匹配、发运单导出

---

## 目录结构

```
code/
├── config.py                    # 配置（路径、pkl、筛选条件）
├── preprocess_oms_full_year.py  # 数据预处理
├── match_oms.py                 # OMS 三单匹配
├── match_dms.py                 # DMS 三单匹配
├── export_delivery_to_excel.py  # 发运单导出 Excel
├── export_utils.py              # 导出与汇总表工具
├── export_schema.py             # 导出字段定义
├── scenario_utils.py            # 场景分类工具
├── launch_all.py                # 批量运行 OMS + DMS
├── sap_invoice_processor.py    # SAP 发票处理
├── sql_to_accounting_excel.py   # SQL 转会计 Excel
└── test/                        # 测试与辅助脚本
    ├── check_pkl_compliance.py  # pkl 合规检查
    ├── check_fullyear_pkl.py    # 全年 pkl 存在性检查
    ├── verify_match_fields.py   # 匹配字段验证
    ├── verify_order_invoice_type.py
    ├── match_oms_full_year.py
    ├── match_oms_1_9_months.py
    ├── match_dms_full_year_from_sql.py
    ├── match_dms_1_9_months_from_sql.py
    ├── match_dms_from_sql.py
    ├── analyze_nottest.py
    └── preprocess_full_year.py  # 冗余，已弃用

项目根目录/
├── input/dingdan/               # 订单 SQL
├── input/fapiao/                # 发票 Excel（可选）
├── input/fayundan/              # 发运单 SQL
├── output/                      # 输出（匹配结果、发运单 xlsx）
├── pkl/                         # 缓存 pkl
├── refer/                       # 参考文档
└── scripts/filter_fapiao_2025.py  # 发票预处理
```

---

## 一、数据源与调用指南

### 1.1 数据源路径（项目根目录下）

| 类型 | 路径 | 文件 |
|------|------|------|
| **订单** | `input/dingdan/` | `24年12月到25年6月订单数据.sql`<br>`25年7月到25年12月订单数据.sql` |
| **发运单** | `input/fayundan/` | `24年12月到25年6月发货数据.sql`<br>`25年7月到26年1月发货数据.sql` |
| **发票** | `output/fapiao_2025_filtered.pkl` | 需先由 `scripts/filter_fapiao_2025.py` 生成 |

### 1.2 预处理产出（`pkl/` 目录）

| 文件 | 用途 | 生成脚本 |
|------|------|----------|
| `pkl/2025年全年OMS订单.pkl` | OMS/DMS 共用订单源 | preprocess_oms_full_year.py |
| `pkl/2025年全年OMS发货.pkl` | OMS/DMS 共用发货源 | preprocess_oms_full_year.py |
| `pkl/2025年全年SAP原始数据.pkl` | OMS/DMS 共用发票源 | preprocess_oms_full_year.py（复制 fapiao_2025_filtered.pkl） |

**说明**：OMS 与 DMS 共用同一套 pkl，通过内存筛选区分：
- **OMS**：`platform_order_no` 为空、`DMS销售单号` 为空
- **DMS**：`platform_order_no` 非空、`DMS销售单号` 非空

### 1.3 订单 OMS 与 DMS 区分

| 判据 | OMS | DMS |
|------|-----|-----|
| **主判据** | `channel_name` 不含 'DMS' | `channel_name` 含 'DMS' |
| **platform_order_no** | 多为 NULL | 多为非空 |
| **匹配键** | main_order_no + 物料（与发票主订单号对齐） | platform_order_no + 物料 |

### 1.4 匹配键定义（客户确认）

| 数据源 | OMS 匹配键 | DMS 匹配键 |
|--------|------------|------------|
| 订单 | main_order_no + item_code | platform_order_no + item_code |
| 发运单 | main_order_no + 料号 | external_order_no + 料号 |
| 发票 | OMS销售单号 + 物料编码 | DMS销售单号 + 物料编码 |

发票侧 OMS 销售单号 = OMS 主订单号；未拆单时子订单号=主订单号，拆单时需按主订单号聚合再匹配。

### 1.5 发票类型与金额/数量列

- **发票类型**：ZA01、ZB02、ZQ01、ZQ07（标准、退货、取消等，fapiao_2025_filtered.pkl 已筛选）
- **OMS 金额**：实际金额（ZFN1）
- **DMS 金额**：含税金额
- **数量**：开票数量（基本单位）

---

## 二、代码运行逻辑

### 2.1 OMS 三单匹配流程（match_oms.py）

```
1. 加载 pkl（订单、发货、发票）
2. 筛选：订单 platform_order_no 为空、发票 DMS销售单号 为空
3. 订单筛选：order_status ≠ OBSOLETE/CANCEL
4. 创建匹配键 order-item（main_order_no + 物料）
5. 按 order-item 聚合金额、数量
6. 以发票为基准左连接订单、发货
7. 计算差异（订单-开票数量、发货-开票数量、订单-发票金额）
8. 分类：2.Not test / 1.1完全匹配 / 1.2金额不一致 / 1.3数量不一致 / 1.4均不一致
9. 按销售组织分组（1240/1250/1260 vs 剔除三家）
10. 导出 Excel（汇总表 + 全部数据 + 各分类明细）
```

### 2.2 DMS 三单匹配流程（match_dms.py）

```
1. 加载 pkl（同 OMS）
2. 筛选：订单 platform_order_no 非空、发票 DMS销售单号 非空
3. 订单筛选：channel_name 含 'DMS'，order_status ≠ OBSOLETE/CANCEL
4. 发货筛选：external_order_no 非空
5. 创建匹配键（platform_order_no / external_order_no + 物料）
6. 聚合、匹配、差异计算、分类（与 OMS 一致）
7. 按销售组织分组、导出 Excel
```

### 2.3 发运单导出（export_delivery_to_excel.py）

- 从 `pkl/2025年全年OMS发货.pkl` 读取
- 导出至 `output/2025年全年发运单.xlsx`
- 超过 Excel 单 sheet 最大行数（1,048,575）时自动分多个 sheet

---

## 三、配置与输出

### 3.1 配置（config.py）

| 配置项 | 说明 |
|--------|------|
| `OUTPUT_DIR` | 输出目录，默认 `BASE/output` |
| `PKL_DIR` | 缓存目录，默认 `BASE/pkl` |
| `ORDER_PKL` / `DELIVERY_PKL` / `INVOICE_PKL` | 源 pkl 路径 |
| `ORDER_STATUS_EXCLUDE` | 排除的订单状态：OBSOLETE、CANCEL |
| `SALES_ORG_123` | 三家销售组织：1240、1250、1260 |

### 3.2 输出文件

| 类型 | 文件示例 |
|------|----------|
| OMS 匹配 | `output/2025年全年匹配结果-销售（toB OMS）明细（剔除三家）.xlsx` |
| DMS 匹配 | `output/2025年全年匹配结果-销售（toB DMS）明细（剔除三家）.xlsx` |
| 发运单 | `output/2025年全年发运单.xlsx` |

每个匹配结果 Excel 含：**汇总表**（第一个 sheet）、**全部数据**、**各分类明细** sheet。

---

## 四、分类说明

| 分类 | 条件 |
|------|------|
| 2.Not test | 关键字段（订单/发货/开票金额、数量）有缺失 |
| 1.1 完全匹配 | 数量差≈0、金额差<1 |
| 1.2 金额不一致 | 数量差≈0、金额差≥1 |
| 1.3 数量不一致 | 数量差≠0、金额差<1 |
| 1.4 均不一致 | 数量差≠0、金额差≥1 |

金额差 < 1 视为一致（考虑四舍五入）；数量差 < 0.01 视为一致。

---

## 五、常用操作

- **强制重新读取**：删除对应 pkl 后重新运行
- **Excel 超限**：自动分多个 sheet（如 发运单_P1、发运单_P2）
- **修改阈值**：在 match_oms.py / match_dms.py 中修改 `AMOUNT_THRESHOLD`、`QUANTITY_THRESHOLD`
- **pkl 合规检查**：`python test/check_pkl_compliance.py`

---

## 六、调试与问题解决

### 6.1 新数据源适配

| 类型 | 旧数据源 | 新数据源 |
|------|----------|----------|
| **订单** | `OMS25年1-12月订单及发货数据`，11/13 列 | `input/dingdan`，12 列（含 line_amount） |
| **发运单** | 同订单目录，7/8 列 | `input/fayundan`，9 列（含 document_no、main_order_no） |
| **发票** | Excel 2025-01～12.XLSX | `output/fapiao_2025_filtered.pkl` |

**解决**：preprocess_oms_full_year.py 已支持新路径；订单补 `channel_name2=np.nan`；发运单映射 `main_order_no` 为主单号。

### 6.2 2.Not test 误判

**原因**：检查了所有列的缺失，额外列有空值即被判为 Not test。

**解决**：只检查关键字段 `订单金额`、`订单数量`、`发货数量`、`开票金额`、`开票数量`。

### 6.3 OMS 匹配键与发票不一致

**解决**：统一 OMS 三单使用 **main_order_no + 物料** 作为匹配键，与发票侧主订单号对齐。

### 6.4 汇总表与输出规范

- 固定汇总行顺序（export_utils.FIXED_SUMMARY_ROW_ORDER）
- 小记 = 四大类合计；总计 = 小记 + 仅发票
- 5.有缺失 按 2025 年过滤

### 6.5 DMS 总计与发票清单金额差异

**说明**：总计基于「剔除三家」后的匹配结果，发票清单基于全部 DMS 发票。差异来自 1240、1250、1260 三家公司的发票金额，属预期口径差异。

### 6.6 OMS 与 DMS 金额口径

| 系统 | 金额字段 |
|------|----------|
| OMS | 实际金额（ZFN1） |
| DMS | 含税金额 |

### 6.7 PKL 缓存机制

- match_oms 会写入 `pkl/oms_order.pkl`、`oms_delivery.pkl`、`oms_invoice.pkl`，存在则优先读缓存
- match_dms 直接读源 pkl

### 6.8 其他

| 问题 | 解决方案 |
|------|----------|
| Excel 超限 | 超过 1,048,575 行自动分多个 sheet |
| 内存占用高 | 使用 PKL 缓存；大数据量约 13–22GB 属正常 |
| 编码问题 | 使用 chardet 检测 SQL 文件编码 |

---

## 技术栈

Python 3.8+ · pandas · openpyxl · chardet

---

## 可复用工具包

项目根目录下的 `triple_match_tool/` 为独立可复用包，仅包含三单匹配核心逻辑（不含 test）。可复制到其它项目使用，详见 [triple_match_tool/README.md](../triple_match_tool/README.md)。
