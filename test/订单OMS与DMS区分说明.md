# 订单 OMS 与 DMS 区分说明

> 基于业务流程与订单字段，说明如何判断 OMS 订单与 DMS 订单。

---

## 〇、业务流程（依据客户确认）

- **通过 DMS 下单**：生成 DMS 订单号 → DMS 传输到 OMS 执行发货 → 生成 OMS 子订单号
- **直接通过 OMS 下单**：仅包含 OMS 子订单号、OMS 主订单号（无 DMS 订单号）

**订单数据源规范**：以 **DMS 订单号（platform_order_no）** 为判据：
- **platform_order_no 非空** → DMS 订单（来自 DMS 下单流程）
- **platform_order_no 为空** → OMS 订单（直接 OMS 下单）

---

## 一、数据字段概览

订单 SQL 含 12 列，其中与渠道/来源相关的字段：

| 字段 | 说明 | 用途 |
|------|------|------|
| **platform_order_no** | DMS 订单号 | **主判据**：非空=DMS 订单，为空=OMS 订单 |
| **channel_name** | 渠道名称 | 与 platform_order_no 高度一致，可作辅助 |
| **sale_order_no** | OMS 子订单号（格式 DD 开头） | OMS 匹配键 |
| **main_order_no** | OMS 主订单号 | OMS 匹配键 |
| **order_type** | 订单类型 | 如 liquid_milk_order、standard_order 等 |
| **order_status** | 订单状态 | 如 RECEIVED、OBSOLETE、CANCEL 等 |

---

## 二、当前数据中的渠道取值

基于 `2025年全年OMS订单.pkl` 统计（新数据源 24年12月～25年12月）：

| channel_name | 订单行数 | 占比 | platform_order_no 非空比例 |
|--------------|----------|------|---------------------------|
| **DMS** | 1,323,252 | 82.5% | 100% |
| **OMS** | 280,663 | 17.5% | 约 0.8% |
| **OMS_WL** | 1,072 | 0.07% | 未单独统计 |

共 3 种取值：`DMS`、`OMS`、`OMS_WL`。

---

## 三、当前代码的区分逻辑

### 3.1 DMS 订单（match_dms.py）

```python
df_order_dms = df_order[df_order['channel_name'].astype(str).str.contains('DMS', case=False, na=False)]
```

- **含义**：`channel_name` 中包含字符串 `"DMS"`（不区分大小写）
- **当前结果**：只保留 `channel_name == 'DMS'` 的订单（1,323,252 行）

### 3.2 OMS 订单（match_oms.py）

- **含义**：不做按 channel_name 的显式过滤
- **实际范围**：使用 preprocess 输出的「全部订单」pkl，再按以下条件筛：
  - order_status ≠ 'OBSOLETE'、'CANCEL'
  - order_type **不限制**（全量参与，用于全量匹配率）
  - create_time **不限制**（不按时间过滤）
  - **OMS_WL 视作 OMS** 一起参与三单匹配
- **结果**：包含 `channel_name == 'OMS'` 和 `'OMS_WL'` 的订单（不含 DMS 发票匹配，但订单池含全部渠道）

OMS 匹配逻辑上并未显式写「只要 OMS」，而是依赖：
1. 发票侧：只保留 DMS销售单号 为空的发票（即 OMS 发票）
2. 匹配键用 sale_order_no + item_code

因此，虽然订单本身包含 DMS，但发票只匹配 OMS 发票，DMS 发票被剔除，DMS 订单在匹配中会落在「订单有、发票无」的未匹配里。

---

## 四、辅助判断字段：platform_order_no

| 渠道 | platform_order_no 典型值 | 说明 |
|------|--------------------------|------|
| **OMS** | 多为 NULL | 无平台订单号 |
| **DMS** | 10 位数字，如 '0015547860' | 来自平台/经销商的单号 |

可作为辅助判断，但不建议单独替代 channel_name：

- 0.8% 的 OMS 订单 platform_order_no 非空
- 业务规则变化时，仅用 platform_order_no 可能不够稳

---

## 五、OMS_WL 的归属

- **OMS_WL**：1,072 行，约 0.07%
- **已确认**：**OMS_WL 视作 OMS**，一起参与 OMS 三单匹配
- **当前行为**：
  - DMS 脚本：`contains('DMS')` → 不包含 `OMS_WL`，**不会**进入 DMS 匹配
  - OMS 脚本：不做 channel 过滤，OMS_WL **会**参与 OMS 匹配（仅排除 order_status=OBSOLETE/CANCEL）

---

## 六、区分规则小结

| 维度 | OMS 订单 | DMS 订单 |
|------|----------|----------|
| **主判据** | channel_name 不含 'DMS' | channel_name 含 'DMS' |
| **典型 channel_name** | 'OMS'、'OMS_WL' | 'DMS' |
| **platform_order_no** | 多为 NULL | 多为非空（10 位数字） |
| **sale_order_no** | DD 开头，如 DD2412010491 | DD 开头，如 DD2507012419 |
| **匹配键（OMS 流程）** | sale_order_no + item_code | 不参与 OMS 发票匹配 |
| **匹配键（DMS 流程）** | 不参与 | platform_order_no + item_code |

---

## 七、待确认事项

1. **OMS_WL**：是否统一视为 OMS？是否需要单独统计或单独逻辑？
2. **platform_order_no**：能否/是否需要作为 OMS/DMS 的补充或主判据？
3. **边界情况**：若 channel_name 出现新值（如 "DMS_XX"、"OMS_YY"），当前规则是否仍适用？

---

*文档基于当前代码与 2025 年全年订单 pkl 统计分析。*
