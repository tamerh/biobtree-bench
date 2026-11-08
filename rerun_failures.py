"""Re-run cells that failed for infrastructure reasons and merge them back.

The runner treats an exhausted retry (429/5xx) as a cell error. Those cells are
not model failures and must not be scored as wrong. This script collects them,
re-runs only those questions under the same protocol, and copies the new records
over the originals.

Usage:
  python rerun_failures.py --results results/web180 \
      --questions questions/anchor_geneturing_180.json \
      --conditions web --max-iterations 15
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def is_infra_error(rec):
    err = rec.get("error") or ""
    return (
        err.startswith("LLMError")
        or err.startswith("MCPError")
        or "HTTP" in err
        or "cannot reach MCP" in err
    )


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--questions", required=True)
    ap.add_argument("--models", nargs="+", default=["deepseek-v4.1-flash"])
    ap.add_argument("--conditions", nargs="+", required=True)
    ap.add_argument("--max-iterations", type=int, default=15)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    results = Path(args.results)
    failed = set()
    for p in results.glob("*.json"):
        rec = json.loads(p.read_text())
        if rec.get("condition") in args.conditions and is_infra_error(rec):
            failed.add(rec["question_id"])
    if not failed:
        print("no infrastructure failures found")
        return

    src = json.loads(Path(args.questions).read_text())
    subset = [q for q in src["questions"] if q["id"] in failed]
    print(f"{len(failed)} failed questions: {', '.join(sorted(failed))}")
    if args.dry_run:
        print("dry run: no LLM calls made")
        return

    tmp = Path(tempfile.mkdtemp(prefix="rerun_"))
    qfile = tmp / "questions.json"
    qfile.write_text(json.dumps({"questions": subset}, indent=1))
    out = tmp / "out"

    cmd = [sys.executable, "runner.py",
           "--questions", str(qfile),
           "--models", *args.models,
           "--conditions", *args.conditions,
           "--max-iterations", str(args.max_iterations),
           "--out", str(out)]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    replaced = 0
    still_failed = 0
    for p in out.glob("*.json"):
        rec = json.loads(p.read_text())
        if is_infra_error(rec):
            still_failed += 1
            print(f"  still failed: {rec['question_id']} ({rec['error'][:80]})")
            continue
        shutil.copy(p, results / p.name)
        replaced += 1
    print(f"replaced {replaced} records; still failed {still_failed}")


if __name__ == "__main__":
    main()
