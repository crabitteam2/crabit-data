# Backend input and original algorithm parity

The internal request remains schema version 1 / algorithm version recap-1. The
approved contract digest is `ec93e480994203a6c8a62d5b9e9992627fba9b71ef346640ea7b80c38f62d233`.
The backend determines effective ledger transactions, snapshot time, account
identity and period windows. Python does not reinterpret correction chains.
`student_id` is the student identity; algorithm `account_id` is
`card_balance_account_id`, scoped to `academy_id`. Profile behavior actor/target
student IDs are mapped by the backend to outgoing/received account aggregates.

`author_previous_month.metrics_version = core-metrics-v1` selects the complete,
closed aggregate. All eight metrics are required. Counts are nonnegative safe
integers; total savings is a signed safe integer; average is finite and signed;
regularity is finite/nonnegative or null; pace is finite/signed or null with no
artificial magnitude bound. Booleans are invalid numbers. Missing or malformed
markers never fall back after a marker is present. An unmarked object accepts only
the original nonempty partial fields. Schema-valid legacy requests retain their
supplied type title. Legacy fractional or beyond-safe count values accidentally
accepted by the old implementation are rejected under its unchanged SafeInteger
contract. This does not claim compatibility with every formerly accepted payload.

Complete aggregates go through the original `CoreMetrics`,
`classify_savings_type` and `build_type_section`. The required supplied type title
is ignored only for complete aggregates. No thresholds, priority, pace prediction,
monthly pattern logic or presenter fields change. `monthly_recap.py` and
`recap_presenter.py` remain byte-identical to the baseline. Shared page-two and
page-three aggregate presentation helpers preserve original Korean messages in
both the raw-data and HTTP paths, without inventing private visitors or author
transactions.

## Period, balance and retry boundaries

Backend requests use an Asia/Seoul end-exclusive period and period-end reference
date. Snapshot-time explicit representative and target amounts are retained;
amounts and transactions exclude subsequent periods. Author metrics use each
story's previous completion month, including December for January, across all
account-owned Wishes, including deleted history. The receiver cannot independently
prove this provenance from aggregate values; database integration tests must.
Received visit counts and unique visitors feed weekly page two. Outgoing author
visits feed monthly classification. The backend supplies complete pre-end history
for lifetime consumers; each original function applies its own required window.

Validation reads but never normalizes or mutates frozen request dictionaries.
Canonical digest verification precedes generation; generation does not replace the
stored input. Repeated identical inputs produce identical results. The stateless
receiver echoes all identities and has no durable idempotency store: reservation,
concurrency, immutable successful results, retry leases, owner authorization and
privacy projection belong to the backend. A successful empty input means zero
activity. Database and HTTP failures do not mean zero activity.

## Rollout and rollback

Deploy the compatible Python receiver before deploying the backend writer of
complete aggregates. Existing stored successful views must remain unchanged.
Previously frozen legacy partial requests continue through the legacy path.
Rolling the receiver back while complete frozen requests are retryable is
incompatible. Keep the compatible receiver until those requests drain, and roll
back the writer through a separately authorized release if necessary. No feature
flag, deployment, merge or release is introduced by this implementation.

## Evidence and remaining acceptance

`tests/test_recap_input_parity.py` contains exact-contract checks, all eleven
original author-metric oracle cases, safe-number and malformed-branch cases,
request immutability, HTTP authentication/idempotency validation and original
visit-message comparisons. Fixtures record the original data revision
`4738d32e179e06c232d5dea048c143a27b534a92`. The oracle has all four classifications,
priority ties, same-day deposits, negative net/average, nullable metrics, negative
pace and pace above one. Visit cases cover zero previous visits, growth, decline
and unchanged visits. Existing service tests also exercise a real HTTP subprocess.
These are receiver/oracle tests; they do not prove database snapshot correctness or
stored app retrieval.

The backend parity harness now passes 11 tests in four suites with no skips,
including actual database-generated weekly and qualifying monthly snapshots sent
unchanged through RecapPythonClient to a local receiver, transactional coordinator
reservation/claim/success, stored request/view/metrics read-back, owner retrieval
and foreign-owner denial. It checks weekly savings 1000 with one deposit, monthly
account-wide savings 3000, nullable peer ranks and stored weekly summary retention.
January/Seoul boundaries, deleted author activity, outgoing visits and the 52-week
habit window also have database coverage. Separately, 60 backend contract and
recommendation regression tests pass in three suites with no skips.

