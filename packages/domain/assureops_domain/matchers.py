"""Small, side-effect-free JSON path lookup and comparison operators.

Shared by the scenario test engine and runtime-event rules so a profile states
expectations as data. No expression evaluation, no code from profiles.
"""

import re

MISSING = object()

OPERATORS = (
    "eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "exists", "absent", "truthy", "falsy",
    "contains", "not_contains", "contains_any", "contains_none", "matches", "not_matches",
    "len_eq", "len_gte", "len_lte", "count_where", "all_eq", "subset_of", "strictly_increasing",
)


def lookup(value, path: str):
    """Dotted path with integer indexes and `*` for every list element: `body.items.0.id`, `items.*.id`."""
    if path in ("", "$"):
        return value
    current = value
    parts = path.split(".")
    for i, part in enumerate(parts):
        if part == "*":
            if not isinstance(current, list):
                return MISSING
            rest = ".".join(parts[i + 1:])
            return [lookup(item, rest) for item in current]
        if isinstance(current, dict):
            current = current.get(part, MISSING)
        elif isinstance(current, list) and part.lstrip("-").isdigit():
            idx = int(part)
            current = current[idx] if -len(current) <= idx < len(current) else MISSING
        else:
            return MISSING
        if current is MISSING:
            return MISSING
    return current


def _text(value) -> str:
    if value is MISSING or value is None:
        return ""
    if isinstance(value, (dict, list)):
        import json
        return json.dumps(value, sort_keys=True)
    return str(value)


def _contains(haystack, needle) -> bool:
    if isinstance(haystack, list):
        return needle in haystack
    return str(needle) in _text(haystack)


def _where(item, where: dict) -> bool:
    return all(lookup(item, k) == v for k, v in where.items())


def compare(actual, op: str, expected=None, where: dict | None = None) -> bool:
    if op not in OPERATORS:
        raise ValueError(f"unsupported operator {op}")
    if op == "exists":
        return actual is not MISSING and actual is not None
    if op == "absent":
        return actual is MISSING or actual is None or actual == "" or actual == []
    if op == "truthy":
        return actual is not MISSING and bool(actual)
    if op == "falsy":
        return actual is MISSING or not actual
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "in":
        return actual in expected
    if op == "not_in":
        return actual not in expected
    if op in ("gt", "gte", "lt", "lte"):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
        return {"gt": actual > expected, "gte": actual >= expected, "lt": actual < expected, "lte": actual <= expected}[op]
    if op == "contains":
        return _contains(actual, expected)
    if op == "not_contains":
        return not _contains(actual, expected)
    if op == "contains_any":
        return any(_contains(actual, e) for e in expected)
    if op == "contains_none":
        return not any(_contains(actual, e) for e in expected)
    if op == "matches":
        return re.search(expected, _text(actual), re.IGNORECASE) is not None
    if op == "not_matches":
        return re.search(expected, _text(actual), re.IGNORECASE) is None
    if op in ("len_eq", "len_gte", "len_lte"):
        if not isinstance(actual, (list, str, dict)):
            return False
        n = len(actual)
        return {"len_eq": n == expected, "len_gte": n >= expected, "len_lte": n <= expected}[op]
    if op == "count_where":
        if not isinstance(actual, list):
            return False
        return sum(1 for item in actual if _where(item, where or {})) == expected
    if op == "all_eq":
        return isinstance(actual, list) and bool(actual) and all(a == expected for a in actual)
    if op == "strictly_increasing":
        return isinstance(actual, list) and bool(actual) and all(
            isinstance(a, (int, float)) and isinstance(b, (int, float)) and a < b for a, b in zip(actual, actual[1:]))
    if op == "subset_of":
        return isinstance(actual, list) and set(map(str, actual)) <= set(map(str, expected))
    raise ValueError(op)


def evaluate(document, conditions: list[dict]) -> bool:
    """All conditions must hold. Each: {"field": path, "op": operator, "value": ..., "where": {...}}."""
    return all(compare(lookup(document, c["field"]), c["op"], c.get("value"), c.get("where")) for c in conditions)
