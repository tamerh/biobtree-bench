"""Generate the short-answer (Track B) question set from BioBTree.

Every question is derived mechanically from a BioBTree record, so the gold
answer is exact and reproducible. The seed lists are fixed and committed; the
generator is deterministic (no random sampling at run time).

Usage:
  python generate_track_b.py --out questions/track_b.json
  python generate_track_b.py --types chromosome top_tissue --max-per-type 5 --check
"""

import argparse
import json
import sys

from mcp_client import MCPClient, MCPError

# Fixed seed lists (documented in the paper's supplementary). Keep sorted.
GENES = [
    "TP53", "BRCA1", "BRCA2", "EGFR", "KRAS", "PTEN", "APOE", "SCN9A", "CFTR",
    "DMD", "HBB", "F8", "G6PD", "INS", "LEPR", "MC4R", "MYH7", "LMNA", "TTN",
    "COL1A1", "FBN1", "NF1", "RB1", "VHL", "WT1", "MEN1", "RET", "MET", "ALK",
    "BRAF", "PIK3CA", "AKT1", "MTOR", "JAK2", "FLT3", "KIT", "PDGFRA", "ABL1",
    "SRC", "STAT3", "MYC", "CDKN2A", "ATM", "CHEK2", "PALB2", "RAD51C", "MLH1",
    "MSH2", "MSH6", "PMS2", "APC", "MUTYH", "CDH1", "STK11", "TSC1", "TSC2",
    "NF2", "PRKAR1A", "GLA", "GAA", "IDUA", "HEXA", "PAH", "GALT", "OTC",
]

DISEASES = [
    "alkaptonuria", "cystic fibrosis", "phenylketonuria", "Huntington disease",
    "Duchenne muscular dystrophy", "sickle cell disease", "beta thalassemia",
    "Marfan syndrome", "neurofibromatosis type 1", "tuberous sclerosis",
    "familial hypercholesterolemia", "hereditary breast ovarian cancer",
    "Lynch syndrome", "von Hippel-Lindau disease", "retinoblastoma",
    "achondroplasia", "Gaucher disease", "Pompe disease", "Fabry disease",
    "Wilson disease", "hemochromatosis", "polycystic kidney disease",
    "amyotrophic lateral sclerosis", "Parkinson disease", "Alzheimer disease",
    "Niemann-Pick disease", "Hurler syndrome", "maple syrup urine disease",
    "homocystinuria", "retinitis pigmentosa", "epidermolysis bullosa",
    "spinal muscular atrophy", "neurofibromatosis type 2",
    "Li-Fraumeni syndrome", "Fanconi anemia", "ataxia telangiectasia",
    "primary ciliary dyskinesia", "hereditary spherocytosis",
    "Friedreich ataxia", "Alport syndrome", "Charcot-Marie-Tooth disease",
]

CLINGEN_CLASSES = [
    "Definitive", "Strong", "Moderate", "Limited", "Disputed", "Refuted",
    "No Known Disease Relationship",
]


def _json(text):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _targets(payload):
    if not payload:
        return []
    out = []
    for m in payload.get("mappings") or []:
        out.extend(m.get("targets") or [])
    return out


def ensembl_id(mcp, symbol):
    p = _json(mcp.call_tool("biobtree_map", {"terms": symbol, "chain": ">>hgnc>>ensembl"}))
    for t in _targets(p):
        if t.startswith("ENSG"):
            return t.split("|")[0]
    return None


def q_chromosome(mcp, symbol):
    ensg = ensembl_id(mcp, symbol)
    if not ensg:
        return None
    e = _json(mcp.call_tool("biobtree_entry", {"identifier": ensg, "dataset": "ensembl"}))
    try:
        chrom = e["Attributes"]["Ensembl"]["seq_region"]
    except (KeyError, TypeError):
        return None
    if not chrom:
        return None
    return {
        "question": f"On which human chromosome is the gene {symbol} located? "
                    f"Answer with the chromosome number or letter.",
        "answer_type": "chromosome",
        "gold": str(chrom),
        "source": {"dataset": "ensembl", "identifier": ensg, "field": "seq_region"},
    }


def q_top_tissue(mcp, symbol):
    ensg = ensembl_id(mcp, symbol)
    if not ensg:
        return None
    b = _json(mcp.call_tool("biobtree_entry", {"identifier": ensg, "dataset": "bgee"}))
    try:
        conds = b["Attributes"]["Bgee"]["top_conditions"]
    except (KeyError, TypeError):
        return None
    parsed = []
    for c in conds:
        parts = c.split("|")
        if len(parts) >= 4:
            try:
                parsed.append((parts[1], float(parts[3]), parts[0]))
            except ValueError:
                continue
    if not parsed:
        return None
    tissue, score, tissue_id = max(parsed, key=lambda x: x[1])
    return {
        "question": f"According to Bgee, in which tissue does {symbol} have its "
                    f"highest expression score?",
        "answer_type": "exact",
        "gold": tissue,
        "accepted": [tissue_id],
        "source": {"dataset": "bgee", "identifier": ensg, "score": score,
                   "tissue_id": tissue_id},
    }


