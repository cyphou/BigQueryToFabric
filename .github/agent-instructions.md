# Shared agent rules

1. Read the canonical model and existing tests before changing behavior.
2. Modify only files listed under the agent's ownership section.
3. Preserve immutable BigQuery source identifiers; proposed Fabric names are separate outputs.
4. Treat dynamic SQL, JavaScript UDFs, BQML, policy tags, and cross-project dependencies as
   explicit review items when equivalence cannot be proven.
5. Validate the narrow changed behavior first, then run the full suite.
6. Cloud deployment must remain opt-in and dry-run by default.

## Working loop

Every implementation agent runs the same loop:

```mermaid
flowchart LR
    P[Plan] --> A[Assign owner]
    A --> I[Implement]
    I --> SH[Self-heal<br/>repair_and_validate]
    SH --> R[Review]
    R -->|accepted| P
    R -->|changes_requested<br/>round < 3| I
    R -->|method issue| PR[Preceptor]
    R -->|escalate / round 3| TL[TechLead]
    PR --> I
    TL --> P
```

1. **Plan** — record the expected behaviour before writing code.
2. **Assign** — one owner per path. Do not edit another agent's owned files.
3. **Implement** — the smallest change that makes the expected behaviour true.
4. **Self-heal** — optional: apply existing `RepairRule`s. A repair never skips review.
5. **Review** — `Reviewer` and `Tester` return a verdict conforming to
   `.github/review-verdict.schema.json`; `Orchestrator` routes it. Accepted work goes to
   `Documentation`.

## Feedback loop

- `changes_requested` returns the slice to its owner, never to the reviewer to fix.
- Two rework rounds at most; the third review must accept or escalate to `TechLead`.
- A finding code that recurs across slices goes to `Preceptor` to become a failure mode
  or, if mechanical, a tested `RepairRule`.

## Escalation

| Escalate to | When |
|---|---|
| `Preceptor` | Uncertain how to verify a change, a test fails after a fix and you are unsure whether it protected the contract or the bug, or a fixture's shape is unconfirmed. |
| `TechLead` | Scope is growing, two agents need the same file, a published contract would change, or a gate stands in the way. |

Escalate early. A blocked gate is information, never an obstacle to remove.
