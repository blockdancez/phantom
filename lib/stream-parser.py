#!/usr/bin/env python3
"""
stream-parser.py - 解析 Claude stream-json 输出并实时显示

从 stdin 读取 stream-json 事件，实时输出到终端，同时保存完整结果到文件。

用法: claude -p --output-format stream-json --verbose --include-partial-messages "prompt" \
        2>&1 | python3 stream-parser.py <log_file>
"""

import sys
import json
import os

# ANSI 颜色
CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
DIM = "\033[2m"
NC = "\033[0m"

def main():
    log_file = sys.argv[1] if len(sys.argv) > 1 else None
    log_handle = open(log_file, "w") if log_file else None

    last_text = ""
    last_tool = ""
    final_result = ""

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")

            if event_type == "assistant":
                content = event.get("message", {}).get("content", [])
                current_text = ""
                current_tool = ""

                for block in content:
                    bt = block.get("type")

                    if bt == "tool_use":
                        name = block.get("name", "")
                        inp = block.get("input", {})
                        tool_desc = ""

                        if name == "Bash":
                            cmd = inp.get("command", "")
                            tool_desc = f"$ {cmd}"
                        elif name == "Read":
                            tool_desc = f"Reading {inp.get('file_path', '')}"
                        elif name == "Edit":
                            tool_desc = f"Editing {inp.get('file_path', '')}"
                        elif name == "Write":
                            tool_desc = f"Writing {inp.get('file_path', '')}"
                        elif name == "Glob":
                            tool_desc = f"Searching {inp.get('pattern', '')}"
                        elif name == "Grep":
                            tool_desc = f"Grep {inp.get('pattern', '')}"
                        else:
                            tool_desc = f"{name}"

                        current_tool = tool_desc

                    elif bt == "text":
                        current_text += block.get("text", "")

                # 显示新的工具调用
                if current_tool and current_tool != last_tool:
                    msg = f"\n{DIM}[tool] {current_tool}{NC}\n"
                    sys.stderr.write(msg)
                    sys.stderr.flush()
                    last_tool = current_tool

                # 显示新的文本内容（增量）
                if current_text and len(current_text) > len(last_text):
                    new_part = current_text[len(last_text):]
                    sys.stdout.write(new_part)
                    sys.stdout.flush()
                    last_text = current_text

            elif event_type == "result":
                final_result = event.get("result", "")

    except KeyboardInterrupt:
        pass
    finally:
        # 写入日志文件
        if log_handle:
            log_handle.write(final_result)
            log_handle.close()

        # 确保结尾换行
        if last_text and not last_text.endswith("\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
