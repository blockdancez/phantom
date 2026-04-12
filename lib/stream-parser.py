#!/usr/bin/env python3
"""
stream-parser.py - 解析 AI CLI 流式输出并实时显示

支持两种后端:
  Claude: claude -p --output-format stream-json ... | python3 stream-parser.py <log_file>
  Codex:  codex exec --json ... | python3 stream-parser.py <log_file> codex

第三个参数为 "codex" 时切换到 Codex JSONL 格式解析。
"""

import sys
import json

# ANSI 颜色
DIM = "\033[2m"
NC = "\033[0m"


def parse_claude(log_file):
    """解析 Claude Code stream-json 格式"""
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

                        if name == "Bash":
                            current_tool = f"$ {inp.get('command', '')}"
                        elif name == "Read":
                            current_tool = f"Reading {inp.get('file_path', '')}"
                        elif name == "Edit":
                            current_tool = f"Editing {inp.get('file_path', '')}"
                        elif name == "Write":
                            current_tool = f"Writing {inp.get('file_path', '')}"
                        elif name == "Glob":
                            current_tool = f"Searching {inp.get('pattern', '')}"
                        elif name == "Grep":
                            current_tool = f"Grep {inp.get('pattern', '')}"
                        else:
                            current_tool = name

                    elif bt == "text":
                        current_text += block.get("text", "")

                if current_tool and current_tool != last_tool:
                    sys.stderr.write(f"\n{DIM}[tool] {current_tool}{NC}\n")
                    sys.stderr.flush()
                    last_tool = current_tool

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
        if log_handle:
            log_handle.write(final_result)
            log_handle.close()
        if last_text and not last_text.endswith("\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()


def parse_codex(log_file):
    """解析 Codex JSONL 格式

    Codex 事件格式:
    - {"type":"item.completed","item":{"type":"agent_message","text":"..."}}
    - {"type":"item.completed","item":{"type":"command_execution","command":"...","aggregated_output":"..."}}
    - {"type":"item.started","item":{"type":"command_execution","command":"..."}}
    """
    log_handle = open(log_file, "w") if log_file else None
    all_text = ""

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
            item = event.get("item", {})
            item_type = item.get("type", "")

            if event_type == "item.completed":
                if item_type == "agent_message":
                    # AI 文本输出
                    text = item.get("text", "")
                    if text:
                        sys.stdout.write(text + "\n")
                        sys.stdout.flush()
                        all_text += text + "\n"

                elif item_type == "command_execution":
                    # 命令执行完成，显示命令和输出摘要
                    cmd = item.get("command", "")
                    output = item.get("aggregated_output", "")
                    exit_code = item.get("exit_code", 0)
                    if cmd:
                        # 提取实际命令（去掉 /bin/zsh -lc 包装）
                        display_cmd = cmd
                        if '-lc "' in cmd:
                            display_cmd = cmd.split('-lc "', 1)[1].rstrip('"')
                        elif "-lc '" in cmd:
                            display_cmd = cmd.split("-lc '", 1)[1].rstrip("'")
                        sys.stderr.write(f"\n{DIM}[tool] $ {display_cmd}{NC}\n")
                        sys.stderr.flush()

                elif item_type == "file_edit":
                    # 文件编辑
                    path = item.get("file_path", "") or item.get("path", "")
                    sys.stderr.write(f"\n{DIM}[tool] Editing {path}{NC}\n")
                    sys.stderr.flush()

                elif item_type == "file_create":
                    # 文件创建
                    path = item.get("file_path", "") or item.get("path", "")
                    sys.stderr.write(f"\n{DIM}[tool] Writing {path}{NC}\n")
                    sys.stderr.flush()

            elif event_type == "item.started":
                if item_type == "command_execution":
                    cmd = item.get("command", "")
                    if cmd:
                        display_cmd = cmd
                        if '-lc "' in cmd:
                            display_cmd = cmd.split('-lc "', 1)[1].rstrip('"')
                        elif "-lc '" in cmd:
                            display_cmd = cmd.split("-lc '", 1)[1].rstrip("'")
                        sys.stderr.write(f"\n{DIM}[tool] $ {display_cmd}{NC}\n")
                        sys.stderr.flush()

    except KeyboardInterrupt:
        pass
    finally:
        if log_handle:
            log_handle.write(all_text)
            log_handle.close()
        if all_text and not all_text.endswith("\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()


def main():
    log_file = sys.argv[1] if len(sys.argv) > 1 else None
    backend = sys.argv[2] if len(sys.argv) > 2 else "claude"

    if backend == "codex":
        parse_codex(log_file)
    else:
        parse_claude(log_file)


if __name__ == "__main__":
    main()
