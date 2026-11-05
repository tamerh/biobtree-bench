"""Build a LAB-Bench DbQA anchor set from the public files.

Downloads the public DbQA subtasks that BioBTree covers and writes a
multiple-choice question set in the benchmark's native format.

Covered subtasks (verified against BioBTree, 10/10 retrieval each):
  gene_location         -> HGNC / Ensembl cytoband
  mirna_targets         -> hgnc -> ensembl -> refseq -> mirdb
  oncogenic_signatures  -> MSigDB C2:CGP set membership
  vax_response          -> MSigDB C2:CGP set membership

Not included (no matching data source in BioBTree):
  dga                   -> needs DisGeNET
  tfbs_GTRD             -> needs GTRD binding sites (JASPAR only)
  viral_ppi             -> needs P-HIPSter
  variant_from_sequence -> needs genome sequence / alignment
  variant_multi_sequence

Usage: python3 build_labbench.py [--out questions/labbench_dbqa.json]
"""

import argparse
import json
import random
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/Future-House/LAB-Bench/main/DbQA"
SUBTASKS = [
    "gene_location",
    "mirna_targets",
    "oncogenic_signatures",
    "vax_response",
]
LETTERS = ["A", "B", "C", "D"]


def fetch(subtask):
    url = f"{BASE}/{subtask}_task-v1-public.jsonl"
    with urllib.request.urlopen(url, timeout=60) as r:
        return [json.loads(line) for line in r.read().decode().splitlines() if line.strip()]


def build(subtasks, seed=42):
    questions = []
    for subtask in subtasks:
        rows = fetch(subtask)
        for row in rows:
            options = [row["ideal"]] + list(row["distractors"])
            rng = random.Random(f"{seed}:{row['id']}")
            rng.shuffle(options)
            gold_letter = LETTERS[options.index(row["ideal"])]
            block = "\n".join(f"{LETTERS[i]}. {opt}" for i, opt in enumerate(options))
            questions.append(
                {
                    "id": f"LABBENCH_{subtask}_{row['id'][:8]}",
                    "track": "anchor",
                    "source": "LAB-Bench",
                    "module": f"DbQA / {subtask}",
                    "question": f"{row['question'].strip()}\n\n{block}\n\nAnswer with the option letter (A-D).",
                    "answer_type": "mcq",
                    "options": options,
                    "gold": gold_letter,
                    "gold_text": row["ideal"],
                }
            )
    return questions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="questions/labbench_dbqa.json")
    args = ap.parse_args()

    questions = build(SUBTASKS)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"questions": questions}, indent=2) + "\n")
    by_module = {}
    for q in questions:
        by_module[q["module"]] = by_module.get(q["module"], 0) + 1
    print(f"wrote {len(questions)} questions to {out}")
    for k, v in sorted(by_module.items()):
        print(f"  {k:<34} {v}")


if __name__ == "__main__":
    main()
