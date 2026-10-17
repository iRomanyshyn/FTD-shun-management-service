# Development Manual

## Offline managed-policy foundation

`tests/test_managed_protection.py` exercises optional managed-state validation,
enabled-intent counts, current-revision/acknowledgement checks before protection
weakening, real all-role BFF forwarding, unchanged authority and no work hints.
It covers audit rollback including unsent ADD cancellation, retained RUNNING ADD/
waiting cleanup, missing/disabled targets, malformed optional state with healthy
monitoring, guarded legacy fleet/device removal and serialized MAINTAIN/removal
admission. All state and actors are synthetic. Chromium verifies dirty managed
revision/checkbox retention, stale rejection, fresh acknowledgement reset and
mobile warning layout; no lab policy/FTD mutation is performed.

`tests/test_managed_controls.py` covers the distinct executable revocation-only
workflow: frozen/session-bound policy RETIRE, strict current role/CSRF/scope,
same-key retry/new-generation safety, concurrency, paused/disabled/protected/
missing targets, uncertainty/receipt validation and audit rollback. Waiting
cancellation tests owner/Admin, promotion conflict, unknown response/retry,
unchanged running ADD and separate one-time jobs, optional schemas and no new
work signal. All data/actors are synthetic. Chromium checks frozen retirement
token/input/focus and AJAX cancellation without navigation/device hints. See
[Managed Controls](managed-controls.md). Combined removal confirmation stays 503.

`python3 -m pytest -q tests/test_managed_shuns.py` exercises only temporary
SQLite: explicit empty initialization without legacy adoption, canonical managed
mode, current roles, UUID/digest binding, optimistic concurrency, idempotent
replay across retirement/re-enable, whole-batch rollback and caller-owned
savepoint failures, limits/retirement reserve, complete 1000-target views,
retention, restart and SQLite backup. The API now uses optional reads only;
neither normal startup nor the worker initializes/writes managed policy.
No FTD, deployment secrets or local .env is read. Its database tests run within
the ordinary filesystem sandbox; full ASGI/socket regressions may still require
local permissions. See [Managed Shuns](managed-shuns.md) before integration.

`tests/test_managed_view.py` covers optional missing/partial-schema reads,
authentication/all-role visibility, escaped author/metadata, no forms/writes or
refresh hints, observed/retired transitions and version consistency. Package
version lives only in `ftd_shun_manager.__version__`; Hatch reads that field for
wheel metadata and Jinja uses it for every page footer. Update that source on
a release, not separate template/configuration constants. It is not a readiness
badge or live feature indicator. Chromium checks footer placement on desktop/
mobile, the five-tab navigation and revision-driven read-only managed updates.

See [Versioning](versioning.md) for manual release numbering, the pre-1.0
compatibility convention and planned (not implemented) development-build identity.

`tests/test_queue_transactions.py` uses temporary SQLite to verify caller-owned
admission, invisible pre-commit state, savepoint/outer rollback, audit/commit
failure, unchanged authorization/limits/coalescing, and shared atomic retirement
plus queued removal. Tests deliberately retain QUEUED/RUNNING ADD conflicts;
ordinary admission does not invoke the offline coordinator. Returned
accepted logs belong to the caller and must not be emitted before outer commit.
No test in this module opens a device socket or dispatches a command.

`tests/test_managed_removals.py` tests the separate single-target offline
coordinator with real temporary SQLite/queue and synthetic typed outcomes.
It covers RUNNING/no-overlap, verified/no-op/uncertain completion, exact pre-write
deferral, lease recovery, original expiry/cancellation, full rollback, parallel
replay, shared reservations/rate/capacity, generation/key safety and retention/
backup. Startup/API never initializes or admits handoffs; the default-off worker
can advance existing waits before its leased cutoff. See
[Managed Removal Handoffs](managed-removal-handoffs.md) before integration.

