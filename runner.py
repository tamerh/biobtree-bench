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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import config
import scoring
from llm_client import LLMClient, LLMError
from mcp_client import MCPClient, MCPError
from web_client import WebClient


def is_infra_error(rec):
    err = (rec or {}).get("error") or ""
    return (
        err.startswith("LLMError")
        or err.startswith("MCPError")
        or "HTTP" in err
        or "cannot reach MCP" in err
    )


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

    usage = {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0,
             "total_tokens": 0, "cost_usd": 0.0, "allowance_usd": 0.0}
    tool_log = []
    llm_seconds = 0.0
    tool_seconds = 0.0
    finish_reasons = []
    comp_tokens = []
    providers = []
    iterations = 0
    answer = ""
    error = None
    started = time.time()

    try:
        for iterations in range(1, max_iterations + 1):
            _t0 = time.time()
            resp = llm.chat(model, messages, tools=tools)
            llm_seconds += time.time() - _t0
            finish_reasons.append(resp.get("finish_reason"))
            if resp.get("provider"):
                providers.append(resp["provider"])
            comp_tokens.append((resp["usage"].get("completion_tokens", 0),
                                resp["usage"].get("total_tokens", 0) - resp["usage"].get("prompt_tokens", 0)))
            for k in usage:
                usage[k] += resp["usage"].get(k, 0)

            if resp["tool_calls"]:
                assistant_msg = {
                    "role": "assistant",
                    "content": resp["content"] or "",
                    "tool_calls": resp["tool_calls"],
                }
                if config.PASS_REASONING_BACK and resp.get("reasoning_content"):
                    assistant_msg["reasoning_content"] = resp["reasoning_content"]
                messages.append(assistant_msg)
                for tc in resp["tool_calls"]:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    _t1 = time.time()
                    try:
                        result = provider.call_tool(name, args)
                    except MCPError as e:
                        result = f"TOOL ERROR: {e}"
                    _tool_s = time.time() - _t1
                    tool_seconds += _tool_s
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
                            "duration_s": round(_tool_s, 3),
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
        "providers": sorted(set(providers)),
        "timing": {
            "llm_s": round(llm_seconds, 3),
            "tool_s": round(tool_seconds, 3),
            "total_s": round(elapsed, 3),
        },
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
    ap.add_argument("--resume", action="store_true",
                    help="skip cells already written without an infrastructure error")
    ap.add_argument("--workers", type=int, default=1,
                    help="run this many cells concurrently (default 1; each worker "
                         "uses its own MCP and HTTP clients)")
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

    tasks = []
    done = 0
    for q in questions:
        for model in args.models:
            for cond in args.conditions:
                done += 1
                if args.resume:
                    rid = f"{q['id']}__{slug(model)}__{cond}"
                    fp = out_dir / f"{rid}.json"
                    if fp.exists():
                        try:
                            prev = json.loads(fp.read_text())
                        except json.JSONDecodeError:
                            prev = None
                        if prev is not None and not is_infra_error(prev):
                            print(f"[{done}/{total}] {q['id']} | {model} | {cond} ... skip")
                            continue
                tasks.append((done, q, model, cond))

    print_lock = threading.Lock()
    completed = {"n": 0}

    def work(task):
        index, q, model, cond = task
        client_mcp = MCPClient()
        client_llm = LLMClient()
        client_web = WebClient() if cond == "web" else None
        with print_lock:
            print(f"[{index}/{total}] {q['id']} | {model} | {cond} ... ",
                  end="", flush=True)
        rec, tool_log, messages = run_one(
            q, model, cond, client_mcp, client_llm, args.max_iterations, web=client_web
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
        with print_lock:
            completed["n"] += 1
            return (f"[{index}/{total}] {q['id']} | {model} | {cond} "
                    f"{flag} score={rec['score']} tok={rec['usage']['total_tokens']} "
                    f"it={rec['iterations']} {rec.get('error') or ''}")

    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for line in pool.map(work, tasks):
                print(line, flush=True)
    else:
        for task in tasks:
            print(work(task), flush=True)

    print(f"\nwrote {completed['n']} runs to {out_dir}")


if __name__ == "__main__":
    main()
