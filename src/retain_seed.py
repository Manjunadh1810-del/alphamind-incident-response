"""Milestone 1a: retain the seed incidents into Hindsight (one document per incident).

Usage:
  python -m src.retain_seed --dry-run     # no network; shows what would be retained
  python -m src.retain_seed               # retains into Hindsight
"""
import argparse
import sys

from src.incidents import load_incidents, parse_time, to_memory_text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="retain only the first N incidents")
    args = ap.parse_args()

    records = load_incidents("incidents_seed.csv")
    if args.limit:
        records = records[: args.limit]

    # Safety check: holdout incidents (INC-2xxx) must never enter memory.
    if any(r["incident_id"].startswith("INC-2") for r in records):
        print("Refusing to run: holdout incident found in seed set.", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"[dry-run] would retain {len(records)} incidents. First one:\n")
        print(to_memory_text(records[0]))
        return 0

    from src.hs import BANK_ID, BANK_MISSION, get_client
    client = get_client()

    try:
        client.create_bank(bank_id=BANK_ID, name="AlphaMind Incidents", mission=BANK_MISSION)
        print(f"Created bank '{BANK_ID}'.")
    except Exception as e:  # bank may already exist; do not hide other errors
        print(f"create_bank note (continuing): {type(e).__name__}: {e}")

    ok, failed = 0, []
    try:
        _retain_all(client, BANK_ID, records, ok, failed)
    finally:
        client.close()
    return 1 if failed else 0


def _retain_all(client, BANK_ID, records, ok, failed):
    for r in records:
        try:
            client.retain(
                bank_id=BANK_ID,
                content=to_memory_text(r),
                context="past incident record",
                timestamp=parse_time(r["occurred_at"]),
                document_id=r["incident_id"],  # lets us trace any recalled fact back to its incident
                metadata={"incident_id": r["incident_id"], "service": r["service"],
                          "source": "synthetic-seed"},
                tags=["incident", f"service:{r['service']}"],
                retain_async=False,
            )
            ok += 1
            print(f"retained {r['incident_id']}")
        except Exception as e:
            failed.append((r["incident_id"], f"{type(e).__name__}: {e}"))
            print(f"FAILED {r['incident_id']}: {e}", file=sys.stderr)

    print(f"\nDone: {ok} retained, {len(failed)} failed.")


if __name__ == "__main__":
    raise SystemExit(main())
