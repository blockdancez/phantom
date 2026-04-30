"""AIFinder —— AI 榨汁机的"投喂者"。

它不属于流水线内部 step，而是**源头**：
1. 自主产生一批候选 topic（这里用内置种子；生产版本可接 LLM / 爬虫 / RSS）
2. 为每个 topic 调 POST /api/workflows，让 AIJuicer 启动一条完整流水线
3. 退出（一次性）或按 --interval 周期运行

与流水线 idea/requirement/... agent 的区别：
- 这些 pipeline agent 通过 Redis Streams **消费** 任务
- AIFinder 通过 HTTP **生产** 工作流

用法：
    python -m sdk.examples.ai_finder --count 3
    python -m sdk.examples.ai_finder --topic "AI 写作助手"
    python -m sdk.examples.ai_finder --count 2 --auto   # 全自动审批策略
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time

import httpx

SEED_TOPICS = [
    "AI 代码审查助手",
    "智能会议纪要生成器",
    "电商评论情感洞察",
    "AI 视频字幕翻译",
    "个性化学习路径推荐",
    "自动生成运营海报",
    "代码库问答机器人",
    "AI 播客剪辑工具",
    "数据看板自然语言查询",
    "AI 简历优化器",
]

STEPS = ("requirement", "plan", "design", "devtest", "deploy")


def generate_topics(n: int) -> list[str]:
    random.shuffle(SEED_TOPICS)
    if n <= len(SEED_TOPICS):
        return SEED_TOPICS[:n]
    # 超过种子数则随机拼接修饰词
    extra_prefix = ["新一代", "实时", "轻量级", "企业级", "多模态"]
    out = list(SEED_TOPICS)
    while len(out) < n:
        out.append(f"{random.choice(extra_prefix)}{random.choice(SEED_TOPICS)}")
    return out[:n]


def post_workflow(server: str, name: str, topic: str, auto: bool) -> str:
    policy = {s: "auto" for s in STEPS} if auto else {}
    r = httpx.post(
        f"{server}/api/workflows",
        json={"name": name, "input": {"text": topic}, "approval_policy": policy},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["id"]


def main() -> None:
    p = argparse.ArgumentParser(prog="ai-finder", description=__doc__.splitlines()[0])
    p.add_argument("--server", default=os.environ.get("AIJUICER_SERVER", "http://127.0.0.1:8000"))
    p.add_argument("--count", type=int, default=1, help="本次产生多少条 idea")
    p.add_argument("--topic", help="手动指定一个 topic；指定时忽略 --count")
    p.add_argument("--auto", action="store_true", help="审批策略全设 auto（一路跑到底）")
    p.add_argument(
        "--interval",
        type=int,
        default=0,
        help="循环间隔秒数；>0 则变成常驻进程，每 interval 生成一批",
    )
    args = p.parse_args()

    def one_batch() -> None:
        topics = [args.topic] if args.topic else generate_topics(args.count)
        for t in topics:
            wf_id = post_workflow(
                args.server, name=f"ai-finder · {t[:24]}", topic=t, auto=args.auto
            )
            sys.stdout.write(f"🧃 AIJuicer 接单：{wf_id}  ← topic: {t}\n")

    try:
        one_batch()
        while args.interval > 0:
            time.sleep(args.interval)
            one_batch()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
