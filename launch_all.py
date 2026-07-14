#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import sys
import os

CODE_DIR = Path(__file__).resolve().parent
os.chdir(CODE_DIR)

print('启动全量匹配...')

# 统一脚本，由 config.TIME_RANGE 控制 1-9月 / 全年
try:
    print('\n[1/2] 运行 OMS 三单匹配...')
    exec(open(CODE_DIR / 'match_oms.py', encoding='utf-8').read())
except FileNotFoundError:
    print('未找到 OMS 脚本: match_oms.py')
    sys.exit(1)

try:
    print('\n[2/2] 运行 DMS 三单匹配...')
    exec(open(CODE_DIR / 'match_dms.py', encoding='utf-8').read())
except FileNotFoundError:
    print('未找到 DMS 脚本: match_dms.py')
    sys.exit(1)

print('\n全部完成。')
