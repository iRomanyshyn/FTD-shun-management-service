# Incident Isolation and Healthy Policy Resume

## Meaning and boundaries

`ISOLATE_INCIDENT` excludes the exact device/IP scope of an acknowledged ordinary
UNVERIFIED or single/fleet ATTENTION case from future manual device work. It
atomically retires currently enabled standing policy in that scope and retains
immutable pair latches, evidence and a receipt. Original outcomes, ATTENTION,
consent, requests, reservations and evidence holds remain. No release/rearm exists.

A fleet decision covers every original member, including missing current devices.
Captured ADDs keep their own outcomes. If an ADD also appears as an ordinary
UNVERIFIED case, it needs its **own** acknowledgment/isolation before healthy
policy can resume. Failed/uncertain restoration still needs its separate
[abandonment](managed-abandonment.md) and validated closure. Acknowledgment alone
changes no controls and grants no resume exception.

Existing restoration abandonment still refuses overlapping ATTENTION cleanup.
Such a combined restoration/cleanup incident therefore remains blocked in this
release; isolation does not manufacture a missing restoration closure or bypass
that guard. A separately designed whole-scope decision is needed for that case.

Isolated pairs cannot receive manual ADD/REMOVE, combined cleanup, MAINTAIN or
restoration, including later generations. Claims recheck the latch and cancel
old queued manual work. Protected automatic removal retains its independent
authority/priority. Read-only monitoring and policy-only retirement stay available.
Isolation is an operational exclusion, never proof that a device write succeeded.
There is no HTTP action or automatic migration/activation.

## Offline prerequisites

Follow [Recovery](recovery.md) and [Acknowledgments](incident-acknowledgements.md):
stop the sole API/Web pair, prevent automatic restart, settle all old agent RPCs
(stop the agent if necessary), and suspend ordinary and existing desired
mutations. An expired lease does not establish remote settlement. No pending
job/handoff/restoration, lease or incomplete fleet admission may remain.

Use the database owner's UID, matching current package, existing absolute
database/WAL path and private output handling. Initialize the acknowledgment
ledger separately and acknowledge the original case first. Every write creates
a checked exclusive0600 SQLite-API backup in an operator-owned0700 directory,
refuses concurrent commits, and retains its backup on failure. Select approved
real absolute paths before using these illustrative commands.

## Separate empty-ledger migration

```bash
ftd-shun-incident-maintenance review-enable-isolation \
  --database /approved/restored/state.db \
  --actor operator-label --confirm-offline

ftd-shun-incident-maintenance enable-isolation \
  --database /approved/restored/state.db \
  --backup /approved/private/backups/before-isolation-ledger.sqlite3 \
  --actor operator-label --confirm-offline --confirm-reviewed \
  --reviewed-at TIMESTAMP_FROM_REVIEW --review-digest DIGEST_FROM_REVIEW
```

Inspect readiness/blockers before confirming within five minutes. One transaction
creates only `incident_isolations`, indexed `incident_isolation_targets`, immutable
update/delete guards and `INCIDENT_ISOLATIONS_INITIALIZED` audit. Existing policy/
queue/controls remain. At most10000 receipts and10000 total target rows are retained.
Ordinary-only databases need no managed initialization. Startup/GET, Store/queue,
acknowledgment and managed migrations never create these tables. Changed/partial
DDL, orphan/count-mismatched latches or capacity refuse instead of shrinking scope.

## Review and isolate the entire original case

Inspect all [attention detail pages](managed-attention.md) and the administrative
acknowledgment. Prepare a distinct decision:

```bash
ftd-shun-incident-maintenance review-isolate \
  --database /approved/restored/state.db \
  --actor operator-label --confirm-offline \
  --case-id fleet_cleanup:ORIGINAL_ROOT_UUID \
  --reason "Exclude the entire reviewed scope; retain uncertain outcomes"
```

Inspect every returned target, original predecessor and current policy being
retired. The five-minute review binds full schema/queue/request/link/observation/
protection/managed context, acknowledgment, original scope, UUID, actor and reason.
Missing historical predecessors are explicit; inconsistent/unfinished evidence
refuses. Missing/disabled devices or protection never authorize a device write.

