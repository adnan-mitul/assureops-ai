"""Phase registry: what each phase may see, which model may serve it, and what it must return.

A phase is enabled only when (1) a provider route is configured, (2) the exact
model is recorded as qualified for this phase/prompt/schema, and (3) for an
external provider, the workspace allows external processing and the phase is
approved for that provider. Otherwise the phase reports a typed unavailable
state and the workflow continues with reviewers.
"""

from dataclasses import dataclass, field

QUICK_STATUS = "quick_check"  # qualification record of a 20-case quick run that found no critical error: informational only
# Phase G-2 flag threshold on Prompt Guard 2's injection probability. Its scores are extreme: on phase-G-dev-v2 (60 cases,
# families disjoint from the held-out sets) benign text scored at most 0.0006 and attacks at least 0.0009, so 0.5 missed most
# attacks. Chosen on the development split only; a flag asks for review and never blocks or authorizes anything.
SCREEN_THRESHOLD = 0.0008

SPAN = {"type": "object", "required": ["source_id", "quote"], "properties": {
    "source_id": {"type": "string"}, "quote": {"type": "string", "minLength": 3, "maxLength": 400}}}
SPANS = {"type": "array", "items": SPAN, "maxItems": 12}
UNKNOWNS = {"type": "array", "items": {"type": "string", "maxLength": 300}, "maxItems": 12}

