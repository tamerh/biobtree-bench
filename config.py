"""Benchmark configuration (env-driven, stdlib only)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
QUESTIONS_DIR = BASE_DIR / "questions"
RESULTS_DIR = BASE_DIR / "results"
TRANSCRIPTS_DIR = RESULTS_DIR / "transcripts"

# MCP server (JSON-RPC over HTTP)
MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8000/mcp")
MCP_TIMEOUT = float(os.environ.get("MCP_TIMEOUT", "120"))

# LLM endpoint (OpenAI-compatible)
OPENROUTER_URL = os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
# Required by the OpenCode Go inference endpoint; harmless elsewhere.
OPENCODE_SESSION = os.environ.get("OPENCODE_SESSION", "")
# DeepSeek thinking mode via OpenRouter requires the previous reasoning_content
# to be echoed back on tool-call continuations. Harmless to leave off elsewhere.
PASS_REASONING_BACK = ("openrouter.ai" in OPENROUTER_URL)

# Defaults recorded in every run
DEFAULT_MODELS = [
    "anthropic/claude-sonnet-5.5",
    "openai/gpt-5.1",
    "anthropic/claude-haiku-5.5",
]
DEFAULT_CONDITIONS = ["no_tools", "mcp"]

TEMPERATURE = float(os.environ.get("BENCH_TEMPERATURE", "0"))
MAX_TOKENS = int(os.environ.get("BENCH_MAX_TOKENS", "16384"))
MAX_ITERATIONS = int(os.environ.get("BENCH_MAX_ITERATIONS", "10"))

# Per-tool-result cap handed back to the model (chars). The MCP server already
# truncates structurally at 50k (valid JSON + `dropped_inputs`), so this is only
# a guard for non-JSON payloads (e.g. TOOL ERROR strings). Keep it at the server
# limit: cutting valid JSON here would reintroduce the unparseable-result bug.
TOOL_RESULT_MAX_CHARS = int(os.environ.get("BENCH_TOOL_RESULT_MAX_CHARS", "50000"))

# Which MCP tools each condition may use.
# `mcp` is the real system: all tools registered, the model chooses.
# The forced subsets are ablations, not part of the main claim.
CONDITION_TOOLS = {
    "no_tools": [],
    "mcp": [
        "biobtree_search",
        "biobtree_map",
        "biobtree_entry",
        "biobtree_atlas",
        "biobtree_enrich",
    ],
    "ablation_raw": ["biobtree_search", "biobtree_map", "biobtree_entry"],
    "ablation_atlas": ["biobtree_atlas"],
    # General web baseline: no BioBTree, no curated database. Same model and
    # iteration budget, so the comparison is "web agent vs MCP agent".
    "web": ["web_search", "web_fetch"],
    # Tool-surface dilution test: the standard MCP surface plus the variant
    # evidence tool. Used only for the dilution/tool-selection probe, not for
    # the primary tables (those are frozen on the 5-tool surface).
    "mcp_variant": [
        "biobtree_search",
        "biobtree_map",
        "biobtree_entry",
        "biobtree_atlas",
        "biobtree_enrich",
        "biobtree_variant",
    ],
}

SYSTEM_PROMPT = (
    "You are a biomedical research assistant. Answer the user's question as "
    "accurately and completely as possible. Use the available tools when they "
    "help you find verified identifiers, exact counts, or data the model may "
    "not know. If the tools do not contain the answer, say so explicitly rather "
    "than guessing. Cite identifiers (gene symbols, accessions, ontology IDs) "
    "where relevant."
)
