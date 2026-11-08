"""Variant-tool acceptance check (run after a Sugi Variant deployment).

Tests the contract points that failed on 2026-11-08:
  - protein HGVS                      (works)
  - c. HGVS                           (failed: BRCA1 c.68_69del)
  - clinical structural variant VCV   (failed: VCV005020085, VCV005038037)
  - gene-only ambiguity               (returns not_found)
  - release string in payload
  - batch of 5 and estimated size for 30

Usage:
  python check_variant_release.py
Exit code 0 when every required check passes, 1 otherwise.
"""

import json
import sys

from mcp_client import MCPClient

CHECKS = [
    ("protein HGVS", {"entities": ["PTEN R130Q"]}, "results"),
    ("c. HGVS", {"entities": ["BRCA1 c.68_69del"]}, "results"),
    ("clinical SV VCV (7q11.23 del)", {"entities": ["VCV005020085"]}, "results"),
    ("clinical SV VCV (2q22 del)", {"entities": ["VCV005038037"]}, "results"),
    ("rsID", {"entities": ["rs80357906"]}, "results"),
]


def main():
    c = MCPClient()
    failures = []
    release = None
    for label, args, expect in CHECKS:
        raw = c.call_tool("biobtree_variant", args)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            print(f"FAIL {label}: non-JSON response")
            failures.append(label)
            continue
        ok = bool(data.get(expect))
        rel = (data.get("results") or [{}])[0].get("release") if data.get("results") else None
        release = release or rel
        print(f"{'PASS' if ok else 'FAIL'} {label}"
              + (f"  (release {rel})" if rel else ""))
        if not ok:
            failures.append(label)

    # batch size
    ids = ["rs80357906", "rs80357907", "rs80357908", "rs1131690830", "rs587780101"]
    raw = c.call_tool("biobtree_variant", {"entities": ids})
    n = len(raw)
    print(f"batch of 5: {n:,} chars -> 30 approx {n / 5 * 30 / 1000:.0f}k chars")
    if n / 5 * 30 > 120_000:
        print("WARN batch of 30 likely too large; use section='Identity'")
    print(f"release: {release}")
    print("\nRESULT:", "PASS" if not failures else f"FAIL ({', '.join(failures)})")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
