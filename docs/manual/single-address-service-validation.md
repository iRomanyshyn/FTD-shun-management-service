# One-Address Service Validation — Scoped Laboratory Procedure

## Status and authority

**Completed for one approved fixture; ADD restored disabled (2026-10-16).**
The operator requested preparation of the next scoped test. Standing code
deployment permission does not authorize enabling ADD, changing inventory,
admitting a test mutation or cleaning up a pre-existing shun. This document is
a runbook, not a script or automatic permission to execute it.

The operator subsequently explicitly approved this exact one-address scope and
provided fresh `show shun 198.51.100.251` returning only the normal prompt.
Only this isolated CLI-lifecycle experiment is approved: one temporary addition,
no-op/replay checks and scoped cleanup, then restore ADD-disabled operation.
Trusted-host submissions use `maintenance:single-address-validation`, displayed
as Operator-approved lab validation with the explicitly granted Operator role;
this is not an Authelia principal or fabricated authentication session. Cleanup
may use the same private queued API when the assistant runs the approved test.
Broad traffic/load/production gates remain unsatisfied. Observed results are
recorded at the end; this completed authorization does not permit another test.

Before proceeding obtain fresh device evidence and explicit approval naming
the non-production device, unused fixture IP, temporary gate/profile changes,
one service creation, one already-present/no-op check, and device-scoped cleanup.
Approval must also cover the private maintenance submission identity and test
window. If scope, creation profile or remaining validation gates are disputed,
resolve them before changing configuration. No long list or production traffic.

The proposed fixture is device ID `1`, displayed as `fpr1010-lab`, and
`198.51.100.251`. The expected profile is
`fpr1010-766-single-vf-management-v1` on the previously reported FPR1010 / FTD
7.6.6 / Basic login. These are proposals and earlier observations, not fresh
model/role verification. Stop if the actual device, role or version differs.
An observed `management` row is CLI lifecycle evidence, not data-plane proof.

## 1. Read-only preflight before approval

In the operator's Basic SSH session, run only:

```text
show shun 198.51.100.251
```

Return to the normal prompt with no row means observed absence. An error,
disconnect, unknown text or unexpected prompt does not. If a row exists, stop:
do not remove/relabel it to make this test pass. Reconfirm that the address is
unused by management, VPN users, probes and other lab traffic, and confirm the
current model/version/Basic role. Share only relevant sanitized evidence, never
passwords, host keys, serial numbers or configuration exports.

Read the existing service cache/policy/queue locally without a refresh hint or
independent agent request. Confirm target device enabled, fixture locally absent,
no enabled protection, no unfinished target job and no unrelated unfinished work
that temporary enablement could execute. Check ready/fresh device status and
SQLite integrity. Cached absence is not fresh device absence; neither alone
grants change authority. Repeat preflight if approval or setup takes time.

### Prepared observations — 2026-10-16T16:54:07Z

- Device `1` is enabled with display hostname `fpr1010-lab`.
- Fixture is absent in local active state; enabled protection is false.
- Unfinished fixture jobs: zero; all unfinished jobs: zero.
- API admission/execution are false; eligible ADD device count is zero.
- Session cycles and large reads are enabled; SQLite quick_check is ok.
- Device ready with no error; last successful normal observation was
  `2026-10-16T16:52:34Z`.

These time-bound cached checks did not open SSH, submit work or read confidential
inventory. Fresh Basic-account target absence, address-unused confirmation and
explicit scoped change approval are still pending. No live ADD result exists.

## 2. Controlled setup — only after separate approval

Review the [addition gates](addition-lab-validation.md),
[exact verification contract](addition-contract.md) and
[worker contract](import-execution.md). This proposed first service experiment
can establish only the small CLI lifecycle. It cannot waive traffic/scope,
large-population, production or broad-import gates. Any exception for this
limited validation window must be explicitly approved and recorded, not inferred
from this runbook or general deployment permission.

Take a fresh checked SQLite-safe backup and preserve the current paired images.
Keep a protected record of prior values so only test-specific changes are
reverted; do not overwrite entire configuration files with an old copy. Confirm
the queue is still empty and other administrators will not modify the fixture.
Do not disable fleet policy or broaden network/SSH privilege to pass the test.

Under the approved change, configure the recognized addition profile for **only
device 1** without changing target address, host key or unrelated allowlists.
Temporary API admission/execution and agent ADD gates must be coordinated with
the existing socket/cycle/large-read prerequisites. An API restart alone does
not apply the agent's gate/profile. Stop the sole API executor cleanly before
agent replacement/recreation; ensure no old RPC survives. Never run another
writer or direct cycle client beside the leased worker.

