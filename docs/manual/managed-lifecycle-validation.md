# Managed Shun Lifecycle Validation

## Current result — completed 2026-10-19

The complete operator lifecycle now passes locally through the real offline CLI,
Web/BFF, private API and shared scheduler, backed by disposable SQLite and a typed
fake console. This validates integration; it does not exercise SSH, Cisco parsing,
FTD traffic or an actual reboot. Separate live evidence now covers the one-time
experiment of 2026-10-16 and the managed lifecycle below.

The completed experiment used **one managed address on one laboratory FTD**.
The operator explicitly approved the concrete scope below on 2026-10-19,
including migration, temporary capabilities and the trusted-host submission
path. The operator subsequently supplied Basic-session absence and confirmed
the fixture is unused on the desk lab with only management connected. Reviewed
migration and one standing grant completed; temporary execution began at
`2026-10-19T10:09Z` (window ends `11:09Z`). Initial ADD completed VERIFIED at
`10:10:26.130Z`, interface `management`. The operator independently confirmed
presence, removed the exact management row once and confirmed absence while
API/Web were stopped and the executor settled. API/Web resumed at approximately
`10:12:43Z`; the complete `10:12:52Z` snapshot confirmed absence with a legitimate
restoration backoff hold. The next baseline admitted one new attempt, completed
VERIFIED at `10:19:16.627Z` on management with unchanged intent/generation.
The operator independently confirmed restored presence. Original-key combined
cleanup retired policy at `10:22:43.999Z`; REMOVE completed VERIFIED at
`10:24:05.666Z`, followed by independent Basic-session absence. Original grant
replay returned only its historical receipt, and an API/Web restart did not
re-enable policy or re-add the fixture (`10:25:17Z` successful read). Two scheduled
baselines completed at `10:30:26Z` and `10:38:47Z` with no re-add. Checked offline
suspension/ordinary resume and removal of temporary configuration closed the
window by `10:41:21Z`, before its deadline. All experimental gates/profile are
off; desired restoration is suspended, ordinary monitoring/work available and
final successful read `10:41:03Z`. Seven optional tables, retired policy,
verified attempts, history and private before/after backups remain retained.
The scoped authorization is consumed. Future runs need a new reviewed fixture
and explicit activation approval; neither this procedure nor a successful result
authorizes general restoration, bulk imports, traffic or production use.

## Repeatable local acceptance

Run from the repository root:

```bash
python3 -m pytest -q tests/test_managed_lifecycle.py
```

The seven cases exercise:

| Scenario | Required result |
| --- | --- |
| Single-device and two-device lifecycle | Checked CLI migration, browser standing consent, separate policy resume, fresh absence, next-cycle ADD, disappearance/restoration, reviewed cleanup, restart and no re-add. |
| Protected IP while ADD is queued | Atomic cancellation; maintenance stays visible; unacknowledged weakening refuses; reviewed weakening allows fresh discovery; renewed protection removes the present shun. |
| Lost ADD reply after simulated mutation | Retained UNVERIFIED survives presence, absence and API restart; no repeated ADD; attention identifies the case and offline policy resume refuses. |
| Single-device and fleet cleanup with one lost REMOVE reply | All reviewed policies remain retired. Later absence is RECONCILED_ABSENT, while independently verified members retain VERIFIED; no fabricated successful-removal event for the uncertain member. |
| Controller disabled between discovery and dispatch | Pending job and original request/deadline survive unchanged; re-enabling within its validity dispatches that job once. |

The clock is controlled to exercise the persisted 60-second cycle gate and
300-second restoration backoff without sleeping. Fake device state changes only
through typed fake methods or an explicit simulated disappearance. Migration,
pause/resume, grants, revocation, attempts and job outcomes use production entry
points; tests do not patch policy/queue tables to manufacture success. Each
offline mutation takes a checked, exclusive 0600 backup in a private directory.
No lab environment file, credential, volume, SSH or agent socket is used.

The successful path also closes the simulated window: desired policy is
suspended, ordinary mutation handling is resumed, experimental admission/worker/
controller capability is disabled and normal monitoring cannot re-add the retired
address. Original grant replay is checked before the admission gate closes.

## Approved lab scope — 2026-10-19

- Device: `1`, `fpr1010-lab`, the previously validated FPR1010 / FTD 7.6.6 Basic
  profile `fpr1010-766-single-vf-management-v1`; recheck identity/version/role.
