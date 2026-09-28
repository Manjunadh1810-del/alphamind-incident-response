"""Shared pipeline for the web app: analyze a report (baseline vs memory-assisted) and
retain a human-confirmed outcome. Every external call is wrapped so one failure never
crashes the request; the response says which part failed."""
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from src.compare import build_candidates
from src.incidents import parse_time, to_memory_text, to_query_text
from src.llm import chat
from src.prompts import (BASELINE_SYSTEM, MEMORY_SYSTEM, assess_matches, memory_user_prompt,
                         parse_json_answer, report_text)

SENSITIVE = {
    "an email address": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "an API key or token": re.compile(r"\b(?:gsk|hsk|sk|pk|ghp|xox[bp])[_-][A-Za-z0-9_\-]{16,}\b"),
    "an AWS-style key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "a credential assignment (password=, token=, ...)":
        re.compile(r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+"),
}
NO_MATCH_NOTICE = ("No relevant past incident found in memory. The guidance below is general "
                   "triage advice, not based on a past incident.")


def find_sensitive(*texts: str) -> list[str]:
    joined = "\n".join(t for t in texts if t)
    return [label for label, rx in SENSITIVE.items() if rx.search(joined)]


def _recall(report: dict):
    if not os.getenv("HINDSIGHT_API_KEY"):
        raise RuntimeError("HINDSIGHT_API_KEY is not set")
    from src.hs import BANK_ID, get_client
    client = get_client()
    try:
        return client.recall(bank_id=BANK_ID, query=to_query_text(report), types=["world", "experience"],
                             budget="mid", max_tokens=2048, include_chunks=True)
    finally:
        client.close()


def _retain(record: dict) -> None:
    if not os.getenv("HINDSIGHT_API_KEY"):
        raise RuntimeError("HINDSIGHT_API_KEY is not set")
    from src.hs import BANK_ID, get_client
    client = get_client()
    try:
        client.retain(
            bank_id=BANK_ID, content=to_memory_text(record),
            context="confirmed incident outcome (feedback)",
            timestamp=parse_time(record["occurred_at"]), document_id=record["incident_id"],
            metadata={"incident_id": record["incident_id"], "service": record["service"],
                      "source": "confirmed-outcome"},
            tags=["incident", f"service:{record['service']}"], retain_async=False)
    finally:
        client.close()


def _err(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"


def analyze(report: dict, top_k: int = 4) -> dict:
    out = {"baseline": {"text": None, "error": None},
           "candidates": [], "recall_error": None,
           "memory": {"strength": "none", "notice": None, "matches": [], "guidance": None,
                      "error": None, "raw": None}}
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_base = ex.submit(chat, BASELINE_SYSTEM, report_text(report))
        f_recall = ex.submit(_recall, report)
        try:
            out["baseline"]["text"] = f_base.result()
        except Exception as e:
            out["baseline"]["error"] = _err(e)
        try:
            out["candidates"] = build_candidates(f_recall.result(), top_k)
        except Exception as e:
            out["recall_error"] = _err(e)

    mem = out["memory"]
    if out["recall_error"]:
        mem["error"] = "Hindsight recall failed, so there is no memory-assisted answer."
        return out
    if not out["candidates"]:
        mem["notice"] = "Memory returned nothing usable. Use the baseline general guidance."
        return out
    try:
        raw = chat(MEMORY_SYSTEM, memory_user_prompt(report, out["candidates"]))
    except Exception as e:
        mem["error"] = f"Memory-assisted LLM call failed: {_err(e)}"
        return out
    parsed = parse_json_answer(raw)
    if parsed is None:
        mem["error"] = "The model did not return the expected structure. Raw output is shown."
        mem["raw"] = raw
        return out
    r = assess_matches(parsed, out["candidates"])
    mem.update(strength=r["strength"], matches=r["matches"], guidance=r["guidance"])
    if r["strength"] == "none":
        mem["notice"] = NO_MATCH_NOTICE
    by_id = {m["incident_id"]: m for m in r["matches"]}
    for c in out["candidates"]:
        m = by_id.get(c["incident_id"])
        c["relevance"] = m["relevance"] if m else None
        c["reason"] = m["reason"] if m else None
        c["score"] = round(c["score"], 3)
    return out


def retain_confirmed(report: dict, outcome: dict) -> dict:
    """Retain a human-confirmed outcome for the current incident as a new memory."""
    status = outcome["root_cause_status"]
    cause = outcome["root_cause"].strip()
    now = datetime.now(timezone.utc)
    record = {
        "incident_id": f"INC-U-{now:%Y%m%d%H%M%S}",
        "title": report["title"], "occurred_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "service": report["service"], "environment": report["environment"],
        "symptoms": report["symptoms"], "recent_changes": report["recent_changes"] or "None reported.",
        "root_cause": "unknown" if status == "unknown" else f"[{status}] {cause}",
        "resolution_steps": outcome["resolution_steps"].strip(),
        "outcome": outcome["outcome"].strip(), "tags": "user-confirmed",
        "source": "AlphaMind web UI: human-confirmed outcome",
    }
    _retain(record)
    return {"incident_id": record["incident_id"]}
