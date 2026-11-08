"""Answer scoring for the BioBTree benchmark.

`answer_type` in each question decides the scorer:

  exact    - gold string (or list of accepted strings) must appear as a
             word-bounded token sequence
  integer  - gold integer must appear as a standalone number
  enum     - gold must match one of the accepted values (normalized)
  boolean  - yes/no detection
  chromosome - chromosome token (handles "17p13.1" -> 17)
  abstain  - correct when the answer says the data is not available
  keyword  - legacy must_mention / must_mention_any scoring (Track A)
  rubric   - not auto-scored (score stays None; manual review)
"""

import re

_PUNCT = re.compile(r"[^\w\s.+-]")
_WS = re.compile(r"\s+")
LETTERS = ["A", "B", "C", "D"]


def normalize(text):
    if text is None:
        return ""
    text = str(text).lower().replace("_", " ")
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def _contains(needle, haystack):
    """Word-bounded containment on normalized text."""
    n = normalize(needle)
    h = normalize(haystack)
    if not n:
        return False
    # Numbers and short tokens: require word boundaries.
    return re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", h) is not None


def _integers(text):
    return [int(x) for x in re.findall(r"(?<!\d)(\d{1,9})(?!\d)", str(text))]


def _yes_no(text):
    t = normalize(text)
    yes = re.search(r"\b(yes|true|associated|present|found|does|is)\b", t)
    no = re.search(r"\b(no|not|false|absent|none|unrelated|isn t|doesn t|not associated)\b", t)
    # "no" wins if both appear (conservative).
    if no and not re.search(r"\bnot only\b", t):
        return False
    if yes:
        return True
    return None


