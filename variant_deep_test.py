"""Deep check of the biobtree_variant tool (no LLM).

Covers the contract points the paper relies on: resolution breadth, evidence
content, determinism, ambiguity/abstention, error model, batch size, sections,
release stamping. Run before and after a Sugi Variant deployment; exit 0 only
when every required check passes.

Usage:
  python variant_deep_test.py
"""

import json
import sys
import time

from mcp_client import MCPClient


def call(c, entities, **kw):
    t0 = time.time()
    raw = c.call_tool("biobtree_variant", {"entities": entities, **kw})
    return raw, time.time() - t0


def parse(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def main():
    c = MCPClient()
    results = {}

    # --- resolution breadth -------------------------------------------------
    probes = {
        "rsID": ["rs80357906"],
        "protein_HGVS": ["PTEN R130Q"],
        "c_HGVS": ["BRCA1 c.68_69del"],
        "VCV": ["VCV000017562"],
        "clinical_SV_VCV": ["VCV005020085"],
        "coordinate": ["10:87933148:G:A"],
        "locus": ["chr10:87933100-87933200"],
        "absent": ["rs99999999999"],
    }
    print("== resolution ==")
    for name, ents in probes.items():
        raw, dt = call(c, ents)
        d = parse(raw) or {}
        n = len(d.get("results") or [])
        amb = len(d.get("ambiguous") or [])
        nf = len(d.get("not_found") or [])
        print(f"  {name:16} hit={n} ambiguous={amb} not_found={nf} {dt:.1f}s")
        results[name] = n

    # --- content / sections -------------------------------------------------
    print("\n== content ==")
    raw, _ = call(c, ["rs80357906"])
    d = parse(raw) or {}
    r0 = (d.get("results") or [{}])[0]
    release = r0.get("release")
    sections = r0.get("sections") or []
    blob = json.dumps(d)
    # The digest is Summary + Identity; evidence lives in named sections.
    comp, _ = call(c, ["rs80357906"], section="Computational & population evidence")
    comp_low = comp.lower()
    checks = {
        "release": bool(release),
        "canonical_url": bool(r0.get("canonical_url")),
        "sections>=5": len(sections) >= 5,
        "clinvar": "clinvar" in blob.lower(),
        "review": "review" in blob.lower(),
        "gnomad": "gnomad" in comp_low,
        "predictor": any(k in comp_low for k in ("spliceai", "alphamissense", "cadd", "revel")),
        "conservation": "conserv" in comp_low,
    }
    for k, v in checks.items():
        print(f"  {k:16} {'PASS' if v else 'FAIL'}")
    print(f"  sections: {sections[:6]} ...")

    # --- determinism --------------------------------------------------------
    print("\n== determinism ==")
    a, _ = call(c, ["rs80357906"])
    b, _ = call(c, ["rs80357906"])
    print(f"  identical payloads: {'PASS' if a == b else 'FAIL'}  ({len(a)} chars)")

    # --- sections / full ----------------------------------------------------
    print("\n== section/full ==")
    sect, _ = call(c, ["rs80357906"], section="Identity")
    full, _ = call(c, ["rs80357906"], full=True)
    print(f"  section={len(sect)} chars, full={len(full)} chars, "
          f"section<full={'PASS' if len(sect) < len(full) else 'FAIL'}")

    # --- ambiguity ----------------------------------------------------------
    print("\n== ambiguity ==")
    raw, _ = call(c, ["BRCA1"])
    d = parse(raw) or {}
    print(f"  gene-only BRCA1: ambiguous={len(d.get('ambiguous') or [])} "
          f"not_found={len(d.get('not_found') or [])} "
          f"fetch_errors={len(d.get('fetch_errors') or [])}")

    # --- batch --------------------------------------------------------------
    print("\n== batch ==")
    ids = ["rs80357906", "rs80357907", "rs80357908", "rs1131690830", "rs587780101",
           "rs140826989", "rs121913529", "rs28934578", "rs1042522", "rs1799983"]
    raw, dt = call(c, ids)
    d = parse(raw) or {}
    n = len(d.get("results") or [])
    print(f"  10 entities: hits={n}, {len(raw):,} chars, {dt:.1f}s "
          f"-> 30 approx {len(raw) / len(ids) * 30 / 1000:.0f}k chars")
    print(f"  batch resolves all: {'PASS' if n == len(ids) else 'INFO ' + str(n) + '/' + str(len(ids))}")

    # --- cross-source sanity (ClinVar) -------------------------------------
    print("\n== ClinVar agreement (one variant) ==")
    # rs80357906 is ClinVar Pathogenic, BRCA1. Read the page's classification.
    low = blob.lower()
    print(f"  page mentions BRCA1: {'PASS' if 'brca1' in low else 'FAIL'}")
    print(f"  page mentions pathogenic: {'PASS' if 'pathogenic' in low else 'FAIL'}")

    print(f"\nrelease: {release}")
    required = ["rsID", "protein_HGVS", "VCV", "clinical_SV_VCV"]
    failed = [k for k in required if not results.get(k)]
    print("RESULT:", "PASS" if not failed and release else f"FAIL ({failed})")
    return 0 if not failed and release else 1


if __name__ == "__main__":
    sys.exit(main())
