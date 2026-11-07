"""Analyze benchmark results: summary, paired table, McNemar, CSV export.

Usage:
  python analyze.py --results results/ --csv results/paired.csv
"""

import argparse
import csv
import json
from collections import defaultdict
from math import comb
from pathlib import Path


def load_runs(results_dir):
    runs = []
    for p in sorted(Path(results_dir).glob("*.json")):
        if p.parent.name == "transcripts":
            continue
        try:
            runs.append(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue
    return runs


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p-value from discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def summarize(runs):
    agg = defaultdict(lambda: {"n": 0, "correct": 0, "tokens": 0, "latency": 0.0,
                               "tool_calls": 0, "errors": 0, "cost": 0.0,
                               "allowance": 0.0})
    for r in runs:
        key = (r["model"], r["condition"])
        a = agg[key]
        a["n"] += 1
        a["correct"] += 1 if r.get("correct") else 0
        a["tokens"] += (r.get("usage") or {}).get("total_tokens", 0)
        a["latency"] += r.get("latency_s") or 0
        a["tool_calls"] += len(r.get("tool_calls") or [])
        a["errors"] += 1 if r.get("error") else 0
        a["cost"] += (r.get("usage") or {}).get("cost_usd", 0) or 0
        a["allowance"] += (r.get("usage") or {}).get("allowance_usd", 0) or 0
    return agg


def paired(runs, cond_a, cond_b):
    """Pair runs by (question, model); return discordant counts per model."""
    by_key = {}
    for r in runs:
        by_key[(r["question_id"], r["model"], r["condition"])] = r

    per_model = defaultdict(lambda: {"b": 0, "c": 0, "n": 0})
    for (qid, model, cond) in list(by_key):
        if cond != cond_a:
            continue
        a = by_key.get((qid, model, cond_a))
        b = by_key.get((qid, model, cond_b))
        if not a or not b or a.get("correct") is None or b.get("correct") is None:
            continue
        s = per_model[model]
        s["n"] += 1
        if a["correct"] and not b["correct"]:
            s["b"] += 1
        elif b["correct"] and not a["correct"]:
            s["c"] += 1
    return per_model


def load_question_meta(questions_dir="questions"):
    """id -> {module, category, track} from the question files."""
    meta = {}
    for p in Path(questions_dir).glob("*.json"):
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        for q in data.get("questions", []):
            meta[q["id"]] = {
                "module": q.get("module") or q.get("category") or q.get("track"),
                "track": q.get("track"),
            }
    return meta


def by_group(runs, meta, group="module"):
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in runs:
        g = meta.get(r["question_id"], {}).get(group) or "unknown"
        cell = agg[g][r["condition"]]
        cell[0] += 1
        cell[1] += 1 if r.get("correct") else 0
    return agg


def load_questions_map(questions_dir="questions"):
    """id -> full question object, for rescoring stored answers."""
    out = {}
    for p in Path(questions_dir).glob("*.json"):
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        for q in data.get("questions", []):
            out[q["id"]] = q
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--rescore", action="store_true",
                    help="recompute scores from stored answers (no LLM calls)")
    args = ap.parse_args(argv)

    runs = load_runs(args.results)
    if not runs:
        raise SystemExit(f"no result files in {args.results}")

    if args.rescore:
        import scoring
        qmap = load_questions_map()
        changed = 0
        for r in runs:
            q = qmap.get(r["question_id"])
            if not q:
                continue
            res = scoring.score(q, r.get("answer") or "")
            if res["correct"] != r.get("correct"):
                changed += 1
            r["score"] = res["score"]
            r["correct"] = res["correct"]
            r["score_detail"] = res["detail"]
        print(f"rescored {len(runs)} runs ({changed} changed)\n")

    print(f"loaded {len(runs)} runs\n")

    agg = summarize(runs)
    print(f"{'model':<34}{'condition':<12}{'n':>4}{'acc':>7}{'tok/run':>10}"
          f"{'lat/run':>9}{'calls':>7}{'err':>5}{'cost$':>8}")
    for (model, cond), a in sorted(agg.items()):
        acc = a["correct"] / a["n"] if a["n"] else 0
        print(f"{model:<34}{cond:<12}{a['n']:>4}{acc:>7.2f}"
              f"{a['tokens'] // max(a['n'], 1):>10}"
              f"{a['latency'] / max(a['n'], 1):>9.2f}"
              f"{a['tool_calls'] / max(a['n'], 1):>7.1f}{a['errors']:>5}"
              f"{a['cost']:>8.3f}")

    conditions = sorted({r["condition"] for r in runs})

    meta = load_question_meta()
    if meta:
        print("\naccuracy by module")
        grouped = by_group(runs, meta)
        conds = sorted({r["condition"] for r in runs})
        print(f"{'module':<28}" + "".join(f"{c:>12}" for c in conds))
        for g in sorted(grouped):
            row = f"{g:<28}"
            for c in conds:
                n, ok = grouped[g].get(c, [0, 0])
                row += f"{(ok / n if n else 0):>12.2f}"
            print(row)

    if len(conditions) >= 2:
        print("\npaired comparisons (McNemar exact, two-sided)")
        for i, ca in enumerate(conditions):
            for cb in conditions[i + 1:]:
                pm = paired(runs, ca, cb)
                for model, s in sorted(pm.items()):
                    if s["n"] == 0:
                        continue
                    p = mcnemar_exact(s["b"], s["c"])
                    print(f"  {model:<32} {ca} vs {cb}: "
                          f"n={s['n']:>3} b={s['b']:>3} c={s['c']:>3} p={p:.4g}")

    if args.csv:
        path = Path(args.csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = ["run_id", "question_id", "track", "model", "condition",
                  "correct", "score", "iterations", "total_tokens",
                  "prompt_tokens", "completion_tokens", "latency_s",
                  "n_tool_calls", "error"]
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in runs:
                u = r.get("usage") or {}
                w.writerow({
                    "run_id": r.get("run_id"),
                    "question_id": r.get("question_id"),
                    "track": r.get("track"),
                    "model": r.get("model"),
                    "condition": r.get("condition"),
                    "correct": r.get("correct"),
                    "score": r.get("score"),
                    "iterations": r.get("iterations"),
                    "total_tokens": u.get("total_tokens", 0),
                    "prompt_tokens": u.get("prompt_tokens", 0),
                    "completion_tokens": u.get("completion_tokens", 0),
                    "latency_s": r.get("latency_s"),
                    "n_tool_calls": len(r.get("tool_calls") or []),
                    "error": r.get("error") or "",
                })
        print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
