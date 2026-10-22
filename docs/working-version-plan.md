# Working Version: Agreed Product Behavior

Agreed with the operator: 2026-10-20.
Status: approved target behavior and delivery plan; not a deployment procedure.

This records the sequential product discussion. The priority is a usable working
version, with usability refined during actual use. Bulk managed addition and
restoration belong in that version. Email is lower priority. The implementation
does not yet provide all behavior below; consult [Project Status](project-status.md).
The [architecture amendment](architecture-and-security-design.md#working-version-product-alignment--2026-10-20)
establishes precedence over conflicting older target decisions while preserving
the credential, typed-operation, verification and authentication boundaries.

## 1. Managed and unmanaged

- A manually added service target is always maintained until explicitly removed.
  There is no one-time-add option in the working-version workflow.
- An observed device/IP without active service authority is unmanaged. Observation
  alone does not establish who created it: FTD output cannot distinguish automatic
  detection from an external administrator's command.
- Managed targets are restored after confirmed disappearance, including following
  a reboot. A missing entry is not itself evidence that a reboot occurred.
- Explicit service removal permanently stops maintenance in the selected scope.
- Explicitly importing an already present unmanaged IP adopts it into maintenance
  on the selected devices. No redundant ADD is needed and no historical service
  creation is invented. Adoption is an intentional user action, never a startup
  conversion of observed state, old imports or history.
- Offering to restore disappeared unmanaged entries is deferred. The first
  working version automatically restores managed targets only.

## 2. Devices, identity and credentials

Keep device configuration outside the Web UI. `.env` points to `devices.json`;
the inventory contains stable internal IDs, display names, connection addresses
(IP or DNS), ports, enabled state and pinned SSH host-key configuration.

SQLite links observations, history and managed authority to stable device IDs.
Changing a connection address preserves those links. Configuration is reloaded
on restart. Address changes do not implicitly replace identity or trust a new
SSH host key. A temporarily missing/unavailable device is not permission to erase
its history or maintenance/cleanup obligations.

Every device explicitly supplies its SSH login and its own password-secret
reference. There is no shared-default credential fallback. Actual FTD passwords
are readable only by the agent; Web/API must not receive them. Do not place
password values in the inventory, database, tracked files or application logs.
Credential mapping is agent-owned; the lower-privilege services receive only the
public inventory projection, not a credential-loading interface or secret mounts.

Planning target: up to 10 configured FTDs, with up to 4 processed concurrently by
default and configurable concurrency. Each device has one serialized command
stream. Failure/reconnection on one device must not stall unrelated devices.
These are product planning targets, not validated FTD hardware capacity claims.

Transport prerequisite implemented 2026-10-22: the Rust agent now supports an
explicit 1–10 fixed connection-worker limit (default 1), with one nonblocking guard
per device/management address and no accepted backlog behind active workers.
Peer UID, fixed wire formats, existing feature gates and operation/session limits
remain unchanged. This does not supply independent API leases or end-to-end
parallel/continuous scheduling; no lab setting or new fixture was activated.
See [Agent Connection Concurrency](manual/agent-concurrency.md).

Fenced per-device API lease/queue primitives are now implemented on an explicitly
initialized optional developer profile (2026-10-22): immutable configured scope,
concurrent owner limit, increasing epochs, live-deadline checks across shared
admission/claim/results and retained expiry attention without stealing. Global
writers are excluded. An internal default-disabled parallel round coordinator now
runs actual independent bounded sessions/shared queue results and drains current
RPCs on cancellation. Independent read timing, continuous background dispatch,
API/Web integration and automatic quiescence-backed recovery are still pending;
no profile or worker is activated by startup or deployed environment settings.
See [Fenced Device Leases](manual/device-leases.md).
See [Parallel Device Rounds](manual/parallel-rounds.md) for the implemented runner,
per-device discovery budgets, shutdown guarantees and remaining activation gaps.

## 3. Bulk import and cancellation

Target up to 10,000 IPv4 addresses in one import, with explicit device selection.
An address/device pair is the maintained unit: 10,000 addresses on 10 selected FTDs
can require 100,000 policy pairs. Storage and admission limits must be revised
accordingly; increasing only the text-field limit is insufficient.

Preview and confirmation identify accepted, duplicate, invalid and actively
protected addresses. Invalid and protected inputs are skipped with a conspicuous
report and Web notification; they do not reject every valid member. Confirmation
binds the exact accepted scope and exclusions. Concurrent changes produce an
explicit conflict, not a silently changed acceptance list.

Accepted targets establish durable maintenance, rather than thousands of short-
lived one-time requests. Feed executable work into a bounded queue in portions;
do not materialize an unbounded job backlog. Progress and restart recovery must
preserve the original batch, target identities and author. The preview/admission
confirmation can expire without expiring an already admitted standing policy.

Cancelling an import cancels its unexecuted portion. Targets already added or
adopted remain maintained, and the result explicitly reports retained versus
cancelled work. An in-flight command must settle and be checked before its result
is classified. Cancelling an import does not roll back its completed additions.

Mass removal of an arbitrary selected address list is deferred. Individual
removal and the separately confirmed Emergency Purge cover initial removal flows.

## 4. Protected IPs / whitelist

Use exact IPv4 addresses only; CIDR/subnet rules are deferred. Users can add,
remove and temporarily disable entries while keeping disabled entries visible.
Disabled entries provide no active protection and should remain visually distinct.

Enabling protection permanently retires matching managed maintenance and cancels
its unstarted additions/restorations, then requests removal of matching observed
shuns on the relevant devices. A running ADD must settle before ordered removal.
While protection is active, newly observed matching shuns are removed again.

Disabling/deleting protection never reactivates the former managed policy. FTD
may subsequently shun that address through its own mechanisms; without a new
explicit managed action it remains unmanaged. This replaces the older design
that retained enabled maintenance behind protection and resumed it on weakening.

## 5. Scheduling, refresh and priority

Queued work continues between polling intervals. There is no artificial minute-
long pause between mutation batches. Keep command verification, bounded sessions,
timeouts and orderly reconnection; new batching limits require measurement and
validation rather than simply deleting the existing agent's safeguards.

The baseline full poll remains configurable with a five-minute default. Manual
full refreshes retain their configured minimum spacing, initially 60 seconds.
Those reading intervals must not impose a global write cooldown or serialize
independent devices. Web progress/status polling reads local state.

Interactive refresh and quick unblock requests take the next appropriate slot
after the current operation **and required verification**. Manual/protected
removals and Emergency Purge must not wait behind an entire bulk ADD list.
Multiple interactive requests are ordered/coalesced appropriately; conflicting
user intentions are not silently overwritten. Do not interrupt an in-flight CLI
operation or its verification to service another request.

The refresh button is always available to submit demand. Show a pending/countdown
indicator on the status trigger until the requested information is refreshed;
repeated clicks join demand rather than pushing its deadline farther away.
Update displayed data after completion without losing user input. Distinguish
waiting, reading, device errors and verified fresh data; an elapsed timer is not
proof that a refresh succeeded.

## 6. Recovery and conflicting users

An unavailable device waits for automatic recovery while healthy devices continue.
Keep its pending intent/progress and expose the wait/retry condition in status.

After a lost command response, automatically obtain valid device evidence and
converge to the still-authorized desired state. Routine network uncertainty must
not require an offline administrative ceremony. Preserve the original uncertain
attempt and audit; do not relabel it VERIFIED or blindly resend a lost command.
Before subsequent device work, establish that the earlier RPC/session cannot
still execute, obtain a complete successful fresh observation, and recheck current
intent/generation, protection, cancellation and purge scope. Timeout, partial
output or an unverified/stale snapshot cannot authorize a new mutation.

This requires a new reviewed reconciliation/attempt contract. The current
permanent-latch implementation is not automatically relaxed by this document.
Retained legacy abandonment/isolation decisions and uncertainty must be preserved
through an explicit compatibility/migration plan; never silently erase receipts
or release old exclusions to obtain automatic recovery.

When users submit contradictory actions on changed state, show a conflict with
the current state and require a refreshed review/confirmation. Do not silently
make the last stale submission win. Preserve authorship and distinguish admission,
in-flight work, observed presence and verified outcomes.

## 7. Web layout and multi-device correlation

Use separate Managed and Unmanaged tabs. Managed shows maintenance and execution
state, including pending restoration; do not present an absent maintained target
as an active observed shun. Retain the existing Protected IPs and history flows.

Keep detailed execution/freshness information in the pop-up status/queue panels.
Their triggers visibly indicate pending work, countdowns, failures and conditions
needing attention. Users should notice important changes without opening a panel.
Skipped import rows and cancellation consequences receive clear local notices.

Highlight an unmanaged IP observed on at least two distinct FTD IDs in a rolling
24-hour window, even if it has already disappeared from one device. Show device
count/names and relevant times, distinct from current simultaneous presence.
Repeated sightings on one FTD do not qualify as multiple devices. Provide a
direct action to take that IP into Managed with explicit device selection.

The later email digest must emphasize these correlated addresses too. Preserve
the existing local timestamp display with explicit timezone and history/search
behavior while reorganizing the interface.

### Deferred IP context / enrichment — requested 2026-10-21

Add minimal informational context for each IP in the Web UI, using RDAP or an
equivalent source to be evaluated later. This is a follow-up idea, not implemented
functionality or permission to enable outbound lookups. Keep core working-version
delivery ahead of this optional feature.

Candidate fields, only where the selected source actually supplies them:

- Network/registered organization name and allocated prefix or address range.
- ASN/operator information, potentially requiring a separate source.
- Registered country, clearly labelled as registration data rather than the
  user's location or the physical origin of traffic.
- Source attribution and lookup timestamp, with explicit stale/unavailable states.

Prefer a compact expandable IP-context view shared by current/managed/unmanaged
lists, search and IP details, rather than adding several permanent table columns.
Context is advisory: never use it as blocking reputation, proof of ownership or
authority to add/remove/restore a shun or change protection.

Enrichment is occurrence-driven, not periodically refreshed (operator clarification
2026-10-21). Schedule at most one lookup attempt when a new shun occurrence is
detected. Keep its result or explicit unavailable/error status while that occurrence
remains active. Polling, page views, cache expiry, failures and service restart
must not trigger another lookup for it. Only a confirmed disappearance/removal
followed by a newly detected occurrence permits another attempt; a failed/partial
device read is not disappearance. Adopting an already observed shun is not a new
detection. Retain an occurrence-bound completion marker across restart.
An additional-device sighting while that IP is already active reuses its existing
context rather than refreshing it merely because another FTD reported it.

Use asynchronous deduplicated lookups with a bounded local cache, provider rate
limits, response-size limits and short timeouts. Coalesce concurrent detections
of the same IP across devices. Cache age may control reuse on a genuinely new
occurrence, but never starts a background refresh or failure-retry loop for an
existing one. Viewing a long list must not fan out into one live lookup per row
or delay Web responses, refresh, queue dispatch or Cisco operations. No-data/errors
must leave IP operations usable; stale cached context may be shown honestly.
Do not automatically backfill every existing active record on feature activation.

Before implementation, evaluate provider coverage/terms and query privacy:
external requests reveal queried IPs to the provider. Specify enablement,
retention and an offline/local-data option where appropriate. Do not query private
or special-use addresses externally. Keep browser third-party requests off and
retain the current Web/API network isolation and FTD-only agent egress; design a
separate constrained lookup path rather than granting these services Internet
access. Use fixed trusted discovery/provider rules, validated destinations and
bounded redirects to prevent SSRF; treat all returned text/links as untrusted.
Provider choice, exact fields, cache defaults, worker topology and any schema or
deployment migration remain future design decisions, not current configuration.

## 8. Emergency Purge

Emergency Purge is available to every authenticated service user, with explicit
confirmation and actual actor audit. This decision does not authorize anonymous
access or invent directory roles. It is an exceptional whole-managed-scope action:

1. Cancel current imports and their unexecuted additions/restorations.
2. Permanently retire all managed targets in the confirmed purge scope.
3. Remove their shuns from the corresponding FTDs with urgent scheduling after
   current operations/verification settle.
4. Preserve whitelist configuration and unmanaged targets outside that scope.
5. Report progress and outstanding/failed/unreachable-device cleanup honestly.

Unlike ordinary import cancellation, Purge also removes the managed entries that
have already been applied. Confirmation must state what will happen, with import,
target and device scope/counts and the fact that maintenance will stop. Missing
current observations do not remove managed targets from that frozen scope.
Retirement must prevent re-add while cleanup is pending, including across restart.

The operator selected cancellation of current imports, not an approved permanent
global import lock. Exact admission behavior for *new* imports while Purge remains
pending needs to be specified with the concurrency/confirmation contract. Do not
infer permission to clear unrelated state or activate Purge on the lab now.

## 9. Email: approved follow-up, lower priority

Use SMTP Relay with independent optional authentication and transport modes:
plaintext, STARTTLS or implicit TLS. Support certificate verification/internal CA;
configured TLS must not silently downgrade. Connection settings, sender, common
recipients and timing belong in `.env`; passwords use secrets. Web needs a test
message action and delivery status rather than another configuration editor.
Sending/retry must be asynchronous and must not delay FTD work. Concrete mail
dispatch topology, outbox/retry bounds and network isolation require a later design.

Notification rules:

- First new unmanaged event after a quiet period: immediate notification.
- During an active notification window, collect further ordinary events rather
  than send an email per IP/device. Send a digest after 10 minutes, then 20, then 40,
  increasing toward a configurable maximum. Exact maximum remains configurable/
  to be selected. Count elapsed time, not poll/command/manual-refresh cycles.
- An unchanged shun list alone causes no new digest. If new events accumulate,
  the message states when the next conditional digest will arrive ("in X").
- Reset the backoff after one hour without new unmanaged events; the next new
  event may notify immediately again.
- Whitelist additions identify who added which address and when.
- Detecting an actively protected address in shun is urgent, independent of the
  ordinary digest timer. Notify about detection, the first unblock attempt/result,
  and later state changes. Repeated identical attempts/failures do not send an
  email every time; successful unblock is a state change.
- Emphasize unmanaged multi-device sightings over the rolling 24-hour window
  within the digest; this does not bypass the ordinary anti-spam timer.

## 10. Delivery order and implementation gaps

These decisions supersede older *target behavior* in the named areas. The older
manuals still describe existing contracts until implementation is migrated.

| Area | Existing implementation constraint | Agreed working-version target |
| --- | --- | --- |
| Credentials | Opt-in agent-only per-device mapping implemented; lab still uses explicit shared compatibility mode | Separately reviewed per-device rollout; no shared fallback within that mode |
| Preparation storage | Explicit 100,000-pair journal/private API/Web; gated confirmation and cancellation/settlement retain reports/canonical policy within current 1000-pair bounds | Compatible larger capacity and rolling dispatch/progress |
| Policy display/reviews | Managed tab reads 100-row pages; single-pair and whole standing-list reviews use distinct exact selections with global totals; authority limits unchanged | Coordinate larger retained capacity, remaining full reviews and bounded dispatch |
| Capacity | 1,000-pair policy/admission bounds | 10,000 input IPs across selected devices; bounded dispatch |
| Existing shun | Gated prepared-confirmation Web/backend support adoption without ADD/provenance; legacy grants still reject it | Retain explicit selected-device adoption in the larger executable workflow |
| Invalid/protected rows | Managed-import Web/backend bind visible diagnostics/protected exclusions and exact accepted scope; legacy standing review still rejects whole scope | Retain exclusions/reporting during rolling execution |
| Scheduling | One fleet executor, global >=60s cooldown | Parallel devices, one stream each, continuous bounded writes |
| Protection | Explicit protection saves now permanently retire matching maintenance; unknown state holds enabled protection until retirement can finish | Retain this lifecycle in the new bulk workflow |
| Lost result | Latched offline attention/recovery | Automatic fresh-evidence reconciliation with original uncertainty retained |
| Purge | No working-version global managed purge | Confirmed cancel/retire/urgent cleanup, authenticated access |
| Correlation | No agreed rolling cross-device signal | Unmanaged rolling 24-hour badge and managed action |
| Email | No mail delivery implementation | Lower-priority SMTP relay/digest follow-up |

Implementation order:

1. Design per-device inventory/secret ownership and capacity-compatible durable
   policy/import records; define migration and rollback from current retained state.
2. Implement managed-only import/adoption, visible exclusions, whitelist retirement
   and cancellation semantics with explicit conflict reviews.
3. Refactor per-device dispatch/concurrency, continuous queues and interactive
   priority while preserving fixed typed protocol and verified outcomes.
4. Implement automatic uncertainty reconciliation with proven RPC settlement,
   current-policy checks and retained audit; integrate ordered removal/Purge.
5. Complete separate tabs, status indicators, refresh completion, import reports
   and 24-hour cross-device correlation/action.
6. Validate end-to-end with disposable state, then separately scoped lab scenarios
   and measured throughput. A 10,000-address target does not authorize a live bulk
   load or establish FTD capacity/production readiness.
7. Implement SMTP delivery and notification aggregation after the core workflows.

### Capacity contract for the next import increment

The [isolated version-2 SQLite component](manual/bulk-policy-storage.md) now
implements actual root/membership/effective-policy persistence, owner recovery,
100-row reads and a positive retirement reserve on a fresh suspended development
profile. It deliberately blocks legacy managed services; no live profile or API
limits were changed. The existing protection coordinator now supports narrow
version-aware permanent revocation/weakening barriers (2026-10-22), without
enabling runtime imports. Version-2 pre-execution cancellation and local progress/
bounded candidate portions are also implemented (2026-10-22), without queue
admission; see [their explicit limits](manual/bulk-cancellation-and-work.md).
An optional bulk result journal now connects retained original evidence to shared
completion/lease/retention hooks, without claim/admission or dispatch activation.
Nonempty conversion, version-aware cleanup/atomic attempt claims and actual
dispatch remain prerequisites for runtime exposure.
A separately explicit captured-cancellation profile now handles owned in-flight
settlement/completed-application retention while preserving earlier receipts.
At that checkpoint, atomic runtime admission/claim, actual dispatch and automatic
reconciliation were not yet supplied; no live profile or fixture was activated.

The next backend increment (2026-10-22) now supplies actual atomic <=16-pair
enqueue and shared queue claims behind a separate default-false bulk capability.
Its explicit developer-profile upgrade retains suspension/history, requires a
fresh-read resume barrier and never activates itself. Cancellation/protection,
typed completion, exact deferral and lease recovery use the same journal/worker.
There is still no runtime refill/controller/Web wiring, concurrent standing
admission, continuous/per-device lease scheduler, automatic reconciliation or
legacy nonempty conversion. See [Bulk Queue Admission and Claim](manual/bulk-queue-admission.md).
No live profile, lab migration, fixture or FTD command accompanies this component.

Bounded refill now composes that admission with the existing Synchronizer behind
an internal default-false bulk capability (2026-10-22). It scans <=64 rows without
adopting observations, admits <=16 new jobs per cycle and limits each device's unfinished
shared-work window to 16. Keyset hints, revision/barrier resets and retained
last-admission ordering provide bounded restart-safe scans and device fairness.
The existing cutoff/cooldown still apply; continuous writes/parallel leases are
not implemented by this integration. Pending/status/claim distinguish the bulk
capability from legacy restoration. Unknown or merely read-reconciled original
RPCs remain retained device barriers; unsent expired jobs are cancelled without
rewriting old failed/unknown outcomes. See [Bounded Bulk Refill](manual/bulk-refill-controller.md).
No environment/API/Web activation, new schema or live lab change was introduced.

The isolated [version-2 format foundation](manual/bulk-import-capacity.md) now
binds a complete 100000-pair classified manifest in a small canonical descriptor,
including explicit protected exclusions/adoption classification and original
preparation identity/digest. A read-only internal journal proposal does not save
authority, expand legacy limits or expose admission. The isolated persistence
checkpoint above is separate; its coordinated runtime migration remains pending.

Inspection on 2026-10-21 confirmed that raising one constant is insufficient.
The current 1000-target registry, shared 1000-pair canonical request, 10000 immutable
request slots with retirement reserve, 10000 lifetime restoration attempts and
full-snapshot readers are coupled. They stay unchanged until the whole path is
compatible. In particular, increasing targets beyond ledger capacity makes the
current retirement-reserve calculation reject every new grant.

Implement the new flow around one durable actor-attributed import root, an exact
accepted/excluded scope and durable per-pair maintenance; do not turn 100000 pairs
into 100000 immediately queued requests. Use paged policy/report reads and bounded
rolling dispatch/restart cursors, with retained provenance and no request-TTL
expiration of standing consent. Freeze managed/protection revisions and explicit
adoption vs missing state; late changes conflict, never silently alter acceptance.
Cancellation must distinguish completed/adopted retained targets, unsent cancelled
targets and unsettled running attempts. Define total retained capacity/retirement
reserve and legacy-latch compatibility together before migration or gate changes.
Synthetic 10000-address/10-device tests must demonstrate storage, paged reads,
backpressure, revocation and restart, not only a larger paste field. No new bulk
schema, live migration or large fixture is authorized by this design note.

Do not keep extending offline incident controls as the default next product
milestone while the core working-version workflows remain unavailable. Existing
operator procedures/receipts remain valid safeguards for their current version.
No runtime code, schema, gates, profiles, credentials or deployment is changed
by recording this plan. New lab fixtures/migrations/activation still require
the existing scoped authorization; old fixture permissions remain consumed.
