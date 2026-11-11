"""Export every benchmark cell used in the paper to one CSV.

The raw run folders under results/ (answers, tool calls and transcripts) are too
large for git; this table keeps, for each cell, the question, the gold answer,
the model's final answer, its score and its cost, so every number in the paper
can be recomputed from the repository.

Usage: python3 export_cells.py   ->  cells.csv
"""
import ast
import csv
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# (study set, run folder, question-id prefix, conditions to keep or None for all);
# the model is read from each record. Two folders also hold pilot runs of other
# conditions that the paper does not use, hence the condition filter.
RUNS = [
    ('geneturing', 'results/anchor900', 'G100_', {'no_tools'}),
    ('geneturing', 'results/final/go/anchor900', 'G100_', None),
    ('geneturing', 'results/final/go/anchor900_web', 'G100_', None),
    ('geneturing', 'results/second_model/haiku', 'G100_', None),
    ('geneturing', 'results/ot_full_haiku', 'G100_', None),
    ('geneturing', 'results/biomcp_full', 'G100_', None),
    ('labbench', 'results/labbench160_mt16k', 'LABBENCH', {'no_tools'}),
    ('labbench', 'results/final/go/labbench160', 'LABBENCH', None),
    ('labbench', 'results/final/go/labbench160_web', 'LABBENCH', None),
    ('labbench', 'results/second_model/haiku', 'LABBENCH', None),
    ('variant_retrieval', 'results/final/variant_retrieval_go', 'V', None),
    ('variant_retrieval', 'results/second_model/haiku', 'V', None),
    ('variant_retrieval', 'results/biomcp_variant_or', 'V', None),
    ('variant_batch', 'results/final/variant_batch_go', 'V6_batch', None),
    ('aggregation', 'results/final/complex20_go', 'CX', None),
    ('aggregation_25_steps', 'results/final/complex20_web25', 'CX', None),
    ('paraphrase', 'results/final/paraphrase_go', 'P_', None),
    ('tf_go_same_day_repeat', 'results/final/go/rerun_tfgo_200', 'G100_', None),
    ('provider_replication', 'results/final/or_confirm_300', 'G100_', None),
]

QUESTION_FILES = [
    'anchor_geneturing_900.json', 'labbench_dbqa.json', 'variant_retrieval.json',
    'variant_batch.json', 'complex_tasks.json', 'paraphrase_63.json',
]

FIELDS = ['set', 'run', 'question_id', 'model', 'condition', 'question', 'gold',
          'answer', 'correct', 'tool_calls', 'total_tokens', 'seconds',
          'cost_usd', 'error', 'timestamp']


def _dict(value):
    if isinstance(value, str):
        try:
            return ast.literal_eval(value)
        except Exception:
            return {}
    return value or {}


def questions():
    out = {}
    for name in QUESTION_FILES:
        data = json.load(open(os.path.join(HERE, 'questions', name)))
        for q in data['questions'] if isinstance(data, dict) else data:
            gold = q.get('gold', q.get('accepted'))
            out[q['id']] = (q.get('question', ''),
                            gold if isinstance(gold, str) else json.dumps(gold))
    return out


def main():
    qs = questions()
    rows = []
    for set_name, run, prefix, conds in RUNS:
        for path in sorted(glob.glob(os.path.join(HERE, run, '*.json'))):
            try:
                r = json.load(open(path))
            except Exception:
                continue
            if not isinstance(r, dict) or 'question_id' not in r:
                continue
            qid = r['question_id']
            if prefix and not qid.startswith(prefix):
                continue
            if conds and r.get('condition') not in conds:
                continue
            if set_name == 'variant_retrieval' and qid.startswith('V6_batch'):
                set_name_row = 'variant_batch'
            else:
                set_name_row = set_name
            usage = _dict(r.get('usage'))
            question, gold = qs.get(qid, ('', ''))
            rows.append({
                'set': set_name_row, 'run': run.replace('results/', ''),
                'question_id': qid, 'model': r.get('model'),
                'condition': r.get('condition'), 'question': question, 'gold': gold,
                'answer': r.get('answer') or '', 'correct': int(bool(r.get('correct'))),
                'tool_calls': len(r.get('tool_calls') or []),
                'total_tokens': usage.get('total_tokens', 0),
                'seconds': round(float(r.get('latency_s') or 0), 2),
                'cost_usd': usage.get('cost_usd', 0),
                'error': r.get('error') or '', 'timestamp': r.get('timestamp', ''),
            })
    out = os.path.join(HERE, 'cells.csv')
    with open(out, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f'wrote {out}: {len(rows)} cells')


if __name__ == '__main__':
    main()