After controlled restart, inspect only safe status metadata and normal cycle
results. Expect one eligible device and a successful v3 initial/final read with
no mutation. Failure before mutation is a stop, not permission for fallback,
reconnect/replay, parser relaxation or promotion from Basic to Config. A normal
baseline read can establish the small population; do not force extra SSH reads.

## 3. One admission, idempotent retry and verification

There is no executable browser import yet. For this maintenance experiment,
use only the trusted host/private API admission route, through the API container;
never direct agent RPC, a public API or spoofed Web authentication headers.
Use an explicitly approved identifiable maintenance actor with its real granted
role, marked as laboratory validation in batch metadata. Do not invent an
Authelia login, session freshness, or another user's identity. This experiment
does not validate the browser authentication/admission workflow.

Freeze one canonical target `(1, 198.51.100.251)`, reviewed policy revision,
label/reason and a generated UUID idempotency key **before** the first POST.
Retain the exact original typed body/key privately for retries. Submit exactly
one `POST /api/v1/imports`; a digest binds intent but is not authorization.
`202` is acceptance, not creation. Poll local status/history only and respect
the persisted cycle eligibility; do not submit refresh hints to speed it up.

Expected evidence:

- One ADD job becomes RUNNING, then VERIFIED under a v3 cycle.
- The strict agent verifies expected acknowledgement and one source-only
  `management` row; no generic command/interface enters admission.
- The current occurrence has `manual_import_count=1` and the blue
  **Manually imported** badge with the approved batch/actor details.
- Retained audit contains `SHUN_ADD_REQUESTED`, queue transitions and
  `SHUN_ADDED_BY_IMPORT` for the same batch/job/fixture.
- The operator independently reads the same target after the cycle is idle:
  `shun (management) 198.51.100.251 0.0.0.0 0 0 0`.

Retry the original exact body/key only to establish `replayed=true`, the same
parent ID and no new job/write/origin. Do not regenerate a key after a timeout.
Unknown/missing result is UNVERIFIED, never success by later presence. Stop,
inspect read-only evidence and obtain a cleanup decision if creation is uncertain.

## 4. Already-present/no-op check

Only after verified creation, unchanged expected target state and explicit
approval for this check, submit the same one target with a **new** UUID.
Review current policy and canonical confirmation again; never broaden the scope.
Expected terminal state is NOOP: the agent performs a fresh target read without
another creation command. Existing occurrence/batch origin remains unchanged,
count stays one, and the second request gets `SHUN_ADD_NOOP`, not a new
`SHUN_ADDED_BY_IMPORT` claim. Idempotent retry and already-present no-op are
different checks and use different key rules.

Do not attempt no-op after disappearance/removal: a new key then requests actual
creation again. Unexpected state or another administrator changing the fixture
requires a stop and review, not automatic repair.

## 5. Scoped cleanup and no automatic re-add

After the verified/no-op jobs are terminal, use either the authenticated existing
Web device-specific removal action or the separately approved private queued
device-specific API with the same declared maintenance actor. Record which was
used; only an actual Web submission establishes real browser-user attribution.
Do not use remove-all, clear-all,
raw CLI writes or a new writer as routine cleanup. The removal uses the same
leased worker, cooldown and verification; wait for its terminal result.

After VERIFIED cleanup and an idle cycle, independently run the target read in
the Basic SSH session. Expect absence, inactive local state and verified removal
audit. Before disabling admission, retry the **original completed creation**
body/key once: expect replay of its old reference and no new job/re-add. Never
use a fresh key for that test. Normal later reconciliation must preserve absence.

Revert only approved temporary gate/profile changes to their captured prior
values and coordinate API/agent restart with no in-flight work. Keep the new
audit/provenance history and additive schema; do not restore the database to
erase evidence. Wait for a normal disabled-mode cycle after restart and confirm
absence/no new ADD. Admission disabled may return 503 even for an old key; that
is why the explicit replay check happens before disabling it.

If a write or cleanup is UNVERIFIED, do not blindly repeat it or restore a
backup. Determine current target state read-only and retain the uncertain event.
A separate operator-approved cleanup may be necessary. Close unused gates and
review pending work safely under the queue recovery procedure. Never remove a
pre-existing or unexpectedly scoped row without a separate decision.

## 6. Evidence and remaining gates

Record actual UTC/timezone-labelled times, fresh model/version/role, approved
scope, canonical batch/job IDs, v3 cycle version/commands/timing, terminal states,
badge/origin assertions, idempotent/no-op distinctions, independent device reads,
cleanup and restored configuration. Sanitize unrelated addresses/hostnames and
exclude credentials, inventory, full production logs and private backups from Git.
Append confirmed results or failures to status/development log, never predictions.

