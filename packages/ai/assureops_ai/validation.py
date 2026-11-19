"""Validation before any model output is persisted as a proposal.

Schema compliance proves shape, not truth, so each phase also checks that
quoted spans exist in the sources it was allowed to see, that every referenced
ID exists, and (phase F) that no number or verdict appears that the frozen
facts do not contain. Failures produce `invalid_output` or `unsupported_claims`,
which become review work, never an accepted result.
"""

import re

import jsonschema

from .registry import schema

NUMBER = re.compile(r"(?<![A-Za-z0-9_-])\d+(?:\.\d+)?%?")
FORBIDDEN_VERDICTS = re.compile(r"\b(certif(?:y|ied|ication)|guarantee[sd]?|fully safe|is safe|compliant|compliance approved|no risk)\b", re.I)
NEGATION = re.compile(r"\b(not|no|never|nor|without|isn't|doesn't)\b[^.;]{0,25}$", re.I)


def verdict_claims(text: str) -> list[str]:
    """Certification/safety words that are asserted, not negated ("this is not a certification" is allowed)."""
    return [m.group(0) for m in FORBIDDEN_VERDICTS.finditer(text) if not NEGATION.search(text[:m.start()])]
NUMERIC_TOKEN = re.compile(r"[A-Za-z]*-?\d+(?:[.,]\d+)*")


def nli_signal(premise: str, claim: str, scores: list[dict]) -> dict:
    """Phase D decision rule (D-2): the classifier's top label, except that a claim naming a number or identifier the premise
    does not contain is never read as entailed. Small NLI models largely ignore numbers ("within 6 days" vs "within 36 days"),
    and a false "entailment" is the critical error, so the rule only ever moves a label away from support."""
    best = max(scores, key=lambda x: x.get("score", 0)) if scores else {}
    label, score = str(best.get("label", "")).lower(), float(best.get("score", 0))
    missing = sorted({m.rstrip(".,") for m in NUMERIC_TOKEN.findall(claim)} - {m.rstrip(".,") for m in NUMERIC_TOKEN.findall(premise)})
    if label == "entailment" and missing:
        return {"label": "neutral", "score": score, "guard": f"claim names {', '.join(missing)}, which the premise does not contain"}
    return {"label": label, "score": score, "guard": None}


SECRETISH = re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{8,}|gsk_[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{12,}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,})\b")


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def check_schema(phase: str, output: dict) -> list[str]:
    try:
        jsonschema.validate(output, schema(phase))
        return []
    except jsonschema.ValidationError as exc:
        return [f"schema: {'/'.join(map(str, exc.absolute_path)) or 'output'}: {exc.message}"]


def check_spans(spans: list[dict], sources: dict[str, str]) -> list[str]:
    problems = []
    for span in spans:
        text = sources.get(span["source_id"])
        if text is None:
            problems.append(f"span cites unknown or unauthorized source {span['source_id']}")
        elif _norm(span["quote"]) not in _norm(text):
            problems.append(f"quote not found in {span['source_id']}: {span['quote'][:60]!r}")
    return problems


def validate(phase: str, output: dict, ctx: dict) -> dict:
    """Returns {"status": "valid"|"invalid_output"|"unsupported_claims", "problems": [...]}.

    Blank strings in top-level lists (e.g. a trailing "" after the last hypothesis) are padding, not content: they are
    dropped in place before the schema check, so the caller keeps the cleaned output."""
    if isinstance(output, dict):
        for key, value in output.items():
            if isinstance(value, list):
                output[key] = [v for v in value if not (isinstance(v, str) and not v.strip())]
    problems = check_schema(phase, output)
    if problems:
        return {"status": "invalid_output", "problems": problems}
    unsupported = []
    if phase == "A":
        for req in output["requirements"]:
            if not req["spans"]:
                unsupported.append(f"requirement without a supporting quote: {req['statement'][:60]!r}")
            unsupported += check_spans(req["spans"], ctx["sources"])
    elif phase == "B":
        tests, comps = set(ctx["test_ids"]), set(ctx["component_ids"])
        for link in output["links"]:
            if link["test_id"] not in tests:
                unsupported.append(f"unknown test {link['test_id']}")
            if link["component_id"] not in comps:
                unsupported.append(f"unknown component {link['component_id']}")
    elif phase == "C":
        unsupported += [problem for test in output["tests"] if (problem := c_test_problem(test, ctx))]
    elif phase == "E":
        unsupported += check_spans(output["spans"], ctx["sources"])
        unsupported += [f"unknown test {t}" for t in output["retest_suggestions"] if t not in set(ctx["test_ids"])]
    elif phase == "F":
        facts = ctx["facts"]
        for section in output["sections"]:
            missing = [f for f in section["fact_ids"] if f not in facts]
            if missing:
                unsupported.append(f"section {section['heading']!r} cites unknown facts {missing}")
                continue
            allowed = set(NUMBER.findall(" ".join(facts[f] for f in section["fact_ids"])))
            stray = sorted(set(NUMBER.findall(section["text"])) - allowed)
            if stray:
                unsupported.append(f"section {section['heading']!r} states numbers not in its facts: {stray}")
            if verdict_claims(section["text"]):
                unsupported.append(f"section {section['heading']!r} makes a certification/safety claim")
    if unsupported:
        return {"status": "unsupported_claims", "problems": unsupported}
    return {"status": "valid", "problems": []}


def c_test_problem(test: dict, ctx: dict) -> str | None:
    """Why one proposed phase C test cannot become a runnable test once its declared facts are added, or None."""
    from assureops_connectors import templates

    if ctx.get("templates") and test["template"] not in ctx["templates"]:
        return f"{test['name']}: template {test['template']} was not offered for proposals"
    try:
        templates.validate_proposal(test["template"], test["args"])  # declared facts may be left for the developer
        if test["template"] == "scenario":
            templates.validate_args("scenario", test["args"])  # a scenario declares everything itself: it must be runnable as written
    except templates.TemplateError as exc:
        return f"{test['name']}: {exc}"
    used = {test["args"]["actor"]} if "actor" in test["args"] else set(test["args"].get("actors") or [])  # named templates: one actor argument
    if used - set(ctx["actors"]) - {"anonymous", "invalid"}:
        return f"{test['name']}: undeclared actors {sorted(used - set(ctx['actors']))}"
    return None


def keep_runnable_c_tests(output: dict, ctx: dict) -> tuple[dict, list[str]]:
    """Serving path for phase C: tests that cannot run are removed and listed, so one malformed test does not void the others.

    Removed tests never reach a proposal; the reviewer sees each with its reason. Qualification still scores the whole output."""
    kept, dropped = [], []
    for test in output.get("tests", []):
        problem = c_test_problem(test, ctx)
        (dropped.append(problem) if problem else kept.append(test))
    if not dropped or not kept:
        return output, []
    notes = [f"removed by validation: {d}"[:300] for d in dropped]
    return {**output, "tests": kept, "unknowns": [*output.get("unknowns", []), *notes][:12]}, dropped


def minimize(text: str) -> str:
    """Redaction before any external dispatch: secrets and e-mail addresses are masked."""
    return SECRETISH.sub("[redacted]", text)
