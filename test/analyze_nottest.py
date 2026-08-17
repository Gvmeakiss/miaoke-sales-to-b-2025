# -*- coding: utf-8 -*-
"""分析 2. 未测试(有缺失) 的构成：缺订单、缺发货的分布"""
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parent
p = BASE / "2025年全年匹配结果-销售（toB OMS）明细.csv"
df = pd.read_csv(p)

d = df[df['2.Not test']].copy()
d['缺订单'] = d['订单金额'].isna() | d['订单数量'].isna()
d['缺发货'] = d['发货数量'].isna()
a = d['缺订单'] & ~d['缺发货']   # 仅缺订单
b = ~d['缺订单'] & d['缺发货']   # 仅缺发货
c = d['缺订单'] & d['缺发货']    # 都缺

print("=== 2. 未测试(有缺失) %s 行的缺失构成 ===" % len(d))
print("仅缺订单(有发货、无订单):", a.sum())
print("仅缺发货(有订单、无发货):", b.sum())
print("订单与发货都缺:          ", c.sum())
print("校验(合计=742352):       ", a.sum() + b.sum() + c.sum())
print()
print("占比(在未测试中):")
print("  仅缺订单: %.1f%%" % (100 * a.sum() / len(d)))
print("  仅缺发货: %.1f%%" % (100 * b.sum() / len(d)))
print("  都缺:     %.1f%%" % (100 * c.sum() / len(d)))