SCHEMAS = {
    "A": {"type": "object", "required": ["requirements", "unknowns"], "additionalProperties": False, "properties": {
        "requirements": {"type": "array", "maxItems": 20, "items": {"type": "object", "required": ["statement", "control", "spans"],
                         "additionalProperties": False, "properties": {
                             "statement": {"type": "string", "minLength": 5, "maxLength": 400},
                             "control": {"type": "string", "pattern": "^C(0[1-9]|10)$"},
                             "applicability_question": {"type": "string", "maxLength": 300}, "spans": SPANS}}},
        "unknowns": UNKNOWNS}},
    "B": {"type": "object", "required": ["links", "gaps"], "additionalProperties": False, "properties": {
        "links": {"type": "array", "maxItems": 60, "items": {"type": "object", "required": ["test_id", "component_id", "rationale"],
                  "additionalProperties": False, "properties": {
                      "test_id": {"type": "string"}, "component_id": {"type": "string"}, "rationale": {"type": "string", "maxLength": 300}}}},
        "gaps": UNKNOWNS}},
    "C": {"type": "object", "required": ["tests", "unknowns"], "additionalProperties": False, "properties": {
        "tests": {"type": "array", "maxItems": 12, "items": {"type": "object", "required": ["template", "control", "args", "name"],
                  "additionalProperties": False, "properties": {
                      "template": {"type": "string"}, "control": {"type": "string", "pattern": "^C(0[1-9]|10)$"},
                      "name": {"type": "string", "maxLength": 160}, "args": {"type": "object"},
                      "severity": {"enum": ["low", "medium", "high", "critical"]}}}},
        "unknowns": UNKNOWNS}},
    "E": {"type": "object", "required": ["summary", "hypotheses", "retest_suggestions", "spans"], "additionalProperties": False, "properties": {
        "summary": {"type": "string", "maxLength": 900}, "hypotheses": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 300}},
        "retest_suggestions": {"type": "array", "maxItems": 10, "items": {"type": "string"}}, "spans": SPANS}},
    "F": {"type": "object", "required": ["sections", "unknowns"], "additionalProperties": False, "properties": {
        "sections": {"type": "array", "minItems": 1, "maxItems": 16, "items": {"type": "object", "required": ["heading", "text", "fact_ids"],
                     "additionalProperties": False, "properties": {
                         "heading": {"type": "string", "maxLength": 120}, "text": {"type": "string", "maxLength": 1200},
                         "fact_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20}}}},
        "unknowns": UNKNOWNS}},
}


@dataclass(frozen=True)
class Phase:
    id: str
    name: str
    kind: str  # generate | embed | classify
    candidate: str
    parameters: str
    purpose: str
    prompt_version: str
    schema_version: str
    external_approved: tuple = field(default_factory=tuple)  # providers approved for this phase besides private serving
    optional: bool = False


PHASES: dict[str, Phase] = {p.id: p for p in [
    Phase("A", "requirement_analysis", "generate", "ibm-granite/granite-4.0-micro", "3B",
          "Approved references and scope -> proposed requirements with source spans and applicability questions", "A-2", "A-2",
          external_approved=("groq",)),
    Phase("B", "dependency_mapping", "generate", "microsoft/Phi-4-mini-instruct", "3.8B",
          "Requirements, collected manifest components and observations -> proposed component links and explicit gaps", "B-2", "B-2",
          external_approved=("groq",)),
    Phase("C", "test_proposal", "generate", "Qwen/Qwen2.5-Coder-1.5B-Instruct", "1.54B",
          "Reviewed requirements and the permitted catalogue -> template IDs with typed arguments", "C-4", "C-2",
          external_approved=("groq",)),
    Phase("D", "semantic_evaluation", "classify", "cross-encoder/nli-deberta-v3-small", "~0.1B",
          "Atomic claim/premise pairs -> entailment/contradiction/neutral signals beside actual test outcomes", "D-2", "D-2"),
    Phase("E", "incident_analysis", "generate", "microsoft/Phi-4-mini-instruct", "3.8B",
          "Verified events and release changes -> cited summary, hypotheses and approved retest suggestions", "E-2", "E-2",
          external_approved=("groq",)),
    Phase("F", "explanation", "generate", "HuggingFaceTB/SmolLM2-1.7B-Instruct", "1.7B",
          "Frozen evidence facts -> readable report draft; the backend renders verdicts and numbers", "F-3", "F-3",
          external_approved=("groq",)),
    Phase("R", "retrieval", "embed", "BAAI/bge-small-en-v1.5", "33.4M",
          "Authorized English sources -> embeddings; hybrid retrieval only after comparison with lexical search", "R-1", "R-1"),
    Phase("G", "input_screening", "classify", "meta-llama/Llama-Prompt-Guard-2-86M", "86M",
          "Bounded untrusted text -> screening signal; never authorizes an action", "G-2", "G-2", external_approved=("groq",), optional=True),
]}


def schema(phase_id: str) -> dict | None:
    return SCHEMAS.get(phase_id)


def constrained(phase_id: str, ctx: dict) -> dict | None:
    """The phase schema narrowed to the identifiers this request may use, so constrained decoding cannot invent them.

    Validation still runs on the output; this only removes a class of errors small models make."""
    import copy

    base = SCHEMAS.get(phase_id)
    if base is None:
        return None
    s = copy.deepcopy(base)
    props = s["properties"]
    if phase_id == "A" and ctx.get("sources"):
        props["requirements"]["items"]["properties"]["spans"]["items"]["properties"]["source_id"] = {"enum": sorted(ctx["sources"])}
    if phase_id == "B":
        item = props["links"]["items"]["properties"]
        item["test_id"] = {"enum": ctx["test_ids"]} if ctx.get("test_ids") else item["test_id"]
        item["component_id"] = {"enum": ctx["component_ids"]} if ctx.get("component_ids") else item["component_id"]
    if phase_id == "C" and ctx.get("templates"):
        props["tests"]["items"]["properties"]["template"] = {"enum": ctx["templates"]}
    if phase_id == "E":
        if ctx.get("test_ids"):
            props["retest_suggestions"]["items"] = {"enum": ctx["test_ids"]}
        if ctx.get("sources"):
            props["spans"]["items"]["properties"]["source_id"] = {"enum": sorted(ctx["sources"])}
    if phase_id == "F" and ctx.get("facts"):
        props["sections"]["items"]["properties"]["fact_ids"]["items"] = {"enum": sorted(ctx["facts"])}
    return s
