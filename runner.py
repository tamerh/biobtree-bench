"""Run the BioBTree benchmark across models and conditions.

Usage:
  python runner.py --questions questions/track_b.json --limit 2 --dry-run
  python runner.py --questions questions/track_b.json \
      --models anthropic/claude-sonnet-5.5 openai/gpt-5.1 \
      --conditions no_tools raw_tools atlas
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import config
import scoring
from llm_client import LLMClient, LLMError
from mcp_client import MCPClient, MCPError
from web_client import WebClient


def slug(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text)).strip("_")


def load_questions(path):
    path = Path(path)
    if path.is_dir():
        items = []
        for p in sorted(path.glob("*.json")):
            items.extend(load_questions(p))
        return items
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = data.get("questions", [])
    for q in data:
        q.setdefault("track", path.stem)
    return data


def run_one(question, model, condition, mcp, llm, max_iterations, web=None):
    """Execute one (question, model, condition) cell."""
    tool_names = config.CONDITION_TOOLS[condition]
    provider = web if condition == "web" else mcp
    tools = provider.openai_tools(tool_names) if tool_names else None

    messages = [
        {"role": "system", "content": config.SYSTEM_PROMPT},
        {"role": "user", "content": question["question"]},
    ]

    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
             "cost_usd": 0.0, "allowance_usd": 0.0}
    tool_log = []
    finish_reasons = []
    comp_tokens = []
    iterations = 0
    answer = ""
    error = None
    started = time.time()

    try:
        for iterations in range(1, max_iterations + 1):
            resp = llm.chat(model, messages, tools=tools)
            finish_reasons.append(resp.get("finish_reason"))
            comp_tokens.append((resp["usage"].get("completion_tokens", 0),
                                resp["usage"].get("total_tokens", 0) - resp["usage"].get("prompt_tokens", 0)))
            for k in usage:
                usage[k] += resp["usage"].get(k, 0)

            if resp["tool_calls"]:
                messages.append(
                    {
                        "role": "assistant",
                        "content": resp["content"] or "",
                        "tool_calls": resp["tool_calls"],
                    }
                )
                for tc in resp["tool_calls"]:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    try:
                        result = provider.call_tool(name, args)
                    except MCPError as e:
                        result = f"TOOL ERROR: {e}"
                    result_for_model = result
                    if name != "biobtree_atlas" and len(result) > config.TOOL_RESULT_MAX_CHARS:
                        # The MCP server bounds tool results structurally (valid
                        # JSON + dropped_inputs). Only cut non-JSON payloads here;
                        # slicing valid JSON would make it unparseable.
                        try:
                            json.loads(result)
                        except json.JSONDecodeError:
                            result_for_model = (
                                result[: config.TOOL_RESULT_MAX_CHARS]
                                + "\n... [truncated]"
                            )
                    tool_log.append(
                        {
                            "tool": name,
                            "arguments": args,
                            "result_chars": len(result),
                            "result": result,
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": result_for_model,
                        }
                    )
            else:
                answer = resp["content"] or ""
                break
        else:
            answer = resp["content"] or ""
            error = "max_iterations reached"
    except (LLMError, Exception) as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"

    elapsed = time.time() - started
    result = scoring.score(question, answer)

    record = {
        "run_id": f"{question['id']}__{slug(model)}__{condition}",
        "question_id": question["id"],
        "track": question.get("track"),
        "model": model,
        "condition": condition,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "answer": answer,
        "iterations": iterations,
        "tool_calls": [
            {k: v for k, v in t.items() if k != "result"} for t in tool_log
        ],
        "usage": usage,
        "latency_s": round(elapsed, 3),
        "score": result["score"],
        "correct": result["correct"],
        "score_detail": result["detail"],
        "error": error,
        "finish_reasons": finish_reasons,
        "comp_tokens": comp_tokens,
        "config": {
            "mcp_url": config.MCP_URL,
            "max_iterations": max_iterations,
            "temperature": config.TEMPERATURE,
            "max_tokens": config.MAX_TOKENS,
            "tool_result_max_chars": config.TOOL_RESULT_MAX_CHARS,
        },
    }
    return record, tool_log, messages


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(config.QUESTIONS_DIR))
    ap.add_argument("--models", nargs="+", default=config.DEFAULT_MODELS)
    ap.add_argument("--conditions", nargs="+", default=config.DEFAULT_CONDITIONS,
                    choices=list(config.CONDITION_TOOLS))
    ap.add_argument("--limit", type=int, default=0, help="first N questions only")
    ap.add_argument("--max-iterations", type=int, default=config.MAX_ITERATIONS)
    ap.add_argument("--out", default=str(config.RESULTS_DIR))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    questions = load_questions(args.questions)
    if args.limit:
        questions = questions[: args.limit]
    if not questions:
        sys.exit("no questions loaded")

    out_dir = Path(args.out)
    tr_dir = out_dir / "transcripts"

    mcp = MCPClient()
    web = WebClient()
    try:
        available = {t["name"] for t in mcp.list_tools()}
    except MCPError as e:
        sys.exit(f"cannot reach MCP at {config.MCP_URL}: {e}")
    mcp_conditions = [c for c in args.conditions if c != "web"]
    missing = {n for c in mcp_conditions for n in config.CONDITION_TOOLS[c]} - available
    if missing:
        sys.exit(f"MCP is missing tools: {sorted(missing)}")

    total = len(questions) * len(args.models) * len(args.conditions)
    print(f"questions={len(questions)} models={len(args.models)} "
          f"conditions={len(args.conditions)} cells={total}")
    print(f"MCP={config.MCP_URL}  max_iterations={args.max_iterations}")

    if args.dry_run:
        for q in questions:
            print(f"  [{q.get('track')}] {q['id']}: {q['question'][:90]}")
        print("\ndry run: no LLM calls made")
        return

    llm = LLMClient()
    out_dir.mkdir(parents=True, exist_ok=True)
    tr_dir.mkdir(parents=True, exist_ok=True)

    done = 0
    for q in questions:
        for model in args.models:
            for cond in args.conditions:
                done += 1
                print(f"[{done}/{total}] {q['id']} | {model} | {cond} ... ",
                      end="", flush=True)
                rec, tool_log, messages = run_one(
                    q, model, cond, mcp, llm, args.max_iterations, web=web
                )
                (out_dir / f"{rec['run_id']}.json").write_text(
                    json.dumps(rec, indent=2, ensure_ascii=False)
                )
                (tr_dir / f"{rec['run_id']}.json").write_text(
                    json.dumps(
                        {"record": rec, "tool_log": tool_log, "messages": messages},
                        indent=2, ensure_ascii=False,
                    )
                )
                flag = "OK " if rec.get("correct") else "   "
                print(f"{flag} score={rec['score']} tok={rec['usage']['total_tokens']} "
                      f"it={rec['iterations']} {rec.get('error') or ''}")

    print(f"\nwrote {done} runs to {out_dir}")


if __name__ == "__main__":
    main()
