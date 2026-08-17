# 销售三单匹配（Miaoke · 2025 toB） 🧾

> 对 Miaoke 2025 年全年 toB 销售订单、发运单与 SAP 发票执行三单匹配，按 OMS / DMS 渠道输出差异分类与审计底稿的工具。

[![Language](https://img.shields.io/badge/language-Python-blue)](https://github.com/Gvmeakiss/miaoke-sales-to-b-2025) [![License](https://img.shields.io/badge/license-MIT-green)](https://github.com/Gvmeakiss/miaoke-sales-to-b-2025/blob/main/LICENSE) [![Domain](https://img.shields.io/badge/domain-Audit%20Analytics-orange)](https://github.com/Gvmeakiss/miaoke-sales-to-b-2025)

## 📌 项目简介

本仓库处理 Miaoke 2025 年全年 toB 销售三单匹配，是 2026H1 版本（AQPP 24 组）之前的 FY25 口径实现。它读取客户订单 SQL、发运单 SQL 与 SAP 发票，按 OMS / DMS 两条渠道分别匹配，输出「完全匹配 / 数量一致金额有差异 / 金额一致数量有差异 / 均有差异 / 有缺失 / Not test」分类汇总与明细，供收入审计勾稽差异。OMS 与 DMS 共用同一套标准化 PKL，仅在内存中按渠道字段筛选区分。

## ✨ 功能特性

- **双渠道匹配**：OMS 与 DMS 共用 PKL，通过 `platform_order_no` / `DMS销售单号` 是否非空在内存中互斥切分。
- **FY25 分类体系**：`scenario_utils.assign_scenario_oms` / `assign_scenario_dms` 按容差 `AMT_TOL = 0.02`、`QTY_TOL = 0.02` 判 `订单-发票金额` 与 `订单-发货/开票数量` 关系，归为 `1.完全匹配`、`2.数量一致金额有差异`、`3.金额一致数量有差异`、`4.均有差异`、`5.有缺失`；关键字段缺失者标记 `2.Not test`。
- **状态与范围剔除**：`config.ORDER_STATUS_EXCLUDE = ['OBSOLETE','CANCEL']`；`SALES_ORG_123 = ['1240','1250','1260']` 三家销售组织单独分组/剔除。
- **发票类型治理**：`config.INVOICE_TYPES = ['ZA01','ZB02','ZQ01','ZQ07']`（标准、退货、取消等）参与匹配。
- **SQL 解析与编码检测**：`preprocess_oms_full_year.py` 的 `detect_file_encoding`（chardet）、`parse_order_sql_11/12/13_cols`、`parse_delivery_sql_file`、`build_oms_order_pkl_full_year` / `build_oms_delivery_pkl_full_year` 支持多种列结构的订单/发运 SQL；`sap_invoice_processor.py` 的 `read_sap_data` / `analyze_invoice_types` / `split_by_invoice_type` 处理 SAP 发票；`sql_to_accounting_excel.py` 将 SQL 转会计 Excel。
- **发运单导出**：`export_delivery_to_excel.py` 读取发货 PKL 导出 Excel，超过 `1,048,575` 行自动分多个 sheet。
- **固定汇总顺序**：`export_utils.FIXED_SUMMARY_ROW_ORDER`、`generate_summary_report`、`export_with_classification` 控制汇总行与分类明细导出。
- **校验与适配文档**：`test/` 含 PKL 合规检查、匹配字段验证、按渠道/期间匹配脚本，以及 `三单匹配逻辑与筛选条件核对.md`、`匹配键核对-依客户确认字段.md`、`新数据源适配审阅报告.md`、`订单OMS与DMS区分说明.md` 等审阅记录。

## 📂 目录结构

```
miaoke-sales-to-b-2025/
├── README.md
├── config.py                     # 路径、OUTPUT_PREFIX、ORDER_STATUS_EXCLUDE、SALES_ORG_123、INVOICE_TYPES
├── launch_all.py                 # 依次执行 match_oms.py、match_dms.py
├── preprocess_oms_full_year.py   # SQL 解析 → 三份标准化 PKL（订单/发货/发票）
├── match_oms.py                  # OMS 三单匹配、分类与导出
├── match_dms.py                  # DMS 三单匹配、分类与导出
├── scenario_utils.py             # 分类逻辑（AMT_TOL/QTY_TOL、assign_scenario_oms/dms、get_export_categories）
├── export_utils.py               # 汇总表、分类明细导出
├── export_schema.py              # 导出字段定义
├── export_delivery_to_excel.py   # 发运单 PKL → Excel（超行分卷）
├── sap_invoice_processor.py      # SAP 发票读取/类型分析/拆分
├── sql_to_accounting_excel.py    # SQL 转会计 Excel
├── requirements.txt              # pandas>=2.0 / numpy>=1.24 / openpyxl>=3.1 / chardet>=5.0
├── test/                         # 校验脚本与适配审阅文档
│   ├── check_pkl_compliance.py
│   ├── check_fullyear_pkl.py
│   ├── verify_match_fields.py
│   ├── verify_order_invoice_type.py
│   ├── match_oms_full_year.py / match_oms_1_9_months.py
│   ├── match_dms_full_year_from_sql.py / match_dms_1_9_months_from_sql.py / match_dms_from_sql.py
│   ├── analyze_nottest.py
│   ├── preprocess_full_year.py   # 已弃用
│   └── *.md（匹配逻辑、匹配键、新数据源适配、OMS/DMS 区分等审阅说明）
└── LICENSE
```

## 🔧 环境要求

- Python 3.8+（README 标注；代码使用 f-string、`pathlib`、类型注解）
- 依赖见 `requirements.txt`：`pandas>=2.0`、`numpy>=1.24`、`openpyxl>=3.1`、`chardet>=5.0`

## 🚀 安装

```bash
git clone https://github.com/Gvmeakiss/miaoke-sales-to-b-2025.git
cd miaoke-sales-to-b-2025
pip install -r requirements.txt
```

## 💡 快速开始 / 使用示例

预处理生成三份标准化 PKL 后，分别运行 OMS / DMS 匹配：

```bash
# 首次运行：解析 SQL、生成 PKL
python3 preprocess_oms_full_year.py

# 三单匹配（OMS、DMS）
python3 match_oms.py
python3 match_dms.py

# 或一键执行两者
python3 launch_all.py

# 发运单导出 Excel
python3 export_delivery_to_excel.py

# PKL 合规检查
python3 test/check_pkl_compliance.py
```

匹配结果 Excel 含「汇总表」（首 sheet）、「全部数据」与各分类明细 sheet；PKL 默认复用，`match_oms.py` 会写入 `oms_order.pkl` 等缓存，存在则优先读取。

## 🧠 核心逻辑（方法论）

1. **预处理标准化**：`preprocess_oms_full_year.py` 以 `detect_file_encoding` 检测 SQL 编码，按 11/12/13 列结构解析订单、解析发运单，构建 `2025年全年OMS订单.pkl` / `2025年全年OMS发货.pkl`；发票由 `sap_invoice_processor.py` / `sql_to_accounting_excel.py` 处理为 `2025年全年SAP原始数据.pkl`。
2. **渠道筛选**：`match_oms.py`（`load_oms_order_delivery_invoice`）与 `match_dms.py` 加载同一套 PKL；OMS 取 `platform_order_no` 与 `DMS销售单号` 均为空的行，DMS 取其非空行；并剔除 `OBSOLETE` / `CANCEL` 订单。
3. **匹配键**：OMS 用 `main_order_no + 物料`、发运 `main_order_no + 料号`、发票 `OMS销售单号 + 物料编码`；DMS 用 `platform_order_no + 物料` / `external_order_no + 料号` / `DMS销售单号 + 物料编码`。
4. **聚合与差异**：按匹配键聚合金额与数量，以发票为基准左连接订单与发运，计算 `订单-发票金额`、`订单-发货数量`、`订单-开票数量` 等差异。
5. **分类**：`scenario_utils.assign_scenario_oms/dms` 用 `AMT_TOL=0.02`、`QTY_TOL=0.02`（`abs(差) < 容差` 视为一致）判关系，归为 `1.完全匹配` – `4.均有差异`、`5.有缺失`，并就关键字段缺失打 `2.Not test`。分类仅做差异归集，不自动下错报结论。
6. **导出**：`export_utils.export_with_classification` + `generate_summary_report` 按 `FIXED_SUMMARY_ROW_ORDER` 输出汇总与各分类明细；金额口径上 OMS 用 `实际金额（ZFN1）`、DMS 用 `含税金额`。

## 📋 输入与输出

- **输入**：客户订单 SQL、发运单 SQL（经 `preprocess_oms_full_year.py` 解析）与 SAP 发票数据；发票类型限 `ZA01/ZB02/Zut...` 即 `INVOICE_TYPES` 配置范围。
- **中间数据**：`pkl/` 下三份标准化 PKL（`2025年全年OMS订单.pkl`、`2025年全年OMS发货.pkl`、`2025年全年SAP原始数据.pkl`），OMS 另写 `oms_order.pkl` 等缓存。
- **输出**（`output/`）：OMS / DMS 匹配结果 Excel（汇总表 + 全部数据 + 各分类明细，文件名前缀 `2025年全年`），以及 `2025年全年发运单.xlsx`（超 `1,048,575` 行自动分卷）。

## ⚙️ 配置说明

集中在 `config.py`：

- `OUTPUT_PREFIX = '2025年全年'`、`OUTPUT_DIR` / `PKL_DIR`；
- `ORDER_PKL` / `DELIVERY_PKL` / `INVOICE_PKL` 三份源 PKL 路径；
- `ORDER_STATUS_EXCLUDE = ['OBSOLETE','CANCEL']`；
- `SALES_ORG_123 = ['1240','1250','1260']`；
- `INVOICE_TYPES = ['ZA01','ZB02','ZQ01','ZQ07']`；
- 容差定义在 `scenario_utils.py`：`AMT_TOL = 0.02`、`QTY_TOL = 0.02`。

注：分类阈值集中在 `scenario_utils` 的 `AMT_TOL` / `QTY_TOL`，主流程以 `abs(差) < 容差` 判断一致，未散落硬编码浮点相等比较。

## ⚠️ 注意事项

- 数据脱敏：仓库不含真实客户业务数据，示例与说明均为脱敏/合成数据；实际运行需将客户导出文件放入对应输入目录。
- 口径说明：渠道切分、状态剔除、发票类型与容差以 `config.py` / `scenario_utils.py` 与代码为准，本 README 仅作说明。
- 版本差异：本仓库为 FY25 口径（分类式），与 2026H1 版本的 AQPP 24 子组口径不同，跨年对比时需注意分类体系切换。
- 审计结论：程序仅归类差异，错报应对由项目组人工选择。

## 🔗 相关仓库

- https://github.com/Gvmeakiss/sales-three-match-miaoke-2026
- https://github.com/Gvmeakiss/miaoke-sales-to-b-2026
- https://github.com/Gvmeakiss/miaoke-sales-to-c
- https://github.com/Gvmeakiss/sales-three-match-newhope-2026

## 📄 License

MIT（详见仓库 `LICENSE`）。

---

<div align="center">

*Disclaimer: Personal project and personal views. Not affiliated with or endorsed by KPMG or any client.*<br>
*本仓库为个人项目与个人观点，与任何前/现雇主及客户无关。*

</div>
