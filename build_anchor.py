"""Build the GeneTuring anchor question set.

Reads the GeneTuring Q&A CSV (Hou & Ji 2023) and emits a fixed, reproducible
sample in this benchmark's schema.

Source CSV:
  https://raw.githubusercontent.com/Winnie09/GeneTuring/main/GeneGPT/Q%26A_dataset.csv

Usage:
  python build_anchor.py --csv /path/to/Q%26A_dataset.csv \
      --per-module 20 --seed 42 --out questions/anchor_geneturing_100.json
"""

import argparse
import csv
import json
import random
import re

# Modules BioBTree can in principle answer, with the answer type to score them.
MODULES = {
    "Gene location": "chromosome",
    "SNP location": "chromosome",
    "Gene alias": "exact",
    "Gene name conversion": "exact",
    "Gene SNP association": "exact",
    "TF regulation": "enum",
    "Protein-coding genes": "protein_coding",
}


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()


def to_question(row, idx):
    module = row["Module"]
    qtype = MODULES[module]
    gold = (row["Goldstandard"] or "").strip()
    q = {
        "id": f"G100_{idx:03d}_{slug(module)}",
        "track": "anchor",
        "source": "GeneTuring",
        "module": module,
        "question": row["Question"].strip(),
        "answer_type": qtype,
        "original_gold": gold,
    }
    if qtype == "chromosome":
        q["gold"] = re.sub(r"^chr", "", gold, flags=re.I)
    elif qtype == "enum":
        q["gold"] = gold
        q["accepted"] = ["Activation", "Repression", "No"]
    elif qtype == "protein_coding":
        # GeneTuring gold is TRUE (protein-coding) or NA (not applicable).
        q["answer_type"] = "enum"
        if gold.upper() == "TRUE":
            q["gold"] = "TRUE"
            q["accepted"] = ["TRUE", "yes", "protein-coding", "codes a protein",
                             "protein coding"]
        else:
            q["gold"] = "NA"
            q["accepted"] = ["NA", "no", "not protein-coding", "non-coding",
                             "pseudogene", "not applicable", "not a protein"]
    else:
        q["gold"] = gold
    return q


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--per-module", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--modules", nargs="+", default=list(MODULES))
    ap.add_argument("--out", default="questions/anchor_geneturing_100.json")
    args = ap.parse_args(argv)

    rows = list(csv.DictReader(open(args.csv)))
    rng = random.Random(args.seed)

    picked = []
    for module in args.modules:
        pool = [r for r in rows if r["Module"] == module]
        if not pool:
            print(f"  no rows for module {module!r}, skipping")
            continue
        n = min(args.per_module, len(pool))
        picked.extend(rng.sample(pool, n))

    questions = [to_question(r, i) for i, r in enumerate(picked)]
    with open(args.out, "w") as f:
        json.dump({"questions": questions}, f, indent=2, ensure_ascii=False)

    print(f"wrote {len(questions)} questions to {args.out}")
    for q in questions[:5]:
        print(f"  {q['id']:<34} gold={q['gold']!r}")


if __name__ == "__main__":
    main()
