#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SAP开票数据处理器
读取前九个月数据，按发票类型分类保存
"""

import pandas as pd
import os
import pickle
from pathlib import Path
import glob

def read_sap_data():
    """读取SAP开票数据前九个月"""
    print("开始读取SAP开票数据...")
    
    # 数据文件夹路径
    data_dir = Path("SAP开票数据")
    
    # 获取所有Excel文件
    excel_files = list(data_dir.glob("2025-*.XLSX"))
    excel_files.sort()  # 按文件名排序
    
    print(f"找到 {len(excel_files)} 个Excel文件")
    
    all_data = []
    
    for file_path in excel_files:
        print(f"正在读取: {file_path.name}")
        try:
            # 读取Excel文件
            df = pd.read_excel(file_path, engine='openpyxl')
            print(f"  - 行数: {len(df)}")
            print(f"  - 列数: {len(df.columns)}")
            
            # 添加数据源标识
            df['数据源文件'] = file_path.name
            
            all_data.append(df)
            
        except Exception as e:
            print(f"  - 读取失败: {e}")
            continue
    
    if not all_data:
        print("没有成功读取任何数据")
        return None
    
    # 合并所有数据
    print("\n合并所有数据...")
    combined_df = pd.concat(all_data, ignore_index=True)
    print(f"合并后总行数: {len(combined_df)}")
    print(f"合并后总列数: {len(combined_df.columns)}")
    
    return combined_df

def analyze_invoice_types(df):
    """分析发票类型分布"""
    print("\n分析发票类型分布...")
    
    # O列是发票类型（第15列，索引14）
    invoice_type_col = df.columns[14]  # O列
    print(f"发票类型列名: {invoice_type_col}")
    
    # 统计发票类型
    type_counts = df[invoice_type_col].value_counts()
    print(f"\n发票类型分布:")
    for invoice_type, count in type_counts.items():
        print(f"  {invoice_type}: {count:,} 条")
    
    return invoice_type_col, type_counts

def save_as_pkl(df, filename="sap_invoice_data.pkl"):
    """保存数据为pkl文件"""
    print(f"\n保存数据为pkl文件: {filename}")
    
    with open(filename, 'wb') as f:
        pickle.dump(df, f)
    
    file_size = os.path.getsize(filename) / (1024 * 1024)  # MB
    print(f"pkl文件大小: {file_size:.2f} MB")

def split_by_invoice_type(df, invoice_type_col):
    """按发票类型分别保存为Excel文件"""
    print(f"\n按发票类型分别保存为Excel文件...")
    
    # 创建输出目录
    output_dir = Path("SAP发票分类输出")
    output_dir.mkdir(exist_ok=True)
    
    # 获取所有发票类型
    invoice_types = df[invoice_type_col].unique()
    print(f"发现 {len(invoice_types)} 种发票类型")
    
    for invoice_type in invoice_types:
        if pd.isna(invoice_type):
            continue
            
        # 过滤数据
        type_data = df[df[invoice_type_col] == invoice_type].copy()
        
        # 清理文件名中的特殊字符（Mac 文件名非法字符：/ 和 :）
        safe_filename = str(invoice_type).replace('/', '_').replace(':', '_')
        
        # 保存为Excel
        output_file = output_dir / f"发票类型_{safe_filename}.xlsx"
        
        print(f"保存 {invoice_type}: {len(type_data)} 条记录 -> {output_file.name}")
        
        try:
            type_data.to_excel(output_file, index=False, engine='openpyxl')
        except Exception as e:
            print(f"  - 保存失败: {e}")
            continue
    
    print(f"\n所有发票类型数据已保存到: {output_dir}")

def load_from_pkl(filename="sap_invoice_data.pkl"):
    """从pkl文件加载数据"""
    print(f"从pkl文件加载数据: {filename}")
    
    if not os.path.exists(filename):
        print(f"pkl文件不存在: {filename}")
        return None
    
    try:
        with open(filename, 'rb') as f:
            df = pickle.load(f)
        
        print(f"成功加载数据: {len(df):,} 行, {len(df.columns)} 列")
        return df
    except Exception as e:
        print(f"加载pkl文件失败: {e}")
        return None

def main():
    """主函数"""
    print("SAP开票数据处理器启动...")
    
    # 尝试从pkl文件加载数据
    df = load_from_pkl()
    
    # 如果pkl文件不存在，则重新读取Excel文件
    if df is None:
        print("pkl文件不存在，开始读取Excel文件...")
        df = read_sap_data()
        if df is None:
            print("数据读取失败，程序退出")
            return
        
        # 保存为pkl文件
        save_as_pkl(df)
    else:
        print("使用pkl文件，跳过Excel读取步骤")
    
    # 显示数据基本信息
    print(f"\n数据基本信息:")
    print(f"总行数: {len(df):,}")
    print(f"总列数: {len(df.columns)}")
    print(f"列名: {list(df.columns)}")
    
    # 分析发票类型
    invoice_type_col, type_counts = analyze_invoice_types(df)
    
    # 按发票类型分别保存
    split_by_invoice_type(df, invoice_type_col)
    
    print("\n处理完成！")

if __name__ == "__main__":
    main()