```bash
ftd-shun-incident-maintenance isolate \
  --database /approved/restored/state.db \
  --backup /approved/private/backups/before-isolation.sqlite3 \
  --actor operator-label --confirm-offline --confirm-reviewed \
  --case-id fleet_cleanup:ORIGINAL_ROOT_UUID \
  --reason "Exclude the entire reviewed scope; retain uncertain outcomes" \
  --request-id REQUEST_UUID_FROM_REVIEW \
  --confirm-ip EXACT_REVIEWED_IPV4 --confirm-target-count ENTIRE_REVIEWED_COUNT \
  --reviewed-at TIMESTAMP_FROM_REVIEW --review-digest DIGEST_FROM_REVIEW
```

All enabled standing policies in scope retire in one transaction, with one
registry revision when retirement occurs. Already retired targets keep their
dates; absent policy is never created. Every member receives its exact device/IP
latch even without current inventory. Sanitized evidence/request/receipt and
INCIDENT_ISOLATED audit commit together with a `maintenance:<label>` actor/empty
roles. Expiry or audit failure rolls back policy, receipt and latches together.

Changed state refuses without rebase. Concurrent original-key confirmations create
one receipt. Exact replay returns that historical receipt after expiry without
changing current policy/controls. Different input or a second key cannot replace
the decision. Isolation keys cannot acquire queue/policy/cleanup/restoration/
acknowledgment/abandonment authority. Preserve original requests after unknown
replies; use a new private backup filename for deliberate receipt retries.

## Resume other healthy standing policy

After all required decisions, follow existing reviewed ordinary mutation resume
while keeping API/Web stopped and desired restoration suspended. Then prepare:

```bash
ftd-shun-managed-maintenance review-resume-isolated \
  --database /approved/restored/state.db \
  --actor operator-label --confirm-offline
```

Require at least one isolation and one enabled healthy standing target. Every
remaining ordinary UNVERIFIED and ATTENTION cleanup case needs its own matching
isolation; every FAILED/UNVERIFIED restoration needs its own valid abandonment.
No lease, pending work, transitional root or additional uncertainty is excluded
automatically. Ordinary resume and restoration-only unrelated resume stay strict.

All receipts/scopes/latches, acknowledgments, exact retired or originally absent
policy and retained jobs/links are revalidated. Changed outcome/authority, extra
links, missing latches or enabled isolated policy refuse. Complete-read REMOVE
reconciliation may remain RECONCILED_ABSENT, never VERIFIED. Isolation holds the
original jobs/linked requests beyond queue retention, including reconciled REMOVE.
Old missing predecessors remain explicitly missing. Existing standing-authority,
device/protection/time checks and a fresh-read barrier still apply.

```bash
ftd-shun-managed-maintenance resume-isolated-policy \
  --database /approved/restored/state.db \
  --backup /approved/private/backups/before-healthy-resume.sqlite3 \
  --actor operator-label --confirm-offline --confirm-reviewed \
  --reviewed-at TIMESTAMP_FROM_REVIEW --review-digest DIGEST_FROM_REVIEW
```

Within five minutes, this atomic control/audit transaction clears desired
suspension and advances only healthy enabled targets' fresh-read barrier.
MANAGED_ISOLATED_POLICY_RESUMED records restoration exclusions and isolated scopes.
Retired policy, outcomes, receipts, gates/profiles and queue stay intact. No job
is queued/signalled; later execution needs independent gates and a fresh complete
snapshot. Another action's or an attention digest cannot authorize this command.

## Inspection, retention, rollback and validation

Attention keeps original cases/outcomes/counts with separate `isolation` status
and `incident_isolated` target context. A case can remain UNVERIFIED/ATTENTION
while acknowledged and isolated. No archive, rearm, release or force purge exists;
evidence/receipts can grow beyond the event-history window.

Keep paired matching images and checked backups. Older writers ignore these
latches: downgrade requires a separate offline plan. Never drop rows/triggers or
restore enabled policy to undo a decision. Lab deployment includes schema-absent
support only: no ledger migration, isolation/resume, grant, fixture or device-write
activation was performed. Operational activation needs separately scoped approval.

Disposable-state tests cover ordinary/single/fleet exclusion,205-member scope,
missing inventory, retirement/rearm refusal, independent uncertain ADD cases,
healthy resume, protected-removal priority, claim checks, stale/typed/expiry
conflicts, rollback, malformed latches, retained reconciliation, concurrent
original-key replay and checked CLI migration. Live recovery/fleet/load/traffic/
physical-reboot/production acceptance remains pending.
