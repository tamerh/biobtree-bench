# Benchmark package (independent of the biobtree repo)

This is the paper's evaluation harness. It lives here, not in `/data/biobtree`,
so it can evolve without touching the production code.

It talks to the running BioBTree MCP server over JSON-RPC and to any
OpenAI-compatible LLM endpoint (OpenRouter by default). It does **not** use the
server's `/chat` endpoint (that is disabled in production and couples the
benchmark to the server's prompt/tool loop).

## Layout

```
benchmark/
├── config.py            # env-driven settings
├── mcp_client.py        # JSON-RPC client for the MCP server
├── llm_client.py        # OpenAI-compatible chat client
├── scoring.py           # exact / integer / enum / boolean / keyword scoring
├── runner.py            # the three-condition agent loop
├── generate_track_b.py  # build short-answer questions from BioBTree
├── analyze.py           # paired table, McNemar, CSV export
├── questions/
│   ├── track_a.json     # realistic multi-hop (hand-curated)
│   ├── track_b.json     # short-answer (generated)
│   └── negative.json    # not-in-BioBTree controls
└── results/             # run output (gitignored)
```

## Setup

```bash
export OPENROUTER_API_KEY=...        # only needed to run the LLM
export MCP_URL=http://127.0.0.1:8000/mcp
```

No third-party Python packages are required (stdlib only).

## Commands

```bash
# 1. Check the MCP is reachable and list its tools
python mcp_client.py

# 2. Build the short-answer question set (free; uses only the MCP)
python generate_track_b.py --out questions/track_b.json

# 3. Dry run: print what would be sent, no LLM calls
python runner.py --questions questions/track_b.json --limit 2 --dry-run

# 4. Real run (costs API budget)
python runner.py --questions questions/track_b.json \
  --models anthropic/claude-sonnet-5.5 openai/gpt-5.1 anthropic/claude-haiku-5.5 \
  --conditions no_tools raw_tools atlas

# 5. Analysis
python analyze.py --results results/ --csv results/paired.csv
```

## Conditions

| condition | tools exposed |
|---|---|
| `no_tools` | none |
| `raw_tools` | `biobtree_search`, `biobtree_map`, `biobtree_entry` |
| `atlas` | `biobtree_atlas` |

Tool schemas are fetched from the MCP server at run time, so the benchmark
always tests the real interface.

## What each run records

One JSON per (question, model, condition) under `results/`, plus a full
transcript under `results/transcripts/`:

- question id, track, model, condition, timestamp
- answer, iterations, tool calls (name, args, result size, full result)
- token usage (prompt/completion/total), latency
- score + scoring detail
- run config (MCP URL, max iterations, temperature, BioBTree version if exposed)

## Scoring

`questions/*.json` carry `answer_type`:

- `exact` — normalized string match (word-boundary aware)
- `integer` — gold integer must appear as a standalone number
- `enum` — gold must match one of the accepted values
- `boolean` — yes/no detection
- `keyword` — the old `must_mention` / `must_mention_any` logic (Track A)
- `rubric` — not auto-scored; `score` stays null for manual review

## Notes

- `temperature=0`, `max_iterations=10` by default. Both are recorded per run.
- Results are gitignored; commit the question sets and the analysis, not the
  raw transcripts.
- The old harness in `/data/biobtree/mcp_srv/benchmark/` is the historical
  record; this package supersedes it for the paper.
