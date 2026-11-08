"""Tool-selection diagnostic for the dilution test.

Reads a results directory produced by runner.py on the tool_selection_probe
questions and reports whether the model's *first* tool call matches the
expected tool, plus false positives for the added tool.

This is a diagnostic, not a scored benchmark. Answers are not graded.

Usage:
  python analyze_tools.py --results results/toolsel_6tools \
      --questions questions/tool_selection_probe.json
"""

import argparse
import collections
import glob
import json
from pathlib import Path


def load_expected(path):
    data = json.loads(Path(path).read_text())
    return {q["id"]: q["expected_tool"] for q in data["questions"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--questions", default="questions/tool_selection_probe.json")
    ap.add_argument("--condition", default=None,
                    help="only analyse this condition (default: all found)")
    args = ap.parse_args(argv)

    expected = load_expected(args.questions)
    rows = [json.loads(Path(p).read_text()) for p in glob.glob(f"{args.results}/*.json")]
    if args.condition:
        rows = [r for r in rows if r["condition"] == args.condition]
    if not rows:
        raise SystemExit("no result records found")

    by_condition = collections.defaultdict(list)
    for r in rows:
        by_condition[r["condition"]].append(r)

    for cond, recs in sorted(by_condition.items()):
        print(f"\n=== condition: {cond}  ({len(recs)} runs) ===")
        correct = 0
        scored = 0
        conf = collections.Counter()
        fp = collections.Counter()
        fp_cells = 0
        no_call = 0
        per_expected = collections.defaultdict(lambda: [0, 0])

        for r in recs:
            exp = expected.get(r["question_id"])
            calls = r.get("tool_calls") or []
            per_expected[exp][1] += 1
            if not calls:
                no_call += 1
                continue
            first = calls[0]["tool"]
            scored += 1
            conf[(exp, first)] += 1
            if first == exp:
                correct += 1
                per_expected[exp][0] += 1
            # calls to a tool that is not expected and not a generic pre-step
            if exp != "biobtree_variant":
                vcalls = [c for c in calls if c["tool"] == "biobtree_variant"]
                if vcalls:
                    fp_cells += 1
                    fp["variant_calls_on_non_variant"] += len(vcalls)

        print(f"first-tool accuracy: {correct}/{scored} "
              f"({correct / scored:.2%})" if scored else "no tool calls")
        if no_call:
            print(f"runs with no tool call: {no_call}")
        print("per expected tool:")
        for exp in sorted(per_expected):
            ok, n = per_expected[exp]
            print(f"  {exp:<18} {ok}/{n}")
        print("confusion (expected -> first):")
        for (exp, first), n in sorted(conf.items()):
            mark = "" if exp == first else "  <-- mismatch"
            print(f"  {exp:<18} -> {first:<18} {n:3d}{mark}")
        if fp:
            print(f"false positives: {fp_cells} non-variant cells "
                  f"({fp_cells / max(len(recs) - per_expected.get('biobtree_variant', [0, 0])[1], 1):.1%}) "
                  f"with {fp['variant_calls_on_non_variant']} calls")
        calls = [len(r.get("tool_calls") or []) for r in recs]
        print(f"calls/run: {sum(calls) / len(calls):.2f}")


if __name__ == "__main__":
    main()
