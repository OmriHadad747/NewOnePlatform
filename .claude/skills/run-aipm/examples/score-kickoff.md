# Kickoff brief — Score model replacement

> Example raw input for "from scratch" mode. Paste this into the platform
> (`aipm transcript ...`) and let it extract the owners, tasks, risks,
> dependencies, decisions, and open questions. Swap in your own kickoff
> material to simulate a real project.

**Goal.** We're replacing the legacy scoring model. The new statistical model is
computed in BigQuery, the scores are published back to the legacy DB through a
Python queue-consumer, then re-synced to BigQuery and reconciled so we can
confirm every score actually landed.

**Who's on it and what they own.**
- Data Scientist (ds@co.com) develops the new statistical scoring model, and
  later runs parity validation (a shadow run against the old model).
- Analytics Engineer (ae@co.com) implements that model in BigQuery and builds the
  score outbox/queue.
- Data Engineer (de@co.com) owns the legacy↔BigQuery sync and the delivery
  reconciliation.
- Backend Engineer (be@co.com) writes the Python publisher service that consumes
  the BQ queue and calls the legacy service to persist scores.
- Legacy Owner (lo@co.com) does the legacy-side adaptations (exposing data for
  the sync, accepting score write-backs). Heads up: they're also on day-to-day
  firefighting, so their availability is limited.

**How the pipeline fits together (this implies the order of work).**
First the legacy owner has to do the legacy-side integration before the data
engineer can sync legacy data into BigQuery. The analytics engineer can only
implement the model in BigQuery once the statistical model exists AND the legacy
data is synced. The score queue comes after the model is in BigQuery. The
publisher service depends on the queue being there, and also on the legacy
integration (it calls the legacy service). Delivery verification depends on the
publisher running, and parity validation comes last, after delivery is verified.

**Risks we already see.**
- Touching the legacy system risks breaking production day-to-day operations (high).
- The legacy owner is split with firefighting, so the integration work may stall (high).
- Legacy↔BigQuery data parity: bad inputs would produce bad scores (high).
- Round-trip delivery: published scores may not reach legacy, or we may have no
  reliable confirmation that they did (high).
- Model parity: new scores could diverge from the old model in production, which
  is business/regulatory exposure (high).
- Queue + Python publisher throughput/latency at full score volume (medium).

**Decisions.**
- Model implementation approach: we tried a SQL stored procedure first, then
  Python, and landed on BigQuery. (decided)
- Queue technology for the score outbox — Pub/Sub vs a BigQuery table-as-queue?
  (still open)
- Cutover strategy — shadow/parallel run vs a hard switch? (still open)

**Open question.** How do we define and reconcile "the score arrived" at the
legacy destination — what's the metric / SLA?