The backend full-suite result remains pending: overlapping Gradle runs failed
result serialization, so those runs are not passing evidence. A sequential full
rerun and frontend/browser verification remain integration-gate requirements.
The requirement tables below retain the finer-grained acceptance checklist; the
passing checks above do not establish every row as complete.

## Q01–Q19 responsibility and evidence map

| Requirement | Responsibility and evidence | Remaining integration evidence |
|---|---|---|
| Q01 | Backend end-exclusive periods and period-end balances; receiver period validation and reference date | Delayed generation with later transactions |
| Q02 | Backend IN_PROGRESS-only fallback; original monthly selector unchanged | Final database fallback regression |
| Q03 | Backend snapshot representative/target; frozen request and receiver immutability tests | Change representative/target after successful storage |
| Q04 | Existing monthly three-deposit and zero-week tests; backend effective deposit count | Actual qualifying monthly export and persistence |
| Q05 | Empty receiver input succeeds; transport failures have error responses | Database failure distinguished from empty query |
| Q06 | Original net/average functions; signed oracle cases | Ledger return/transfer facts through snapshot |
| Q07 | Backend parent-chain folding; receiver consumes effective rows unchanged | Cross-month cancellation and chain tests |
| Q08 | Original pattern-analysis function; distinct-date oracle deviation | Mean-gap message example through final monthly snapshot |
| Q09 | Original weekly/monthly grouping functions unchanged | Fixed month with differing Monday/date-week boundaries |
| Q10 | Original streak function unchanged; backend full history input | 53-week and exact boundary snapshot |
| Q11 | Backend includes deleted Wish history; original filters unchanged | Deleted creation/completion/abandonment snapshots |
| Q12 | Backend age/account/academy cohort construction | Age boundaries and representative-less peer fixture |
| Q13 | Existing monthly no-peers tests; original comparison unchanged | All-tied/partial-tie final backend cohort |
| Q14 | Shared original visit presenter tested against raw visits; outgoing metric classifier oracle | Actual behavior actor/target mapping |
| Q15 | Backend visible-before-first-five, stable order; shared page-three summary | Completion/update boundaries and frozen retry order |
| Q16 | Complete aggregate original classifier oracle | Author other-Wish activity and January rollover database facts |
| Q17 | Original representative pace function unchanged | Other-Wish-only savings and mid-month creation snapshots |
| Q18 | Original fractional-day operation unchanged | Preserve exact September 2 oracle in integration |
| Q19 | Original nonpositive-pace early return unchanged | Reached target with zero pace snapshot |

## T01–T24 acceptance tracking

| Cases | Receiver evidence | Integration work still required |
|---|---|---|
| T01–T03 | Effective transaction contract; no correction reinterpretation | Cancellation, corrected amount and cross-month chains |
| T04 | Zero weekly and three-deposit monthly unit tests | Qualifying backend snapshot export and persisted result |
| T05–T06 | Original net/average/classifier with signed oracle | Returns, transfer pairs and deleted history from ledger |
| T07–T08 | Frozen-input immutability/digest tests | Delayed generation, representative changes and repeat stored reads |
| T09–T12 | Original pace function preserved; nonpositive pace regression | Representative-specific pace, mid-month days, fractional-day and early-return fixtures |
| T13–T14 | Distinct-day deviation oracle; original grouping/streak unchanged | Average-gap message, month week boundaries, 53-week database input |
| T15–T16 | Existing no-peers nullable response | Exact cohort eligibility and tie/rank boundaries |
| T17 | Raw received-visit presentation parity; outgoing count classifier | Actual behavior-event identity/direction mapping |
| T18–T20 | Bounded closed candidates, all four author types, no raw author fields | Visibility/order, previous-month/year rollover and >100-Wish account facts |
| T21 | HTTP auth/schema/idempotency/digest failure tests | DB failures, timeouts and mismatched persisted responses |
| T22 | Deterministic identical HTTP retry output | Durable concurrent reservations and conflicting result rejection |
| T23–T24 | Receiver does not mutate stored state | Owner-only retrieval and current story privacy after deletion/private/block |
