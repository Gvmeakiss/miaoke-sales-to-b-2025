# PKL 文件验证说明

## 一、当前代码依赖的 PKL

| 文件 | 用途 | 生成方式 |
|------|------|----------|
| `pkl/2025年全年OMS订单.pkl` | OMS/DMS 共用订单源 | preprocess_oms_full_year.py |
| `pkl/2025年全年OMS发货.pkl` | OMS/DMS 共用发货源 | preprocess_oms_full_year.py |
| `pkl/2025年全年SAP原始数据.pkl` | OMS/DMS 共用发票源 | preprocess_oms_full_year.py（复制 output/fapiao_2025_filtered.pkl） |
| `output/fapiao_2025_filtered.pkl` | 发票预处理输入 | 外部脚本生成，preprocess 读取后写出到 pkl/SAP原始数据.pkl |

## 二、是否需要重新保存 PKL？

**不需要。** 本次修改仅涉及：

- **match_oms.py**：内存中的筛选（订单 platform_order_no 为空、发票 DMS销售单号 为空）
- **match_dms.py**：内存中的筛选（订单 platform_order_no 非空、发票 DMS销售单号 非空）
- **config.py**：配置与文档

源 pkl 的列结构与含义未变，preprocess 产出可直接使用，无需重新跑 preprocess。

## 三、PKL 与缓存目录

**config**：`PKL_DIR = BASE / 'pkl'`，源 pkl 与 match_oms 缓存均在此目录。

**match_oms** 会写入：

- `pkl/oms_order.pkl`
- `pkl/oms_delivery.pkl`
- `pkl/oms_invoice.pkl`

下次运行时若存在以上文件，则直接从缓存读取，不再读源 pkl。

**match_dms**：已取消 DMS 专用缓存，直接读上述三个源 pkl。

## 四、可删除的 PKL（不再使用）

| 文件 | 说明 |
|------|------|
| `pkl/oms_order_full_year.pkl` | 旧命名，当前使用 oms_order.pkl |
| `pkl/oms_delivery_full_year.pkl` | 同上 |
| `pkl/oms_invoice_full_year.pkl` | 同上 |

说明：如曾存在 `dms_order_full_year.pkl` 等，也已在 DMS 改为共用源 pkl 后废弃，可一并删除。

**迁移提示**：若此前 pkl 文件在项目根目录，请将 `2025年全年OMS订单.pkl` 等三个文件移至 `pkl/` 目录，或重新运行 `preprocess_oms_full_year.py`。

## 五、建议操作

1. **删除 PKL 中已废弃文件**（见上方列表）。
2. **可选**：清空 `PKL/*.pkl`，强制下次 match 从源 pkl 读取，避免历史缓存干扰。
3. **无需重新执行 preprocess**，源 pkl 保持不变即可。
