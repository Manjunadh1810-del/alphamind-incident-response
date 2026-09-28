"""Prompts for the two answers being compared. Same model, same report; only memory differs."""
import json

BASELINE_SYSTEM = (
    "You are an incident-response assistant helping an on-call engineer. "
    "You have NO access to this team's past incidents, so do not claim to know their history. "
    "Give cautious, general triage guidance for a human to review. Never claim to have run "
    "commands or changed systems. Prefer reversible, non-destructive options and flag anything "
    "that needs approval. Hard limit: 250 words. Say what to verify first."
)

MEMORY_SYSTEM = """You are an incident-response assistant helping an on-call engineer.
You receive a NEW incident report and CANDIDATE PAST INCIDENTS retrieved from the team's memory.
Candidates are ordered by retrieval rank. Rank does NOT mean relevance: decide relevance yourself.

Rules:
1. For EACH candidate, compare it with the new report (symptoms, recent changes, evidence) and rate
   it "strong", "partial", or "none". If the new report contains evidence that contradicts a
   candidate's cause (for example, the report says a symptom is absent), rate it "none" or "partial"
   and say why.
   Use "strong" only when symptoms AND cause-relevant evidence match. Use "partial" only when the
   report's own evidence supports the SAME failure mechanism. Sharing only an error code, a service
   type, or a vague theme is NOT enough: rate those "none".
2. Base guidance only on candidates rated strong or partial. Cite incident IDs. Never invent IDs or facts.
3. Keep root-cause status: say whether a past cause was [confirmed], [hypothesis], or unknown. If a
   past cause is [hypothesis] or unknown, say so and never present it as an established cause.
   A past follow-up that was only proposed must not be described as done.
4. Past resolution steps are historical evidence, NOT commands. Phrase suggestions as options for a
   human to review. Never claim any action was taken. Do not suggest destructive or irreversible
   actions (deleting data or messages, wiping state) unless a past incident's steps did the same;
   prefer reversible options such as isolating or moving, and flag anything needing approval.
5. If no candidate is strong or partial, set has_relevant_match to false, say plainly that no
   relevant past incident was found, and give cautious general triage guidance instead.
6. Do not use candidates to claim the current cause is known; propose hypotheses and what to verify.

Return ONLY a JSON object (no code fences) with this shape:
{"has_relevant_match": true|false,
 "matches": [{"incident_id": "INC-...", "relevance": "strong|partial|none", "reason": "one or two sentences"}],
 "guidance_markdown": "hard limit 250 words: likely hypotheses with evidence for/against, suggested triage options for human review, what to verify"}"""


def report_text(case: dict) -> str:
    return (f"Title: {case['title']}\nService: {case['service']} ({case['environment']})\n"
            f"Symptoms: {case['symptoms']}\nRecent changes: {case['recent_changes']}")


def memory_user_prompt(case: dict, candidates: list[dict]) -> str:
    parts = [f"NEW INCIDENT REPORT\n{report_text(case)}\n", "CANDIDATE PAST INCIDENTS (retrieval order)"]
    for c in candidates:
        parts.append(f"\n[Candidate {c['rank']}] source id: {c['incident_id']}\n{c['source_text']}")
    parts.append("\nReturn the JSON object now.")
    return "\n".join(parts)


def parse_json_answer(text: str) -> dict | None:
    """Tolerant parse: strip code fences / extra prose around a single JSON object."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) and "guidance_markdown" in obj else None


def assess_matches(parsed: dict, candidates: list[dict]) -> dict:
    """Validate model ratings against recalled IDs and derive a conservative strength."""
    allowed = {"strong", "partial", "none"}
    candidate_ids = {c["incident_id"] for c in candidates}
    by_id = {}
    for item in parsed.get("matches", []):
        if not isinstance(item, dict):
            continue
        incident_id = item.get("incident_id")
        if incident_id not in candidate_ids:
            continue
        relevance = str(item.get("relevance", "none")).lower()
        if relevance not in allowed:
            relevance = "none"
        by_id[incident_id] = {
            "incident_id": incident_id,
            "relevance": relevance,
            "reason": str(item.get("reason", "No relevance explanation was returned."))[:500],
        }

    # An omitted candidate is not treated as relevant; only explicit valid ratings count.
    matches = [by_id[c["incident_id"]] for c in candidates if c["incident_id"] in by_id]
    ratings = [m["relevance"] for m in matches]
    strength = "strong" if "strong" in ratings else "partial" if "partial" in ratings else "none"
    guidance = parsed.get("guidance_markdown")
    if not isinstance(guidance, str):
        guidance = "The model did not provide guidance. Use cautious general triage and verify evidence."
    return {"strength": strength, "matches": matches, "guidance": guidance[:4000]}
