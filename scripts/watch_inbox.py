#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
监听 inbox 文件夹，一个一个处理 PDF 文件
用法：python3 watch_inbox.py
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path.home() / 'Desktop' / '文献管理 html'
INBOX_DIR = BASE_DIR / 'inbox'
INCOMING_DIR = BASE_DIR / 'incoming'
UPDATE_SCRIPT = BASE_DIR / 'scripts' / 'update_library.py'

SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.txt', '.md', '.html', '.zip'}
POLL_INTERVAL = 2  # 秒

def ensure_dirs():
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)

def get_pending_files():
    """获取待处理的文件，按文件名排序"""
    files = []
    for p in INBOX_DIR.iterdir():
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS and not p.name.startswith('.'):
            files.append(p)
    return sorted(files, key=lambda x: x.name)

def process_one(file_path):
    """处理单个文件：搬到 incoming → 调用 update_library.py → 删除原文件"""
    print(f"\n[{time.strftime('%H:%M:%S')}] 开始处理：{file_path.name}")
    
    # 1. 搬到 incoming
    target = INCOMING_DIR / file_path.name
    try:
        shutil.move(str(file_path), str(target))
        print(f"  ✓ 已移动到 incoming/")
    except Exception as e:
        print(f"  ✗ 移动失败：{e}")
        return False
    
    # 2. 调用 update_library.py
    print(f"  → 正在解析...")
    try:
        result = subprocess.run(
            [sys.executable, str(UPDATE_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode == 0:
            print(f"  ✓ 解析成功")
            # 尝试解析输出
            try:
                output = json.loads(result.stdout)
                if output.get('auto_sync', {}).get('ok'):
                    print(f"  ✓ 已同步到 VPS")
                elif output.get('auto_sync', {}).get('enabled'):
                    print(f"  ⚠ VPS 同步失败：{output['auto_sync'].get('message', '未知错误')}")
            except:
                pass
        else:
            print(f"  ✗ 解析失败：{result.stderr[:200]}")
            # 解析失败也要把文件搬回来，避免丢失
            shutil.move(str(target), str(file_path))
            print(f"  ← 已恢复原文件到 inbox/")
            return False
    except subprocess.TimeoutExpired:
        print(f"  ✗ 解析超时")
        shutil.move(str(target), str(file_path))
        print(f"  ← 已恢复原文件到 inbox/")
        return False
    except Exception as e:
        print(f"  ✗ 异常：{e}")
        shutil.move(str(target), str(file_path))
        print(f"  ← 已恢复原文件到 inbox/")
        return False
    
    # 3. 删除 inbox 里的原文件（已经移动了，这里不需要再删）
    # 文件已经在第 1 步从 inbox 移走了，所以这里什么都不用做
    print(f"  ✓ 完成：{file_path.name}")
    return True

def main():
    ensure_dirs()
    print(f"监听文件夹：{INBOX_DIR}")
    print(f"支持格式：{', '.join(SUPPORTED_EXTENSIONS)}")
    print(f"按 Ctrl+C 停止\n")
    
    processed = set()
    
    try:
        while True:
            pending = get_pending_files()
            
            if pending:
                # 有新文件
                for file_path in pending:
                    if file_path.name not in processed:
                        success = process_one(file_path)
                        if success:
                            processed.add(file_path.name)
                        # 处理完一个就等一会，避免并发
                        time.sleep(POLL_INTERVAL)
            else:
                # 没有文件，轮询等待
                time.sleep(POLL_INTERVAL)
                
    except KeyboardInterrupt:
        print(f"\n\n停止监听。已处理 {len(processed)} 个文件。")

if __name__ == '__main__':
    main()