- Address: unused TEST-NET `198.51.100.252`, expected `management` interface.
  Confirm it is not used by management, users, probes or other lab traffic.
- Window: at most 60 minutes after activation. One standing intent, one initial
  verified ADD, one deliberately induced disappearance, one verified restoration,
  one final combined device-scoped retirement/removal and no-readd observation.
- Initial optional migration: the seven base managed tables, using reviewed
  offline initialization and private backups. No closure-ledger migration.
- Temporary capability/profile changes are limited to device 1 and the settings
  below. One-time import admission stays off. Other administrators must leave
  grants, queue, fixture and profile settings unchanged during the window.
- Submission uses the operator's real authenticated Web session, or an explicitly
  approved trusted-host actor `maintenance:managed-lifecycle-validation` with
  Operator authority limited to this fixture. Never spoof an Authelia identity.
  The private API path does not establish live browser-authentication acceptance.
- The operator performs the single external disappearance in the existing Basic
  SSH session while the service executor is stopped and prior RPCs settled.
  This represents external loss; a physical reboot is not needed or covered.
- Finish with retired policy and immutable evidence retained, desired restoration
  suspended, experimental gates/profile restored off, ordinary monitoring working.
  Optional schemas remain initialized; rollback does not drop evidence or restore
  an old database over the new authority/history.

### Prepared read-only evidence

Post-approval preflight at `2026-10-19T10:02:59Z` reconfirmed cached fixture
absence, no protection or previous fixture jobs, no unfinished/uncertain work,
no managed tables/profiles, all experimental gates off and healthy monitoring
(last normal read `2026-10-19T10:00:15Z`). A checked exclusive 0600 SQLite-API
backup and matching API/Web/agent rollback tags were retained before activation.
See the development log for exact artifacts. Services remain running unchanged.

At `2026-10-19T09:40:41Z`, the API's local state showed device 1 enabled,
`198.51.100.252` absent/unprotected with zero historical jobs, zero unfinished or
uncertain fleet jobs, no optional managed tables, no eligible addition profiles
and SQLite quick-check `ok`. Cycle/large-read capability was enabled; all import,
standing, controller and cleanup gates were false. Last successful normal read:
`2026-10-19T09:39:38Z`, no error. This inspection requested no extra device read.

These are dated cached observations. Repeat the checks before setup. Obtain a
fresh Basic-session `show shun 198.51.100.252` with only a normal prompt and verify
the address is unused. Any pre-existing row, protection, unrelated pending work,
unknown state or different device/profile stops preparation; do not clear it to
make the experiment fit.

## Execution sequence after approval

### Restart caveat observed during this experiment

For already initialized lab volumes, restart only the reviewed services with
`docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.local-lab.yml up -d --no-deps api web`.
During the experiment, bare `compose start api web` also started the former
`socket-init` dependency. Its recursive state-volume chown failed on private
0700 backup directories under its restricted capabilities. Do not loosen backup
permissions or grant broad capabilities to work around it. Existing volumes and
socket ownership must already be valid; `--no-deps` is not a fresh-install recipe.
The root-only initializer fix was validated on disposable volumes and deployed
during final closure; the current lab initializer exits0 with private backup
modes/ownership intact. Older initializer containers still need recreation from
the new Compose definition. See [Deployment](deployment.md).

### 1. Prepare durable state and consent

Retain current matching API/Web/agent images, exact prior non-secret gate/profile
values and a checked SQLite-safe backup. Stop API/Web and settle all old agent
RPCs; stop the agent if settlement cannot otherwise be established. Follow
[Offline Recovery](recovery.md) to suspend, then
[Offline Managed Maintenance](managed-maintenance.md) to review/initialize the
empty managed schemas and resume ordinary mutations. Each control needs its own
new backup. Desired restoration remains suspended. Preserve unrelated history
and protection; recovery records changes to request/pause metadata.

Configure the exact addition profile on device 1 only. Enable
`FTD_SHUN_MANAGED_POLICY_ADMISSION_ENABLED` for the reviewed API/Web pair while
`FTD_SHUN_IMPORT_EXECUTION_ENABLED`, `FTD_SHUN_MANAGED_RESTORATION_ENABLED` and
`FTD_SHUN_AGENT_ADDITIONS_ENABLED` remain false. Use the real
[standing review](managed-grants.md) or [address-list review](managed-batch-grants.md)
with exactly one pair. Inspect normalized scope/metadata/digest, acknowledge
recurring maintenance and retain the original UUID/body/receipt. Verify one
enabled intent, suspended restoration and zero new jobs/device mutations.