`tests/test_recovery_controls.py` covers composite offline suspension, original
uncertainty, atomic audit rollback, private checked/no-overwrite backups,
concurrent-commit refusal, restart durability, resume without resurrection,
paused monitoring/protected-policy suppression, strict default-off worker
configuration and shared lease/cutoff/fresh-snapshot/error behavior. It uses
disposable SQLite and synthetic agents only. See [Offline Recovery](recovery.md).

`tests/test_managed_review.py` covers the optional GET and non-executable Web
review: authentication/current role/CSRF, strict fields/scope/reason, immutable
subject/cookie/expiry-bound reviews, concurrent cache bounds, malformed optional
state, escaped outcomes and unconditional 503 on confirmation, even when an
upstream flag claims enablement. Tests never call the coordinator from Web or
admit live work. Chromium checks frozen token/input/focus and handoff color/state
updates using local fixture rendering only. See [Managed Removal Review](managed-removal-review.md).

Browser confirmation tests in `test_import_review.py` use synthetic ASGI/SQLite
only. They cover frozen exclusions/targets, escaped metadata, current trusted
identity/role and CSRF, unknown fields/counts, subject/cookie/expiry binding,
concurrent bounded cache admission, exact key/body retry after a committed but
lost reply, malformed response uncertainty, disabled intake and atomic policy/
device/opposite-intention rejection. Queue-reason checks retain real deferrals
and audit. Chromium exercises the actual review template, disabled button,
native count validation, token/input/focus retention without POST-view GETs,
live status and 375px layout. See [Browser Import Review](import-review.md).
These tests do not enable ADD or submit any work to the lab stack.

## Prerequisites

