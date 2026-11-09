"""对比评测：同一批问题分别走「单次 RAG」和「Agent」，比较效果与成本。

用法：
    python -m scripts.eval_agent            # 跑默认 10 题
输出：控制台表格 + D:\\dsh生成文件\\agent_eval.md
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8000"

QUESTIONS = [
    "今天有哪些科技新闻？",
    "最近体育界有什么重磅新闻？",
    "有没有关于人工智能的报道？",
    "科技和财经最近分别有什么大事？",
    "对比一下最近的手机行业新闻和汽车行业新闻",
    "最近有哪些关于新能源的消息？请详细讲讲其中一条",
    "帮我把最近关于 AI 芯片的新闻梳理一下",
    "今天财经方面有没有值得关注的事？",
    "最近文化和娱乐领域有什么值得看的？",
    "国际新闻里有哪些和中国有关的？",
]


async def ask(client: httpx.AsyncClient, question: str, mode: str) -> dict:
    started = time.perf_counter()
    answer_parts: list[str] = []
    steps: list[str] = []
    usage = None
    refs = 0

    async with client.stream("POST", f"{BASE}/api/ai/chat?mode={mode}",
                             json={"question": question}) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if event["type"] == "delta":
                answer_parts.append(event["content"])
            elif event["type"] == "step":
                steps.append(event["text"])
            elif event["type"] == "refs":
                refs = len(event.get("refs") or [])
            elif event["type"] == "done":
                usage = event.get("usage")
                refs = refs or len(event.get("refs") or [])

    return {
        "answer": "".join(answer_parts),
        "steps": steps,
        "refs": refs,
        "usage": usage or {},
        "seconds": round(time.perf_counter() - started, 1),
    }


async def main() -> None:
    rows = []
    async with httpx.AsyncClient(timeout=300) as client:
        for i, question in enumerate(QUESTIONS, 1):
            print(f"[{i}/{len(QUESTIONS)}] {question}")
            rag = await ask(client, question, "rag")
            agent = await ask(client, question, "agent")
            rows.append({"q": question, "rag": rag, "agent": agent})
            print(f"   RAG   {rag['seconds']}s  {rag['usage'].get('totalTokens')} tokens  "
                  f"¥{rag['usage'].get('cost', 0):.5f}")
            print(f"   Agent {agent['seconds']}s  {agent['usage'].get('totalTokens')} tokens  "
                  f"¥{agent['usage'].get('cost', 0):.5f}  步骤 {len(agent['steps'])}")

    # 汇总
    def total(key):
        return sum(r["usage"].get(key, 0) or 0 for row in rows for r in (row["rag"], row["agent"]))

    rag_cost = sum(r["rag"]["usage"].get("cost", 0) for r in rows)
    agent_cost = sum(r["agent"]["usage"].get("cost", 0) for r in rows)
    rag_sec = sum(r["rag"]["seconds"] for r in rows) / len(rows)
    agent_sec = sum(r["agent"]["seconds"] for r in rows) / len(rows)

    lines = [
        "# Agent vs RAG 对比评测\n",
        f"- 问题数：{len(rows)}",
        f"- 单次 RAG：平均 {rag_sec:.1f}s，总成本 ¥{rag_cost:.4f}",
        f"- Agent：平均 {agent_sec:.1f}s，总成本 ¥{agent_cost:.4f}",
        "",
        "| # | 问题 | RAG 耗时 | RAG 成本 | Agent 耗时 | Agent 成本 | 工具步数 |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, row in enumerate(rows, 1):
        lines.append(
            f"| {i} | {row['q']} | {row['rag']['seconds']}s | ¥{row['rag']['usage'].get('cost', 0):.5f} "
            f"| {row['agent']['seconds']}s | ¥{row['agent']['usage'].get('cost', 0):.5f} "
            f"| {len(row['agent']['steps'])} |"
        )

    lines.append("\n## 回答对比\n")
    for i, row in enumerate(rows, 1):
        lines.append(f"### {i}. {row['q']}\n")
        lines.append(f"**RAG（{row['rag']['seconds']}s）**：\n{row['rag']['answer'][:400]}\n")
        steps = " → ".join(row["agent"]["steps"]) or "（无工具调用）"
        lines.append(f"**Agent（{row['agent']['seconds']}s，{steps}）**：\n{row['agent']['answer'][:400]}\n")

    out = Path(r"D:\dsh生成文件\agent_eval.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入 {out}")


if __name__ == "__main__":
    asyncio.run(main())
