#!/usr/bin/env python3
"""Compare the same questions across repeated mcp runs.

    python3 compare_runs.py results/final/go/anchor900 results/final/go/rerun_tfgo_200

Prints per-module accuracy for each run over the questions they share, plus
McNemar between the first two runs, so a re-run can be read as variance or as a
shift rather than eyeballed.
"""
import collections
import glob
import json
import os
import sys
from math import comb


def load(directory, condition='mcp'):
    out = {}
    for path in glob.glob(os.path.join(directory, '*.json')):
        with open(path) as fh:
            r = json.load(fh)
        if r.get('condition') == condition:
            out[r['question_id']] = r
    return out


def module_of(qid):
    return qid.split('_', 2)[2] if qid.count('_') >= 2 else qid


def mcnemar_p(b, c):
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


def main(dirs):
    runs = [load(d) for d in dirs]
    common = set(runs[0])
    for run in runs[1:]:
        common &= set(run)
    if not common:
        print('no shared questions')
        return
    per = collections.defaultdict(lambda: [0] * (2 * len(runs)))
    for qid in common:
        for k, run in enumerate(runs):
            per[module_of(qid)][2 * k] += 1 if run[qid].get('correct') else 0
            per[module_of(qid)][2 * k + 1] += 1
    header = '  '.join(f'run{i + 1:>2}' for i in range(len(runs)))
    print(f'{"module":<26}{header:>26}{"n":>6}')
    for module, v in sorted(per.items()):
        cells = '  '.join(f'{v[2 * k]:>4}/{v[2 * k + 1]:<4}' for k in range(len(runs)))
        print(f'{module:<26}{cells:>26}{v[1]:>6}')
    for k in range(len(runs)):
        acc = sum(v[2 * k] for v in per.values()) / len(common)
        print(f'run{k + 1} overall {acc:.3f}')
    if len(runs) >= 2:
        b = sum(1 for q in common if runs[0][q].get('correct') and not runs[1][q].get('correct'))
        c = sum(1 for q in common if runs[1][q].get('correct') and not runs[0][q].get('correct'))
        print(f'McNemar run1 vs run2: b={b} c={c} p={mcnemar_p(b, c):.4g}')


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1:])