def score(question, answer):
    """Return {score, correct, detail} for one answer."""
    qtype = question.get("answer_type", "keyword")
    gt = question.get("ground_truth", {}) or {}
    gold = question.get("gold", gt.get("gold"))
    accepted = question.get("accepted") or gt.get("accepted") or []

    if qtype == "rubric":
        return {"score": None, "correct": None, "detail": "manual review"}

    if qtype == "exact":
        candidates = []
        if isinstance(gold, list):
            candidates = gold
        elif gold is not None:
            candidates = [gold]
        candidates = list(candidates) + list(accepted)
        hit = next((c for c in candidates if _contains(c, answer)), None)
        return {
            "score": 1.0 if hit is not None else 0.0,
            "correct": hit is not None,
            "detail": {"matched": hit, "gold": gold},
        }

    if qtype == "integer":
        try:
            target = int(gold)
        except (TypeError, ValueError):
            return {"score": 0.0, "correct": False, "detail": "bad gold"}
        found = _integers(answer)
        ok = target in found
        return {
            "score": 1.0 if ok else 0.0,
            "correct": ok,
            "detail": {"gold": target, "numbers_in_answer": found[:20]},
        }

    if qtype == "enum":
        candidates = list(accepted) + ([gold] if gold is not None else [])
        hit = next((c for c in candidates if _contains(c, answer)), None)
        return {
            "score": 1.0 if hit is not None else 0.0,
            "correct": hit is not None,
            "detail": {"matched": hit, "gold": gold},
        }

    if qtype == "boolean":
        target = bool(gold)
        got = _yes_no(answer)
        ok = got is not None and got == target
        return {
            "score": 1.0 if ok else 0.0,
            "correct": ok,
            "detail": {"gold": target, "detected": got},
        }

    if qtype == "chromosome":
        # Prefer explicit chromosome phrasing over "the first number in the text":
        # answers often contain gene names (RNU6-42P) and coordinates (18:12,400,412)
        # that would otherwise be mistaken for the chromosome.
        target = str(gold).upper()
        text = str(answer)
        patterns = [
            rf"\b(?:chromosome|chr)\s*{re.escape(target)}\b",
            rf"\b{re.escape(target)}[pq]\d",
            rf"\bchr{re.escape(target)}\b",
        ]
        for pat in patterns:
            if re.search(pat, text, re.I):
                return {
                    "score": 1.0, "correct": True,
                    "detail": {"gold": target, "detected": target, "via": pat},
                }
        # Table row: "| Chromosome | 18 |"
        if re.search(rf"chromosome\s*[|/]?\s*{re.escape(target)}\b", text, re.I):
            return {
                "score": 1.0, "correct": True,
                "detail": {"gold": target, "detected": target, "via": "table"},
            }
        # Fall back: if the answer mentions exactly one chromosome-like token, use it.
        toks = re.findall(
            r"\b(?:chr(?:omosome)?\s*)?([0-9]{1,2}|X|Y|MT)(?=[pq]?\d|\b)", text, re.I
        )
        uniq = {t.upper() for t in toks}
        got = next(iter(uniq)) if len(uniq) == 1 else None
        ok = got == target
        return {
            "score": 1.0 if ok else 0.0,
            "correct": ok,
            "detail": {"gold": target, "detected": got, "candidates": sorted(uniq)[:10]},
        }

    if qtype == "mcq":
        # gold is the option letter; gold_text is the option content.
        letter = str(gold or "").strip().upper()
        options = question.get("options") or []
        gold_text = question.get("gold_text")
        text = str(answer or "")
        letter_hit = any(
            re.search(p, text)
            for p in (
                rf"(?i)\banswer\s*(?:is|:|\-)?\s*\(?{re.escape(letter)}\)?\b",
                rf"(?i)^\s*\(?{re.escape(letter)}\)?\s*[\.\)\:\-]",
                rf"(?i)^\s*\(?{re.escape(letter)}\)?\s*$",
                rf"(?i)\boption\s+{re.escape(letter)}\b",
                rf"(?i)\(\s*{re.escape(letter)}\s*\)",
                rf"(?i)\*\*\(?{re.escape(letter)}\)?(?:\s*[\.\)\:])?\*\*",
            )
        )
        text_hit = bool(gold_text and _contains(gold_text, text))
        other_hit = next(
            (
                o
                for i, o in enumerate(options)
                if LETTERS[i] != letter and _contains(o, text)
            ),
            None,
        )
        ok = letter_hit or text_hit
        return {
            "score": 1.0 if ok else 0.0,
            "correct": ok,
            "detail": {
                "gold": letter,
                "gold_text": gold_text,
                "letter_hit": letter_hit,
                "text_hit": text_hit,
                "other_option": other_hit,
            },
        }

    if qtype == "all_of":
        candidates = list(accepted) + ([gold] if isinstance(gold, str) else list(gold or []))
        hits = [c for c in candidates if _contains(c, answer)]
        missing = [c for c in candidates if c not in hits]
        return {
            "score": 1.0 if not missing else 0.0,
            "correct": not missing,
            "detail": {"matched": hits, "missing": missing, "gold": gold},
        }

    if qtype == "coverage":
        candidates = list(accepted) + ([gold] if isinstance(gold, str) else list(gold or []))
        if not candidates:
            return {"score": 0.0, "correct": False, "detail": "no gold"}
        hits = [c for c in candidates if _contains(c, answer)]
        frac = len(hits) / len(candidates)
        threshold = question.get("threshold", 0.9)
        return {
            "score": frac,
            "correct": frac >= threshold,
            "detail": {"coverage": frac, "missing": [c for c in candidates if c not in hits]},
        }

    if qtype == "abstain":
        # Correct behaviour: say the data is not available rather than invent it.
        t = normalize(answer)
        markers = (
            "not found", "no data", "not available", "not in biobtree",
            "not covered", "no information", "unknown", "cannot find",
            "could not find", "not present", "no record", "does not exist",
            "unable to find", "no such", "not a variant", "is a gene",
            "gene, not a variant", "no single", "not a single variant",
            "does not have a single", "cannot be determined", "not a valid",
        )
        ok = any(m in t for m in markers)
        return {
            "score": 1.0 if ok else 0.0,
            "correct": ok,
            "detail": {"abstained": ok},
        }

    # keyword (legacy Track A logic)
    must = gt.get("must_mention", [])
    must_any = gt.get("must_mention_any", [])
    tool_only = gt.get("tool_only_terms", [])

    must_found = [t for t in must if _contains(t, answer)]
    any_found = [t for t in must_any if _contains(t, answer)]
    evidence_found = [t for t in tool_only if _contains(t, answer)]

    must_score = len(must_found) / len(must) if must else 1.0
    any_score = 1.0 if any_found or not must_any else 0.0
    evidence_score = 1.0 if evidence_found or not tool_only else 0.0

    parts = [must_score, any_score] + ([evidence_score] if tool_only else [])
    final = sum(parts) / len(parts)
    return {
        "score": round(final, 3),
        "correct": final >= 0.999,
        "detail": {
            "must_found": must_found,
            "must_missing": [t for t in must if t not in must_found],
            "any_found": any_found,
            "evidence_found": evidence_found,
        },
    }
