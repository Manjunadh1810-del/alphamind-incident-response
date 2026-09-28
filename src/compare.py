"""Milestone 2: baseline (no memory) vs memory-assisted answer for one eval case.

Usage:
  python -m src.compare --case EVAL-02
  python -m src.compare --case EVAL-06 --top 4 --show-prompt
"""
import argparse
import sys

from src.incidents import load_eval_cases, to_query_text
from src.prompts import (BASELINE_SYSTEM, MEMORY_SYSTEM, memory_user_prompt,
                         parse_json_answer, report_text)
from src.recall_demo import group_by_source


def build_candidates(resp, top_k: int) -> list[dict]:
    """Top-k source incidents from a recall response. The source text comes from the
    chunks Hindsight stored (include_chunks), so it also works for incidents retained later."""
    chunks = getattr(resp, "chunks", None) or {}
    out = []
    for doc_id, best, facts in group_by_source(resp.results):
        if doc_id.startswith("("):  # consolidated observations have no citable source id
            continue
        texts, seen = [], set()
        for f in facts:
            ch = chunks.get(getattr(f, "chunk_id", None))
            t = ch.text if ch is not None else None
            if t and t not in seen:
                seen.add(t); texts.append(t)
        source = "\n".join(texts) if texts else "\n".join(f"- {f.text}" for f in facts[:4]) + \
            "\n(note: only extracted facts were available, not the full source record)"
        out.append({"rank": len(out) + 1, "incident_id": doc_id, "score": best, "source_text": source})
        if len(out) >= top_k:
            break
    return out


def format_memory_view(parsed: dict, candidates: list[dict]) -> str:
    """Match strength is derived from the per-candidate ratings in code, so the UI never
    depends on the model's own summary flag. Ratings for IDs we did not supply are dropped."""
    valid = {c["incident_id"] for c in candidates}
    matches, dropped = [], []
    for m in parsed.get("matches", []):
        (matches if m.get("incident_id") in valid else dropped).append(m)
    ratings = [str(m.get("relevance", "")).lower() for m in matches]
    if "strong" in ratings:
        strength = "STRONG"
    elif "partial" in ratings:
        strength = "PARTIAL ONLY (treat with caution: the past cause may not apply)"
    else:
        strength = "NONE"
    lines = [f"Match strength: {strength}"]
    if strength == "NONE":
        lines.append("NO RELEVANT PAST INCIDENT FOUND IN MEMORY. The guidance below is general "
                     "triage advice, not based on a past incident.")
    lines.append("Relevance check:")
    for m in matches:
        lines.append(f"  - {m.get('incident_id')}: {m.get('relevance')} -- {m.get('reason')}")
    if dropped:
        lines.append(f"  (ignored {len(dropped)} rating(s) for IDs that were not recalled)")
    lines.append("\n" + str(parsed.get("guidance_markdown", "")))
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # safe on Windows consoles
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--top", type=int, default=4)
    ap.add_argument("--show-prompt", action="store_true")
    args = ap.parse_args()

    cases = {c["case_id"]: c for c in load_eval_cases()}
    if args.case not in cases:
        raise SystemExit(f"Unknown case {args.case}. Choose from: {', '.join(cases)}")
    case = cases[args.case]

    from src.hs import BANK_ID, get_client
    from src.llm import MODEL, LLMError, chat

    print(f"Case {case['case_id']} ({case['case_type']}): {case['title']}")
    print(f"Model: {MODEL}\n")

    # ---- Baseline: no memory ----
    try:
        baseline = chat(BASELINE_SYSTEM, report_text(case))
    except LLMError as e:
        baseline = f"[baseline failed: {e}]"

    # ---- Memory-assisted: Hindsight recall, then the same model with candidates ----
    client = get_client()
    try:
        resp = client.recall(bank_id=BANK_ID, query=to_query(case), types=["world", "experience"],
                             budget="mid", max_tokens=2048, include_chunks=True)
    except Exception as e:
        resp = None
        recall_error = f"{type(e).__name__}: {e}"
    finally:
        client.close()

    if resp is None:
        print("=== BASELINE (no memory) ===\n" + baseline)
        print(f"\n=== MEMORY-ASSISTED ===\n[recall failed: {recall_error}]. Falling back to the baseline above.")
        return 1

    candidates = build_candidates(resp, args.top)
    print("Recalled candidates (Hindsight rank): " +
          (" | ".join(f"{c['incident_id']} {c['score']:.2f}" for c in candidates) or "none") + "\n")

    if not candidates:
        memory_view = "No relevant past incident found in memory. Use the baseline general guidance."
    else:
        prompt = memory_user_prompt(case, candidates)
        if args.show_prompt:
            print("--- memory prompt sent to LLM ---\n" + prompt + "\n---------------------------------\n")
        try:
            raw = chat(MEMORY_SYSTEM, prompt)
            parsed = parse_json_answer(raw)
            if parsed is None:
                memory_view = "[could not parse structured answer; raw model output below]\n" + raw
            else:
                memory_view = format_memory_view(parsed, candidates)
        except LLMError as e:
            memory_view = f"[memory-assisted call failed: {e}]"

    print("=== BASELINE (no memory) ===\n" + baseline)
    print("\n=== MEMORY-ASSISTED (Hindsight recall) ===\n" + memory_view)
    print("\nExpected for this case:", case["expected_relevant_seed_ids"])
    print("Suggestions are for human review; nothing was executed.")
    return 0


def to_query(case: dict) -> str:
    return to_query_text(case)


if __name__ == "__main__":
    raise SystemExit(main())
