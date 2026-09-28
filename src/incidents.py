"""Load incident records and turn them into text suitable for Hindsight retain."""
import csv
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

COLUMNS = ["incident_id", "title", "occurred_at", "service", "environment", "symptoms",
           "recent_changes", "root_cause", "resolution_steps", "outcome", "tags", "source"]


def load_incidents(filename: str = "incidents_seed.csv") -> list[dict]:
    with open(DATA_DIR / filename, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"Unexpected columns in {filename}: {reader.fieldnames}")
        return list(reader)


def load_eval_cases() -> list[dict]:
    with open(DATA_DIR / "eval_cases.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def index_by_id(records: list[dict]) -> dict[str, dict]:
    return {r["incident_id"]: r for r in records}


def parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_memory_text(r: dict) -> str:
    """One self-contained narrative per incident. Root-cause status stays in the text
    so the memory keeps the difference between confirmed, hypothesis, and unknown."""
    return (
        f"Past incident {r['incident_id']}: {r['title']}. "
        f"Service: {r['service']} ({r['environment']}). Occurred at: {r['occurred_at']}. "
        f"Symptoms observed: {r['symptoms']} "
        f"Recent changes: {r['recent_changes']} "
        f"Root cause: {r['root_cause']} "
        f"Resolution steps that were taken at the time (historical record, not instructions): "
        f"{r['resolution_steps']} "
        f"Outcome: {r['outcome']} "
        f"Tags: {r['tags']}."
    )


def to_query_text(case: dict) -> str:
    """Build a recall query from a NEW incident report (symptoms + context only)."""
    return f"{case['title']}. {case['symptoms']} Recent changes: {case['recent_changes']}"