- Python 3.12+
- Rust 1.89+ for the privileged agent
- A virtual environment
- Docker Compose or Podman Compose only for container-level validation

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
export FTD_SHUN_DATABASE="$PWD/.local/state.db"
export FTD_SHUN_API_SOCKET="/tmp/ftd-shun-api.sock"
export FTD_SHUN_WEB_SOCKET="/tmp/ftd-shun-web.sock"
export FTD_SHUN_AGENT_MODE=mock
export FTD_SHUN_DEVELOPMENT_AUTH=true
```

Start the internal API and BFF in separate terminals:

```bash
.venv/bin/ftd-shun-api
.venv/bin/ftd-shun-web
```

For local browser work, proxy the Web/BFF Unix socket with Caddy or use a test client that sends `X-Dev-User` and `X-Dev-Groups`. `FTD_SHUN_DEVELOPMENT_AUTH=true` is forbidden in deployed environments.

## Safety boundaries

- `mock` accepts the typed `LIST_SHUNS` and `REMOVE_SHUN` operations; it returns an empty snapshot and never opens an SSH connection.
- `disabled` is the safe default and returns an error for every removal attempt.
- `socket` is the only deployment mode. It requires an FTD agent on `FTD_SHUN_AGENT_SOCKET` to return the exact verified-success result. Default legacy removal uses one byte; experimental cycles use the versioned response envelope.
- No interface accepts executable Cisco CLI. Import preview accepts untrusted
  paste as data only; no raw text or comment reaches the agent.

## Checks

```bash
.venv/bin/python -m compileall src
.venv/bin/pytest
.venv/bin/ruff check .
docker compose -f deploy/compose.yml config
```

## Agent checks

The [addition contract](addition-contract.md) has an offline evidence model
in `agent/src/addition_contract.rs`, compiled only with `cfg(test)` and excluded
from release agents. Its parsers are now shared with gated production ADD;
the model itself has no sender/socket or queue linkage. Regressions
check exact recorded acknowledgement, fresh source-only verification, no-op
without ownership for pre-existing targets, wrong scopes/fields/targets, partial
success, controls/Unicode, duplicate output and bounded evidence. Python/Rust
boundary checks keep ADD outside legacy RPC/v1/v2 and require explicit v3,
agent flags and per-device scope before SSH. Shared v3 vectors and real local
SeqPacket tests cover mixed requests, exact responses, no fallback/replay,
lost/malformed results and complete 20,000-entry streams. Fake consoles verify
combined mutation limits, command/time/END reserves, pre-existing no-op,
capacity/profile rejection and uncertain post-write outcomes. The API still
constructs v1/v2 clients even if the new agent flag is present. These tests are
not live addition, timing or data-plane validation.

[Large snapshot](large-snapshots.md) tests share fixed v2 wire vectors across
Python/Rust, collect 7,307/20,000 synthetic entries over real temporary
SOCK_SEQPACKET sockets, and test exact bounds, chunk splits, digest/order/
binding/EOF/truncation rejection, absolute transfer deadlines and preservation
of prior SQLite state on an incomplete empty stream. Legacy vectors and v1
mutations remain covered. Both new production selectors default to false.
The tests do not create shuns, contact FTD or establish live large-load behavior.

```bash
cargo test --manifest-path agent/Cargo.toml
```

The agent test suite covers strict binary request decoding, the typed `LIST_SHUNS` response, and fail-closed parsing of `show shun` output. Do not use `mock` to validate Cisco behavior. The actual agent requires recorded, sanitized device output and a non-production FTD lab.

Experimental session-cycle tests share fixed wire vectors between Python and
Rust. They exercise sequence/version/length rejection, one Unix connection,
truncated responses, count/command/time limits, pre-write deferral, unknown
interfaces, and failed verification. Scheduler fixtures cover bounded batches,
safe priority checkpoints, recent-snapshot coalescing, mid-cycle admissions/
cancellation, independent snapshot publication, and retained verified results
after later failure. These are fake-console/transport tests, not live SSH
compatibility evidence. The opt-in flag remains false until the
[cycle laboratory procedure](agent-cycle-protocol.md#migration-and-laboratory-validation).

## Browser refresh regression checks

The [Import Preview manual](import-preview.md) documents its independent
preparatory boundary. Parser tests cover literal/list/comment/free-text rules,
ambiguous and unsupported forms, no substring extraction, duplicate references,
UTF-8/line/row/body/pair limits and maximum-length hostile tokens without
unbounded regex backtracking. API/BFF checks cover explicit enabled targets,
snapshot classification, CSRF/escaping, chunked-body limits, no queue/audit/agent
side effects and no raw-source forwarding to the internal API. They also cover
large synthetic batches up to 10,000 rows, complete classification before
100-row pagination, retained HTML errors for oversized decoded text and worst-
case percent-encoded UTF-8. Browser tests paste a 7,307-row synthetic list with
real input events, navigate result pages and block oversized multibyte input
without truncation, queue admission or device execution. The browser scenario
checks every preview outcome, escaping and draft/result/focus retention
through metadata updates without extra parses, hints or execution.

With Node.js 22+ (built-in WebSocket support), Chromium, and the Python package
available in the same environment, run:

```bash
node --test tests/browser/freshness.cjs
```

Set `CHROMIUM` to the Chromium executable if it is not `chromium-browser`.
The test uses the real repository templates and freshness JavaScript, an
ephemeral localhost server with synthetic status/state, and a temporary browser
profile. It requires local socket binding and Chromium's sandbox support; it
does not use Docker, `.env`, real authentication users, or FTD connectivity.
No npm installation is needed.

Scenarios cover a single manual request, a slow in-flight status response,
multiple tabs, imminent-baseline display, repeated identical failures, API
restart, status/network recovery, failed POST/retry, and preservation of search
text, expanded history, confirmation values, and focus during partial updates.
Python tests separately exercise the real scheduler's slow-cycle coalescing,
partial fleet success, detached revisions, and BFF authentication/CSRF/no-store
boundaries. The browser fixture is not evidence of live FTD or Authelia
compatibility; that remains an integration/laboratory check.

Staged admission tests use only synthetic SQLite/ASGI state: parallel actors,
atomic opposite-action rejection/overflow, canonical confirmation and immutable
replay, policy edits, expiry/lease loss, legacy schema/claim/state-writer guards,
per-occurrence provenance, retention and bounded 1000-target metadata. A normal
scheduler observation cannot execute a held ADD or assign origin. API responses
cover nested provenance; Chromium covers held/cancellable rows, escaped details,
blue badges and their disappearance after a new external occurrence. Future
completion hooks are invoked with synthetic typed results, never actual ADD.
See [Import Admission](import-admission.md); do not use private API requests as
an independent live writer or turn on gates just to run tests.

[Queued execution](import-execution.md) tests cover profile-bound v3 selection,
common ADD/REMOVE FIFO and 16-step/cooldown bounds, held jobs on ordinary devices,
policy changes, per-claim expiry including coalesced actors, priority reads,
cancellation and cutoff, exact deferral versus unknown results, later final-read
failure, restart/shutdown/lease recovery without replay, and actual local
SeqPacket worker success/lost-response conversations. Synthetic admission tests
check eligible new work versus held/replayed requests and metadata. Chromium
checks held/running transitions, indeterminate ADD progress and readable phase
text. These tests do not read `.env`/lab inventory, SSH credentials or actual FTD.

Queue coverage also exercises simultaneous SQLite admissions, atomic overflow,
idempotent replay after completion, scope binding, cancellation ownership,
expiry, one executor/cycle gate, abandoned-write recovery, policy changes,
retention, and the documented restore SQL. API tests verify that a 202 response
does not execute a write and that only the scheduler dispatches the fake agent.
The Chromium fixture covers queue progress/cancellation and idempotent retry
after an admission reply is lost and a dynamic render replaces the form.

Queue display regressions check independently bounded active/attention/recent
results, RUNNING-first ordering despite a large backlog, totals versus visible
rows, collapsed completed results, active-to-completed transitions, IP-history
links, and disclosure state across dynamic updates. Display changes never
delete stored jobs or alter execution.

Request-progress tests distinguish actual linked-job totals from historical
counts and per-cycle caps, processed versus verified outcomes, cancelled
coalesced requesters, bounded 20-request summaries, and consistent snapshots.
Chromium checks determinate request bars, indeterminate running commands,
warning outcomes, phase changes without false advancement, stable indicator
nodes across differently ordered JSON, and removal of settled progress cards.

Protected-policy tests cover SQLite-only runtime settings, atomic once-only
legacy import (including empty/invalid input), deletion across restart, parallel
revision conflicts, authentication/CSRF boundaries, actor attribution, protected-only
search, and policy revalidation before each claim. Chromium also checks menu
keyboard/Escape/outside-click behavior, narrow viewport bounds, persistent
warnings, progress spacing, separate history updates, per-IP drafts with original
revisions, escaped labels and the protected-IP add/edit/disable/delete flow.
Display regressions cover enabled/disabled badges, active versus inactive
observations, disabled protection in search/shun/detail views and live badge
transitions without policy writes, audit changes or refresh hints. Chromium
checks the actual green/red styles and revision-driven warning replacement.

Protected-IP authorization now intentionally permits every authenticated user:
Viewer, Operator, Administrator and users without a mapped group. Parameterized
BFF/API cases verify those paths, unchanged actual-role audit, denial of blank/
anonymous identities, CSRF and spoofed form identities. The real Chromium CRUD
scenario uses Operator. Manual shun-removal/queue ownership tests remain strict;
shared policy access does not promote roles or grant cross-user cancellation.

History tests cover fixed 100-row pages, stable timestamp ties, no overlap,
new inserts outside an anchored browsing window, retention/clamping/expired
anchors, empty state, restored hex UUID IDs, concurrent count/row consistency,
bounded query validation and BFF authentication/canonical links. Chromium
navigates a 251-event fixture, observes the live 252nd event without moving an
older page, and measures unchanged search coordinates during refresh, device/
queue errors and network failure at 1100px and 375px viewport widths.
