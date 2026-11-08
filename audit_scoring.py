"""Scoring audit: sample answers and surface likely scoring errors.

Flags:
  FN?  scored wrong, but the gold token appears in the answer (normalisation gap)
  FP?  scored correct, but the answer is very short or the gold match is suspicious

Usage:
  python audit_scoring.py --results results/final/anchor900 --condition mcp -n 50 --seed 1
"""

import argparse
import json
import random
import re
from pathlib import Path

import scoring


def norm(s):
    return scoring.normalize(s or "")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--condition", default="mcp")
    ap.add_argument("-n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)

    runs = []
    for p in Path(args.results).glob("*.json"):
        if p.parent.name == "transcripts":
            continue
        r = json.loads(p.read_text())
        if r.get("condition") == args.condition:
            runs.append(r)
    random.seed(args.seed)
    sample = random.sample(runs, min(args.n, len(runs)))

    fn = fp = 0
    for r in sample:
        gold = r.get("score_detail", {}).get("gold")
        ans = r.get("answer") or ""
        g = gold if isinstance(gold, str) else json.dumps(gold)
        flag = ""
        if not r.get("correct") and g and norm(g) in norm(ans):
            flag = "FN?"
            fn += 1
        elif r.get("correct") and len(norm(ans)) < 3:
            flag = "FP?"
            fp += 1
        print(f"{r['question_id']:<38} correct={str(r.get('correct'))[:5]:<5} "
              f"gold={str(gold)[:28]:<28} {flag}")
        print(f"    Q: {r.get('question','')[:110]}")
        print(f"    A: {ans[:140].replace(chr(10), ' ')}")

    print(f"\nsampled {len(sample)}; heuristic FN={fn} FP={fp}")
    print("Adjudicate the printed pairs: a correct gold match in context is TP; "
          "a match that answers a different question is a scoring error.")


if __name__ == "__main__":
    main()