Passing this test is small-population service/CLI evidence only. Data-plane
blocking, fleet creation scope, real large snapshots, priority under long imports,
multi-user live failures, executable BFF submission and 7,307-address scheduling/
reauthorization remain separate gates. Do not leave general ADD enabled simply
because one TEST-NET fixture passed.

## Recorded service result — 2026-10-16

The separately approved experiment completed on device 1 using the existing
ftd-shun-lab account and the declared maintenance actor. Model/version/Basic role
use the operator's earlier FPR1010 / FTD 7.6.6 profile and matching configured
account, not a newly added generic CLI probe. The operator supplied fresh target
reads before creation, while present, and after cleanup:

```text
> show shun 198.51.100.251
>

> show shun 198.51.100.251
shun (management) 198.51.100.251 0.0.0.0 0 0 0

> show shun 198.51.100.251
>
```

| Phase | Observed result | UTC completion / evidence | Agent commands / cycle time |
| --- | --- | --- | --- |
| Initial ordinary v3 read | Complete, fixture absent, zero mutations | API success 17:03:14Z | 2 / 8972 ms |
| One queued creation | VERIFIED, management, one origin | Job 17:05:24.909Z; SHUN_ADDED_BY_IMPORT | 5 / 15490 ms |
| Exact original-key retry | Same parent, replayed=true, one linked job/origin | Private API assertion passed | No new cycle/write requested |
| New-key already-present check | NOOP, original origin count remains one | Job 17:07:06.477Z; agent.add_shun.noop | 3 / 11276 ms |
| Scoped queued removal | VERIFIED; final snapshot and operator read absent | Job 17:08:25.948Z | Metrics not captured before agent recreation |
| Original creation key after cleanup | Old reference, no new job or re-add | Total jobs remained 9, unfinished zero | No new work requested |
| Restored ordinary v2 read | Complete, absent, zero mutations | API success 17:11:13Z | 2 / 8997 ms |

Creation request/job IDs:
`cf13f6de-9eb8-4461-9713-497bd820606a` /
`ed1effdf-8e3d-467f-9e68-98cb57081641`.
NOOP request/job IDs:
`8aa0f424-0ece-4f2c-a904-9ae5ff4f0437` /
`60efa008-f1d1-4004-b425-576be53bfcd1`.
Cleanup request/job IDs:
`d42bb709-f9a2-471a-bd5c-0843d50867ac` /
`bf6716af-c8cd-4909-8c84-57acabd780b9`.

Both mutations and the no-op used private semantic API admission under the
maintenance actor, not forged Web headers or direct agent requests. Cleanup
uses the existing SHUN_REMOVED_BY_UI event name, but its actual caller was this
explicit maintenance actor; authenticated browser submission/visuals were not
independently checked by the assistant. The API exposed one current origin and
its batch metadata while present; after cleanup no active row/badge remains.
Inactive occurrence provenance and all three job/audit records survive restart.

A private local Compose override temporarily enabled gates. Only device 1's
profile was added; .env was untouched. API was stopped before each agent
recreation. After terminal cleanup, the profile was removed and the original
inventory/.env bytes verified by checksums; the override was disarmed and normal
base lab configuration restored. No image/source/schema changed; Web/Caddy/
Authelia IDs were untouched. Retained checked SQLite-safe backup:
`.local/backups/state-before-single-address-20261016T170037Z.sqlite3` (0600,
private 0700 directory), with image tags `before-single-address-20261016t170037z`.
Private request artifacts retain their exact keys/bodies, not source paste or
credentials; they are ignored and 0600, and the inactive override has all gates off.

At 17:11:48Z both API gates/client capability were disabled, agent ADD gate was
absent/default false, eligible count zero, fixture absent and unfinished jobs
zero. Original 61 active shuns and three policy entries/revision 3 remain.
Queue totals are eight VERIFIED and one NOOP (six pre-existing verified jobs
plus exactly these three test jobs). Backup comparisons confirm unrelated shun
state/stable dates/occurrence IDs, pre-existing jobs and policy are unchanged;
one inactive fixture origin is retained. quick_check is ok, foreign_key_check
has no rows, anonymous Web/status returns 401 and TLS-verified HTTPS redirects
to Authelia (302). No database restore or audit erasure was performed.

This closes the one-address service/CLI lifecycle and small-read v3 compatibility
test only. It is not traffic blocking, real large-load, live priority/failure,
browser authentication, fleet creation scope or production acceptance. Capture
sanitized operational evidence before future container recreation: Docker local
logs are container-scoped; removal cycle metrics were not retained here.
