# biobtree-bench

Benchmark harness, question sets and per-question results for the evaluation of
[BioBTree](https://github.com/tamerh/biobtree) as a tool set for large language
models (LLMs). Each condition gives the same LLM a different set of tools (none,
the BioBTree MCP tools, web search, or a domain-specific MCP server), and every
condition answers the same questions.

## Contents

```
cells.csv            every result cell used in the paper (9,391 rows)
export_cells.py      regenerates cells.csv from the raw run folders
questions/           question sets (JSON)
runner.py            agent loop: one LLM, one condition, one question per cell
config.py            endpoints, protocol settings and the tools of each condition
mcp_client.py        JSON-RPC client for MCP servers
web_client.py        search and page-fetch tools for the web-search condition
llm_client.py        OpenAI-compatible chat client
scoring.py           automatic scoring against the gold answers
analyze.py, compare_runs.py, audit_scoring.py   analysis helpers
```

## Question sets used in the paper

| file | questions | content |
|---|---:|---|
| `anchor_geneturing_900.json` | 900 | GeneTuring, the nine database-lookup modules, 100 each |
| `labbench_dbqa.json` | 160 | LAB-Bench DbQA, four subtasks |
| `variant_retrieval.json` | 86 | variant records (clinical significance, frequency, consequence) |
| `variant_batch.json` | 1 | one table of 30 variants in a single answer |
| `complex_tasks.json` | 20 | aggregation: counts and sets across sources |
| `paraphrase_63.json` | 63 | reworded anchor questions (paraphrase control) |
| `anchor_tfgo_200.json` | 200 | TF-regulation and gene-ontology repeat |
| `anchor_or_confirm_300.json` | 300 | three modules on a second inference provider |

The other files in `questions/` are smoke tests and probes used during
development.

## Conditions

| condition | tools |
|---|---|
| `no_tools` | none |
| `mcp` | the five BioBTree MCP tools (search, map, entry, atlas, enrich) |
| `mcp_variant` | the same, plus the BioBTree `variant` tool |
| `web` | web search and page fetch (`web_client.py`) |
| `ot_mcp` | the Open Targets Platform MCP server |
| `biomcp` | BioMCP |

The remaining conditions in `config.py` are tool ablations. Tool schemas are
fetched from each MCP server at run time, so a run always tests the live
interface.

## Results

`cells.csv` has one row per (question, model, condition) with the columns `set`,
`run`, `question_id`, `model`, `condition`, `question`, `gold`, `answer`,
`correct`, `tool_calls`, `total_tokens`, `seconds`, `cost_usd`, `error` and
`timestamp`. Cost is the provider's list price per question, including discounts
for cached input; the tools themselves incurred no charge.

The raw run folders (answers, tool calls and full transcripts, about 600 MB) are
not in git. `python3 export_cells.py` rebuilds `cells.csv` from them.

## Running

No third-party Python packages are needed (standard library only).

```bash
export OPENROUTER_API_KEY=...            # or OPENROUTER_URL for another
                                         # OpenAI-compatible endpoint
export MCP_URL=https://sugi.bio/biobtree/mcp

# dry run: show what would be sent, no LLM calls
python3 runner.py --questions questions/anchor_geneturing_900.json --limit 2 --dry-run

# protocol of the paper: temperature 0, 16k output tokens, 15 steps
python3 runner.py --questions questions/anchor_geneturing_900.json \
  --models <model> --conditions no_tools mcp web --max-iterations 15
```

Each cell is written as one JSON file under `results/`, with a full transcript
under `results/transcripts/`. Temperature and output length are set with
`BENCH_TEMPERATURE` and `BENCH_MAX_TOKENS`.

## Scoring

Each question carries an `answer_type`: `exact` (normalised string match,
word-boundary aware), `integer`, `enum`, `boolean` or `keyword`. Scoring is
automatic; see the paper's Limitations for the known sources of scoring error
(outdated gold answers, questions with several valid answers and hyphenation).
