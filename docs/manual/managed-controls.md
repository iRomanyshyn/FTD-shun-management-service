# Managed Controls — Revocation Only

## Supported actions and limits

The Managed shuns page now supports two local revocation actions. They do not
initialize optional tables, admit device writes, start SSH, request a refresh,
enable ADD or resume restoration. A GET or review preparation changes nothing.

| Action | Effect | Does not do |
| --- | --- | --- |
| Stop maintaining — policy only | Retire one exact reviewed device/IP intent under the registry revision. | Remove a shun, cancel one-time jobs/running ADD/separate cleanup, re-enable policy. |
| Cancel waiting cleanup | Cancel the owner's (or Administrator's) WAITING_ADD removal handoff. | Cancel its ADD, remove a shun, cancel a job already admitted to Queue, resume maintenance. |

These are not the combined **Stop maintenance and queue removal** workflow.
That separate [preparatory review](managed-removal-review.md) still always
rejects execution with 503. No managed creation/adoption/re-enable/resume route
exists. The controller remains unavailable, the cleanup-worker flag defaults
off and no managed policy/handoff tables have been initialized in the lab.
Do not seed live data to demonstrate controls or reuse the consumed ADD fixture.

Ordinary device/fleet removal now refuses an enabled managed target in its scope;
fleet checks include maintained-but-missing devices outside the observed list.
Stop maintaining the relevant targets first, then use ordinary removal as two
separate explicit actions until combined admission is released. A new MAINTAIN
cannot overlap a queued/running removal. Existing original-key replay is still
observational and does not submit work. Protected-IP automatic removal is a
separate higher-priority policy path and keeps desired intent blocked, not
retired; see [Protected IPs](protected-ips.md#managed-maintenance-acknowledgement).

## Stop maintaining only

On an explicitly initialized development fixture, open **Managed shuns → Stop
maintaining a target — no device command**. Choose one enabled managed intent
and optionally enter a plain-text reason (500 characters maximum). Missing
observations, enabled protection and disabled devices do not prevent revocation.

**Review stop maintaining only** freezes the exact pair, hostname, intent ID/
generation, managed revision, original reason, new request UUID/digest, local
observation and protection. No policy change occurs yet. Type the exact shown
IPv4 and confirm **Stop maintaining — do not remove shun**. Only the trusted
BFF supplies actor and frozen fields to the private policy-only API.

Current Operator/Administrator, session binding and CSRF are checked again.
A new request atomically checks the global registry revision, retires policy
and appends actor-attributed audit. It can run during a recovery mutation pause.
Unstarted one-time imports/removals and running commands keep their original
authority: inspect **Queue** separately if you also want cancellation. Future
system restoration cancellation must be integrated atomically before releasing
that controller; this action is not a shortcut around its remaining gates.

The result is a **policy receipt**, not verified device removal or a claim about
the latest policy generation. Same-key replay returns the original receipt
without changing a later generation or adding audit. Concurrent different
requests under the same revision cannot both commit. Stale review conflicts
require inspecting current state and preparing a new review, not silently
rebasing the old one.

### Lost replies and frozen reviews

An unknown/malformed/failed reply keeps the original review, typed IP and request
key available for explicit retry; never generate a new key merely to retry.
A validated durable receipt remains valid even when the subsequent optional
status read is unavailable. It does not prove current state after later edits.
No automatic submission/retry or device hint is sent by polling.

Reviews are immutable process-local objects, bound to subject and CSRF-cookie
hash. They expire within ten minutes/the shorter configured sensitive-action
age, with five per subject and 256 globally **in the retirement cache**, separate
from combined-removal reviews. Overflow does not evict existing reviews. Cookie
change, Web restart and expiry invalidate the review; inspect current policy
before preparing another. Cross-purpose review tokens cannot be used for a
different action. Browser status updates never replace a frozen POST review,
its token, typed confirmation or focus. Labels/reason/metadata remain escaped.

## Cancel waiting cleanup

In **Managed removal handoffs**, a WAITING_ADD entry owned by the current
Operator/Administrator offers a collapsed **Cancel this waiting cleanup**
disclosure. Administrators may cancel another user's wait. Other users can
observe it but do not get that control. Open the explanation before confirming
**Cancel waiting cleanup only**. The running ADD may still finish and a shun
may remain; maintenance stays stopped.

Cancellation is serialized with handoff promotion in SQLite. If the worker
already admitted removal, cancellation returns 409 and leaves that queued job
untouched: inspect/cancel the separate request in **Queue** if permitted. It
does not silently change meaning from waiting cancellation to queue cancellation.
An expired/attention handoff likewise requires inspection. Repeating a confirmed
cancel is an audit-free no-op; current identity/role/ownership is still checked.
The operation works during recovery pause and without the cleanup-worker flag.

With JavaScript, the existing single-submission controller updates metadata and
the handoff region without navigation or a refresh hint. Without JavaScript,
success redirects back to Managed shuns. Lost/malformed replies are not shown
as success; inspect state and retry the same root if necessary. No new queue
request, authority renewal or cleanup is created. Audit/log success occurs only
after commit and the real cancelling actor is recorded.

## Internal interfaces and security

`POST /api/v1/managed-shuns/retire` accepts one strict device/IP/revision/digest/
reason body plus current actor and a canonical UUID `Idempotency-Key`. Action is
fixed RETIRE, Protected-IP canonical revision is fixed 0 (revocation does not
depend on that revision), and no arbitrary action/mode/target list is accepted.
Canonical policy intent lives in the pure `managed_intent.py` module; the old
registry import remains an alias. Web does not import storage or the coordinator.

`POST /api/v1/managed-removal-handoffs/{UUID}/cancel` accepts only a strict current
actor. BFF form accepts CSRF only; subject/roles never come from form fields.
Current owner or Administrator and WAITING_ADD are checked under the same write
transaction. An absent/partial optional schema yields a controlled failure,
never implicit initialization. Both APIs remain private Unix-socket resources;
Caddy/Authelia trusted identity and the existing isolation boundary are unchanged.

## Validation, rollout and rollback

Synthetic ASGI/SQLite tests cover no-change preparation, current roles/CSRF,
scope/reason/body validation, session/cross-purpose/expiry/cache bounds,
concurrent revision conflict, old-key replay after a new generation, protected/
disabled/absent targets, audit rollback and unknown replies. Waiting checks cover
owner/Admin, idempotency, promotion conflict, rollback, unchanged RUNNING ADD and
no restoration. Real Chromium uses only localhost fixtures to check the frozen
review, desktop/mobile layout and AJAX cancellation without navigation/hints.
This is not live managed-policy or device-write acceptance.

No new schema or environment switch. Retain paired API/Web images and a checked
SQLite backup; stop/recreate only the sole API/Web pair. API startup may run
already admitted ordinary queue/policy work. Keep actual gates/inventory/secrets
unchanged, do not seed optional tables or submit live control actions for smoke
testing. Verify absent optional schemas, unchanged stable state, disabled gates,
ordinary reads and anonymous rejection. For rollback, preserve authority and
audit, never restore old enabled policy merely to revert software. Previous
paired images remove these UI controls; obey [Offline Recovery](recovery.md)
and its prohibition on older images ignoring active pause/reservations.
