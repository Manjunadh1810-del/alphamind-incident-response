# ALPHA MIND INCIDENT RESPONSE

How we built a human-reviewed incident-response agent to carry confirmed lessons into the next alert.

An incident usually leaves behind a useful record: what failed, which evidence mattered, what we tried, and what fixed it. The trouble comes later. That record may be in a ticket or post-mortem, and the next on-call engineer has to find it while production is still having a bad day.

AlphaMind is meant to make that experience available during the next incident. An engineer enters a report. The agent retrieves candidate incidents, compares their evidence with the new report, and offers guidance for a person to review. When the incident is resolved, a person can confirm what happened and retain the outcome for later use.

The point is to carry confirmed lessons forward so we are less likely to repeat the same investigation or mistake. AlphaMind does not execute commands or change production systems.

![Diagram: AlphaMind recalls past incidents to guide a human, then retains a confirmed outcome for future incidents.](alphamind-memory-flow.png)

## Why persistent memory belongs in incident response

An LLM can suggest sensible triage steps, but it does not know how we resolved the last certificate failure, queue crash, or connection-pool issue unless we give it that history. Search can find similar tickets, but similar symptoms do not always mean the same cause. The engineer still needs to compare the evidence.

We use [Hindsight](https://github.com/vectorize-io/hindsight) as the persistent memory layer. Each retained incident includes its ID, service, environment, symptoms, recent changes, root-cause status, resolution steps, and outcome. When a new report arrives, Hindsight recalls candidate memories. The agent compares each candidate with the current evidence; its rank is not treated as proof that the old cause applies.

That gives us a straightforward loop: retain what we have confirmed, recall useful context for a new report, and show enough of the source for the engineer to judge the match. The [Hindsight documentation](https://hindsight.vectorize.io/) covers its memory operations. [This overview of agent memory](https://vectorize.io/what-is-agent-memory) explains the broader idea.

## What happens when an incident is submitted

The app has a small FastAPI backend and a browser interface. It sends the same report down two paths: a baseline answer without incident history, and a memory-assisted answer that first recalls candidate incidents from Hindsight. Both use the configured Groq model. That keeps the comparison focused on what changes when we supply retrieved incident context.

The memory path extracts source records from Hindsight's response, including available chunks. The model rates each candidate as a strong match, a partial match, or not relevant. The backend checks that each rated ID was actually recalled and derives the overall match strength from those ratings. In the interface, an on-call engineer can inspect the source, the relevance explanation, and the guidance before acting on it.

The backend derives the match banner from the per-incident ratings:

```python
ratings = [m["relevance"] for m in matches]
strength = "strong" if "strong" in ratings else \
           "partial" if "partial" in ratings else "none"
```

This makes the banner traceable to IDs that were actually recalled. It does not make the model's judgment infallible; it gives the interface a consistent summary of it.

The recall call looks like this:

```python
return client.recall(
    bank_id=BANK_ID,
    query=to_query_text(report),
    types=["world", "experience"],
    budget="mid",
    max_tokens=2048,
    include_chunks=True,
)
```

The source record matters. If an older incident has a confirmed cause, AlphaMind can say so. If the cause was only a hypothesis or is unknown, the agent is instructed to preserve that uncertainty. Earlier resolution steps are evidence for a person to consider, not commands for the agent to run.

After resolution, an engineer enters the root-cause status, the steps actually taken, and the verified outcome. The retain endpoint requires an explicit confirmation and checks for common sensitive patterns before writing. It stores the confirmed record in Hindsight with an incident ID, service metadata, and a timestamp. A later recall can then return it as context.

The write path uses the same serializer as the seed records:

```python
client.retain(
    bank_id=BANK_ID,
    content=to_memory_text(record),
    document_id=record["incident_id"],
    metadata={"incident_id": record["incident_id"], "service": record["service"]},
    retain_async=False,
)
```

## A before-and-after learning loop

We created a small synthetic incident set: 18 seed incidents for initial memory, six resolved examples kept out of the seed set, and evaluation reports for relevant matches, similar symptoms with different causes, weak matches, and a no-match case. These records are fictional; they are not production data.

One deliberately constructed case shows the learning loop. Before we retained a certificate-related outcome, EVAL-07 described payment authorizations failing because a downstream certificate had expired. Hindsight returned older seed candidates, including INC-1003 at 0.37 and INC-1013 at 0.22. The model rated both as not relevant. AlphaMind showed that it had no relevant past incident and fell back to general triage guidance.

We then retained synthetic incident INC-2002. Its confirmed cause was an expired certificate after a failed renewal job; the recorded resolution was to rerun renewal and reload the service. When we ran EVAL-07 again, Hindsight returned INC-2002 first, with a score of 1.08. The model rated it a strong match and brought back the confirmed cause and earlier steps for a person to review.

The before-and-after is the useful part. The first response had no relevant memory. After we retained a human-confirmed outcome, a later response could use it. The baseline had already noticed the certificate error, so the improvement was not spotting the obvious symptom. The memory path added our recorded cause and remedy.

The numbers need context. Hindsight scores are retrieval signals, not probabilities, and can change as the bank changes. We wrote EVAL-07 to resemble INC-2002, so this one example shows the mechanism, not generalization. The incidents also name different services. A person should decide whether “strong” is the right label or whether “partial” better reflects that difference.

## Human review is part of the design

During an incident, a confident but wrong suggestion can waste time. AlphaMind shows the candidate records and keeps root-cause confidence attached to each memory. It can suggest checks and options, but the person on call decides whether they fit the evidence. The agent cannot restart a service, change a certificate, roll back a deployment, or execute a runbook.

The input guard blocks common patterns that look like email addresses, API tokens, AWS-style keys, or credential assignments. It is a basic safeguard, not a complete data-loss-prevention system. Use synthetic or sanitized data in public recordings, and do not send secrets or personal information to external services.

We also learned to make the confirmation boundary obvious. In an early terminal run, we typed `yes` in lowercase and the retain script refused to write the record; it required us to type `YES` at the confirmation prompt. That small bit of friction was useful. A memory write should happen because someone reviewed the outcome, not because an analysis request happened to finish.

## What this implementation has not proven

The data set is small and synthetic, and we wrote the evaluation cases alongside it. The evaluation is not independent; it cannot establish incident-resolution accuracy, time saved, or production reliability. Model judgments can vary between runs. Retrieval can return a plausible-looking incident with a different cause, which is why the interface shows the source and asks for human review.

The current code does not ingest tickets, connect to live monitoring, track runbook versions, measure outcomes across a real team, or predict deployment risk. Those features would need separate integrations, access controls, evaluation, and operational safeguards. The next step is to try a sanitized, independently reviewed incident set and measure whether the suggestions help engineers reach a correct diagnosis faster.

## Lessons I would carry into another memory feature

1. Keep the source attached to the suggestion. The on-call engineer needs to see what actually happened before reusing a past fix.
2. Separate retrieval rank from relevance. Similar words can hide a different failure mechanism, so compare the evidence.
3. Preserve uncertainty. A hypothesis should still be a hypothesis when it is recalled later.
4. Make memory writes deliberate. Human confirmation helps keep an unverified guess from becoming tomorrow's “known fix.”

## The takeaway

We built AlphaMind around a practical idea: teams should not have to rediscover every lesson from scratch. Retaining confirmed outcomes, recalling their source incidents, and keeping a person in control gives the next response more context than the last one had.