def _uncapped_total(payload):
    """stats.total is a page size (capped at 100); only trust it when there is
    no next page."""
    if not payload:
        return None
    if (payload.get("pagination") or {}).get("has_next"):
        return None
    n = (payload.get("stats") or {}).get("total")
    return int(n) if n else None


def q_reactome_count(mcp, symbol):
    p = _json(mcp.call_tool("biobtree_map",
                            {"terms": symbol, "chain": ">>hgnc>>uniprot>>reactome"}))
    n = _uncapped_total(p)
    if not n:
        return None
    return {
        "question": f"How many Reactome pathways involve the protein encoded by {symbol}?",
        "answer_type": "integer",
        "gold": n,
        "source": {"chain": ">>hgnc>>uniprot>>reactome"},
    }


def q_trials_count(mcp, disease):
    p = _json(mcp.call_tool("biobtree_map",
                            {"terms": disease, "chain": ">>mondo>>clinical_trials"}))
    n = _uncapped_total(p)
    if not n:
        return None
    return {
        "question": f"How many clinical trials are registered for {disease}?",
        "answer_type": "integer",
        "gold": n,
        "source": {"chain": ">>mondo>>clinical_trials"},
    }


def q_hgnc_id(mcp, symbol):
    p = _json(mcp.call_tool("biobtree_search", {"terms": symbol, "dataset": "hgnc"}))
    if not p:
        return None
    for row in p.get("data", []):
        if row.startswith("HGNC:"):
            return {
                "question": f"What is the HGNC identifier for the gene {symbol}?",
                "answer_type": "exact",
                "gold": row.split("|")[0],
                "source": {"dataset": "hgnc"},
            }
    return None


def q_clingen(mcp, symbol):
    p = _json(mcp.call_tool("biobtree_map",
                            {"terms": symbol, "chain": ">>hgnc>>clingen_gene_validity"}))
    for t in _targets(p):
        parts = t.split("|")
        if len(parts) >= 4 and parts[3]:
            return {
                "question": f"What is the ClinGen gene-disease validity classification "
                            f"for {symbol} in {parts[2]}?",
                "answer_type": "enum",
                "gold": parts[3],
                "accepted": CLINGEN_CLASSES,
                "source": {"dataset": "clingen_gene_validity", "disease": parts[2]},
            }
    return None


GENE_TYPES = {
    "chromosome": q_chromosome,
    "top_tissue": q_top_tissue,
    "reactome_count": q_reactome_count,
    "hgnc_id": q_hgnc_id,
    "clingen": q_clingen,
}
DISEASE_TYPES = {"trials_count": q_trials_count}


def build(mcp, types, max_per_type):
    questions = []
    counters = {t: 0 for t in types}

    def add(qtype, q, key):
        if q is None or counters[qtype] >= max_per_type:
            return
        qid = f"B_{qtype}_{key}"
        questions.append({
            "id": qid,
            "track": "track_b",
            "category": qtype,
            **q,
        })
        counters[qtype] += 1

    for qtype in types:
        if qtype in GENE_TYPES:
            for gene in GENES:
                if counters[qtype] >= max_per_type:
                    break
                try:
                    add(qtype, GENE_TYPES[qtype](mcp, gene), gene)
                except MCPError as e:
                    print(f"  skip {qtype}/{gene}: {e}", file=sys.stderr)
        elif qtype in DISEASE_TYPES:
            for disease in DISEASES:
                if counters[qtype] >= max_per_type:
                    break
                try:
                    add(qtype, DISEASE_TYPES[qtype](mcp, disease), disease.replace(" ", "_"))
                except MCPError as e:
                    print(f"  skip {qtype}/{disease}: {e}", file=sys.stderr)
    return questions


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="questions/track_b.json")
    ap.add_argument("--types", nargs="+",
                    default=list(GENE_TYPES) + list(DISEASE_TYPES))
    ap.add_argument("--max-per-type", type=int, default=20)
    ap.add_argument("--check", action="store_true", help="print and do not write")
    args = ap.parse_args(argv)

    mcp = MCPClient()
    questions = build(mcp, args.types, args.max_per_type)

    print(f"generated {len(questions)} questions "
          f"({len(args.types)} types x <= {args.max_per_type})")
    for q in questions[:12]:
        print(f"  {q['id']:<42} gold={q['gold']!r}")

    if args.check:
        return
    with open(args.out, "w") as f:
        json.dump({"questions": questions}, f, indent=2, ensure_ascii=False)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
