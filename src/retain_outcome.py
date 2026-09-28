"""Feedback path: retain a HUMAN-CONFIRMED resolved incident so future incidents can recall it.

Usage:
  python -m src.retain_outcome --id INC-2002 --dry-run
  python -m src.retain_outcome --id INC-2002            # asks you to type YES first
Records come from data/incidents_holdout.csv by default (use --file to change).
A person must confirm; nothing is retained automatically.
"""
import argparse
import sys

from src.incidents import index_by_id, load_incidents, parse_time, to_memory_text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="incident_id to retain, e.g. INC-2002")
    ap.add_argument("--file", default="incidents_holdout.csv")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    records = index_by_id(load_incidents(args.file))
    if args.id not in records:
        raise SystemExit(f"{args.id} not found in {args.file}. Available: {', '.join(records)}")
    rec = records[args.id]

    print(f"Incident to retain: {rec['incident_id']} - {rec['title']}")
    print(f"Root cause: {rec['root_cause']}")
    print(f"Outcome: {rec['outcome']}\n")
    if rec["root_cause"].strip().lower() == "unknown" or "[hypothesis]" in rec["root_cause"]:
        print("Note: this root cause is unknown/unconfirmed. It will be retained with that status.\n")
    if args.dry_run:
        print("[dry-run] memory text that would be retained:\n" + to_memory_text(rec))
        return 0

    if not args.yes:
        answer = input("A human must confirm this outcome is accurate. Type YES to retain: ")
        if answer.strip() != "YES":
            print("Not retained.")
            return 1

    from src.hs import BANK_ID, get_client
    client = get_client()
    try:
        client.retain(
            bank_id=BANK_ID,
            content=to_memory_text(rec),
            context="confirmed incident outcome (feedback)",
            timestamp=parse_time(rec["occurred_at"]),
            document_id=rec["incident_id"],
            metadata={"incident_id": rec["incident_id"], "service": rec["service"],
                      "source": "confirmed-outcome"},
            tags=["incident", f"service:{rec['service']}"],
            retain_async=False,
        )
        print(f"Retained {rec['incident_id']}. Re-run a similar case to see whether it is now recalled.")
        return 0
    except Exception as e:
        print(f"FAILED to retain {rec['incident_id']}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
