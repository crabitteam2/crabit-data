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

The controller adopted backend develop base
`5e468b2cd21cff20b56c0fde7920cd22baed5d1c` and data main base
`ae65675f53d6d1538c744f30ddce2df46de75156`, producing backend HEAD
`1fb57a7db0c0bd136a981d5bae65d3286a2b7e2b` and data HEAD
`a3faf23732ef0d88b11b2708e0876530f40c44a4`. Base integration is complete.

The scheduled-path review rework at that backend HEAD reserves PREPARATION,
claims preparation, builds the database snapshot with the reserved generation ID,
completes preparation, claims generation, sends frozen bytes over actual HTTP,
and records success. Duplicate scheduling before preparation and after success
retains the generation. Repeated owner queries preserve complete responses and
all stored generation fields. With this test/document rework applied, parity
passed 11 tests in four suites and the sequential full backend suite passed 628
tests in 123 suites; both had zero failures, errors or skips. Local logs are
`/private/tmp/recap-scheduled-parity.log` and
`/private/tmp/recap-scheduled-full.log`, with XML reports in the matching
`recap-scheduled-parity-xml` and `recap-scheduled-full-xml` directories.
These supersede historical pre-integration counts. The earlier data suite passed
49 tests at HEAD `73daa30a6ff8630d513068d1ffc49eb9ca086328`; that historical
receiver result is not a fresh test of this documentation-only update.

Existing-app browser acceptance passed one Playwright test in 19.6 seconds on the
integrated production trees using disposable PostgreSQL, the real receiver,
backend and existing frontend. Real ledger facts and scheduled PREPARATION
reservations produced the requests. It verified weekly and qualifying monthly
rendering, repeated response equality and immutable stored inputs, nullable
achievement presentation, story navigation, monthly ineligibility, failure UI
when the receiver was stopped, and foreign-owner 404. A legal FOLLOWERS visibility
change revoked unauthorized story access and its link while preserving stored
successful views. This supersedes the earlier invalid PRIVATE fixture attempt.
The script and passing log are under
`/private/tmp/crabit-recap-preparation-browser/` (`recap-preparation.spec.mjs` and
`run-final.log`). The controller repository retains the browser bundle and manifest
under `workflows/publications/recap-algorithm-input-parity/validation/`, named
`browser-1fb57a7-a3faf237.*`. This is local acceptance evidence, not deployed
acceptance or release approval. The tables separate confirmed checks from finer
grain scenarios still requiring explicit evidence.

## Q01–Q19 responsibility and evidence map

| Requirement | Responsibility and evidence | Confirmed integration / remaining evidence |
|---|---|---|
| Q01 | Backend end-exclusive periods and period-end balances; receiver period validation and reference date | Delayed generation with later transactions |
| Q02 | Backend IN_PROGRESS-only fallback; original monthly selector unchanged | Final database fallback regression |
| Q03 | Backend snapshot representative/target; frozen request and receiver immutability tests | Change representative/target after successful storage |
| Q04 | Existing monthly three-deposit and zero-week tests; backend effective deposit count | Confirmed: qualifying monthly database export, HTTP generation, persistence and browser rendering |
| Q05 | Empty receiver input succeeds; transport failures have error responses | Database failure distinguished from empty query |
| Q06 | Original net/average functions; signed oracle cases | Ledger return/transfer facts through snapshot |
| Q07 | Backend parent-chain folding; receiver consumes effective rows unchanged | Confirmed: backdated/cross-month cancellation and stable root identity; remaining: other chain variants |
| Q08 | Original pattern-analysis function; distinct-date oracle deviation | Mean-gap message example through final monthly snapshot |
| Q09 | Original weekly/monthly grouping functions unchanged | Fixed month with differing Monday/date-week boundaries |
| Q10 | Original streak function unchanged; backend full history input | Confirmed: exact 52-week habit cutoff with Seoul inclusive/exclusive boundaries; remaining: explicit 53-week example |
| Q11 | Backend includes deleted Wish history; original filters unchanged | Deleted creation/completion/abandonment snapshots |
| Q12 | Backend age/account/academy cohort construction | Confirmed: age provenance, synthetic-age exclusion and representative-less peer fixture; remaining: exact age boundaries |
| Q13 | Existing monthly no-peers tests; original comparison unchanged | All-tied/partial-tie final backend cohort |
| Q14 | Shared original visit presenter tested against raw visits; outgoing metric classifier oracle | Confirmed: outgoing author-visit actor/account mapping; remaining: full received-visit direction fixture |
| Q15 | Backend visible-before-first-five, stable order; shared page-three summary | Confirmed: visibility-before-limit, completion-month selection and immutable repeated retrieval; remaining: exact update-boundary example |
| Q16 | Complete aggregate original classifier oracle | Confirmed: account-wide author activity, deleted Wishes and January/December Seoul rollover |
| Q17 | Original representative pace function unchanged | Other-Wish-only savings and mid-month creation snapshots |
| Q18 | Original fractional-day operation unchanged | Preserve exact September 2 oracle in integration |
| Q19 | Original nonpositive-pace early return unchanged | Reached target with zero pace snapshot |

## T01–T24 acceptance tracking

| Cases | Receiver evidence | Confirmed integration / remaining evidence |
|---|---|---|
| T01–T03 | Effective transaction contract; no correction reinterpretation | Confirmed: backdated/cross-month cancellation and stable roots; remaining: additional corrected-amount/chain fixtures |
| T04 | Zero weekly and three-deposit monthly unit tests | Confirmed: qualifying monthly export, HTTP result, stored read-back and browser rendering |
| T05–T06 | Original net/average/classifier with signed oracle | Returns, transfer pairs and deleted history from ledger |
| T07–T08 | Frozen-input immutability/digest tests | Confirmed: repeated weekly/monthly owner responses and immutable stored generation fields; remaining: later representative/target changes and delayed generation |
| T09–T12 | Original pace function preserved; nonpositive pace regression | Representative-specific pace, mid-month days, fractional-day and early-return fixtures |
| T13–T14 | Distinct-day deviation oracle; original grouping/streak unchanged | Confirmed: exact 52-week habit cutoff; remaining: average-gap message, month week boundaries and explicit 53-week example |
| T15–T16 | Existing no-peers nullable response | Confirmed: age provenance, synthetic-age exclusion, representative-less peers and nullable browser presentation; remaining: exact age and tie/rank boundaries |
| T17 | Raw received-visit presentation parity; outgoing count classifier | Confirmed: outgoing author visit student/account mapping; remaining: received-visit direction fixture |
| T18–T20 | Bounded closed candidates, all four author types, no raw author fields | Confirmed: visibility-before-limit, previous completion month, January/December rollover and deleted account activity; remaining: explicit >100-Wish fixture |
| T21 | HTTP auth/schema/idempotency/digest failure tests | Confirmed: real stopped-receiver failure UI and existing response-identity checks; remaining: explicit DB-failure and timeout evidence |
| T22 | Deterministic identical HTTP retry output | Confirmed: scheduled reserve/prepare/claim/success and duplicate reservation before preparation/after success; remaining: explicit concurrent-reservation and conflicting-result cases |
| T23–T24 | Receiver does not mutate stored state | Confirmed: owner retrieval, foreign-owner 404 and FOLLOWERS revocation preserving stored views; remaining: deletion/block-specific browser cases (PRIVATE is not a legal shared-card fixture) |