### 2. Resume and observe initial creation

Stop API/Web again and settle RPCs. Prepare and apply `review-resume` /
`resume-policy` with its fresh five-minute digest and another checked backup.
This preserves the original intent/generation and installs the fresh-read barrier.
If blocked, stop; never alter timestamps, ledgers or outcomes to pass the review.

Coordinate API/Web/agent configuration: enable API import execution, managed
restoration, agent additions, managed removal worker and managed removal admission.
Keep cycles/large snapshots enabled and one-time import admission false. Start
the matching services with one executor. Agent recreation is necessary to apply
its profile/gate. Keep network, credentials, Basic role and host-key pins intact.

Allow normal cycles to discover absence and then dispatch at the next eligible
cycle. Verify system actor/original authority/intent/generation, unchanged bounded
request deadline, typed VERIFIED creation and a complete snapshot of the fixture.
Record an independent Basic `show shun 198.51.100.252`. A queued receipt, NOOP,
cached row or missing response does not satisfy creation acceptance.

### 3. Observe one restoration after external disappearance

Stop the API/Web executor and settle its last RPC. The operator executes exactly:

```text
no shun 198.51.100.252 interface management
show shun 198.51.100.252
```

Use these commands only after this experiment is authorized and initial creation
has been verified. Preserve standing intent; do not use service cleanup for this
step because it revokes maintenance. Restart API/Web with the same enabled test
configuration. Fresh complete absence must precede a new system attempt; the
existing 300-second per-pair backoff and >=60-second cycle gate remain in force.

Require one new VERIFIED attempt with the same standing intent/generation and a
new snapshot/job/occurrence. Preserve both original outcomes. Confirm presence
through the Basic session again. Stop if another unexpected attempt is admitted,
an outcome is uncertain or unrelated work appears. No automatic retry or NOOP
substitute for the required evidence.

### 4. Retire, remove and close the window

Use the [combined device cleanup](managed-cleanup.md) review for device 1 / the
fixture. Confirm current intent/generation and original cleanup UUID. Verify
atomic retirement/admission, then a VERIFIED queued removal and complete absence.
Confirm independently with Basic `show shun 198.51.100.252`.

Wait for two complete scheduled baseline cycles after removal and include an
API/Web restart. There must be no new restoration job and no re-add. Deliberate
original-grant-key replay, while admission remains enabled, must return only its
historical receipt and leave policy retired. Do not prepare a replacement grant.

An interactive read can move the next baseline deadline. If browser activity
keeps shifting it, stop only Web while API continues normal monitoring; record
the new due time and wait for actual scheduled completion. Do not shorten the
interval, force device reads or count a merely expired timer as a complete cycle.
Restore Web during final disabled-mode closure.

Stop services and settle RPCs. Use checked offline `suspend` then reviewed
`resume-mutations` to leave desired policy suspended but ordinary work available.
Restore only test-specific gates/profile to their prior values, including the
agent addition gate, and recreate matching affected services. Verify healthy
normal monitoring, retired intent, no pending work, retained audit/attempts and
unchanged unrelated policy. Keep the initialized schema and receipts; do not
restore the pre-test database as routine cleanup.

## Failure handling and recorded acceptance

On unexpected scope, parser/host-key/transport failure, FAILED/UNVERIFIED result
or unrelated work, stop expansion of the experiment and settle/suspend execution
using the existing recovery procedure. Record exact attempt/job IDs and honest
observed state. Do not rekey, replay uncertain ADD, delete evidence, enable
closures or grant a fresh generation. Fixture cleanup after uncertainty needs
an explicitly reviewed plan; the successful-path procedure must not imply a
successful cleanup when its evidence is missing.

Record UTC times, image IDs, gate/profile changes, private backup locations,
original consent/intent/generation, both verified ADD attempt IDs, external-loss
evidence, final cleanup result, no-readd reads and restored configuration in the
development log. Keep credentials/raw console output out of the repository.
Passing this one-fixture test establishes only this managed CLI lifecycle;
bulk/load, traffic, real reboot, fleet failure recovery and production acceptance
remain separate work.
