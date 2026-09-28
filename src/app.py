"""Local web app. Run:  uvicorn src.app:app --host 127.0.0.1 --port 8000
Suggestions are for human review; the app never changes any system."""
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src import pipeline
from src.incidents import index_by_id, load_eval_cases, load_incidents

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="AlphaMind Incident Response")

# Demo convenience: which held-out resolved record is the "confirmed outcome" for a sample case.
SAMPLE_OUTCOME_FOR = {"EVAL-01": "INC-2001", "EVAL-02": "INC-2002", "EVAL-03": "INC-2003",
                      "EVAL-04": "INC-2004", "EVAL-05": "INC-2005"}


class Report(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    service: str = Field(min_length=1, max_length=100)
    environment: str = Field(default="production", max_length=50)
    symptoms: str = Field(min_length=10, max_length=3000)
    recent_changes: str = Field(default="", max_length=2000)


class Outcome(BaseModel):
    report: Report
    root_cause_status: Literal["confirmed", "hypothesis", "unknown"]
    root_cause: str = Field(default="", max_length=1000)
    resolution_steps: str = Field(min_length=5, max_length=2000)
    outcome: str = Field(min_length=3, max_length=1000)
    human_confirmed: bool


def _block_sensitive(*texts: str) -> None:
    found = pipeline.find_sensitive(*texts)
    if found:
        raise HTTPException(400, "Input looks like it contains " + ", ".join(found) +
                            ". Remove secrets and personal data, then try again.")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/status")
def status():
    from src.hs import BANK_ID
    from src.llm import MODEL
    return {"hindsight_key_set": bool(os.getenv("HINDSIGHT_API_KEY")),
            "groq_key_set": bool(os.getenv("GROQ_API_KEY")), "bank": BANK_ID, "model": MODEL}


@app.get("/api/cases")
def cases():
    holdout = index_by_id(load_incidents("incidents_holdout.csv"))
    out = []
    for c in load_eval_cases():
        item = {k: c[k] for k in ("case_id", "case_type", "title", "service", "environment",
                                  "symptoms", "recent_changes")}
        h = holdout.get(SAMPLE_OUTCOME_FOR.get(c["case_id"], ""))
        if h:
            rc = h["root_cause"]
            status_ = "confirmed" if rc.startswith("[confirmed]") else "hypothesis" if rc.startswith("[hypothesis]") else "unknown"
            item["sample_outcome"] = {"root_cause_status": status_,
                                      "root_cause": rc.split("] ", 1)[-1] if rc.startswith("[") else "",
                                      "resolution_steps": h["resolution_steps"], "outcome": h["outcome"]}
        out.append(item)
    return out


@app.post("/api/analyze")
def analyze(report: Report):
    _block_sensitive(report.title, report.symptoms, report.recent_changes)
    return pipeline.analyze(report.model_dump())


@app.post("/api/retain")
def retain(body: Outcome):
    if not body.human_confirmed:
        raise HTTPException(400, "A person must confirm the outcome is accurate before it is retained.")
    if body.root_cause_status != "unknown" and len(body.root_cause.strip()) < 3:
        raise HTTPException(400, "Describe the root cause, or set its status to unknown.")
    r = body.report
    _block_sensitive(r.title, r.symptoms, r.recent_changes, body.root_cause,
                     body.resolution_steps, body.outcome)
    try:
        return pipeline.retain_confirmed(r.model_dump(), body.model_dump(exclude={"report", "human_confirmed"}))
    except Exception as e:
        raise HTTPException(502, f"Could not retain into Hindsight: {type(e).__name__}: {e}")
