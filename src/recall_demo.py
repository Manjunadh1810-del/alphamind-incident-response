"""Milestone 1b: recall memories for a NEW incident report and show the source incidents.

Usage:
  python -m src.recall_demo --case EVAL-01            # top 3 source incidents in detail
  python -m src.recall_demo --case EVAL-06 --top 5
  python -m src.recall_demo --case EVAL-01 --dry-run  # prints the query only (no network)
"""
import argparse
from collections import defaultdict

from src.incidents import index_by_id, load_eval_cases, load_incidents, to_query_text


def score_of(fact) -> float:
    s = getattr(fact, "scores", None)
    v = getattr(s, "final", None) if s else None
    return v if v is not None else 0.0


def group_by_source(results) -> list[tuple[str, float, list]]:
    """Group recalled facts by source incident (document_id); best score first.
    Consolidated observations have no document_id and are kept in their own bucket."""
    groups = defaultdict(list)
    for r in results:
        groups[r.document_id or "(consolidated observations)"].append(r)
    ranked = [(doc, max(score_of(f) for f in facts), facts) for doc, facts in groups.items()]
    return sorted(ranked, key=lambda t: t[1], reverse=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, help="e.g. EVAL-01")
    ap.add_argument("--top", type=int, default=3, help="how many source incidents to print in detail")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cases = {c["case_id"]: c for c in load_eval_cases()}
    if args.case not in cases:
        raise SystemExit(f"Unknown case {args.case}. Choose from: {', '.join(cases)}")
    case = cases[args.case]
    query = to_query_text(case)

    print(f"Case {case['case_id']} ({case['case_type']}): {case['title']}")
    print(f"Query sent to Hindsight recall:\n  {query}\n")
    if args.dry_run:
        return 0

    from src.hs import BANK_ID, get_client
    client = get_client()
    try:
        resp = client.recall(bank_id=BANK_ID, query=query, budget="mid", max_tokens=2048)
    finally:
        client.close()

    if not resp.results:
        print("No memories returned. The agent should say no relevant record was found.")
        return 0

    ranked = group_by_source(resp.results)
    print("Ranking (source: best fact score):")
    print("  " + " | ".join(f"{doc} {score:.2f}" for doc, score, _ in ranked) + "\n")

    seed = index_by_id(load_incidents("incidents_seed.csv"))
    for doc_id, best, facts in ranked[: args.top]:
        print(f"=== Source: {doc_id}   (best fact score {best:.2f}, {len(facts)} fact(s)) ===")
        for f in facts[:3]:
            print(f"  - [{f.type}] {f.text}")
        rec = seed.get(doc_id)
        if rec:
            print(f"  Full record -> service={rec['service']} | root_cause={rec['root_cause'][:110]}")
        print()

    print("Expected for this case:", case["expected_relevant_seed_ids"])
    print("Note: scores are relative within one query; judge relevance by reading the records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
