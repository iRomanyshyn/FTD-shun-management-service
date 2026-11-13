# Import and Automatic-Restoration Pauses

## Operator controls

Open **Status → Scheduling** from any working page. Operators and Administrators have two
independent controls:

| Control | Stops new work | Keeps working |
| --- | --- | --- |
| Pause imports | Initial application of imported addresses not yet known present under their current rule. | Restoration, monitoring, removals and Protected-IP unblocking. |
| Pause automatic restoration | Re-adding missing blocks already applied, adopted or observed under their current rule. | Initial imports, monitoring, removals and Protected-IP unblocking. |

Neither removes existing blocks, cancels saved imports, turns off individual
rules or changes protected addresses. An already claimed operation may finish;
its acknowledgments, verification and terminal settlement still complete. Pause
is checked transactionally before the next claim/admission, not by interrupting
SSH. Normal request expiry still applies to unsent jobs; saved standing rules
remain and can produce fresh eligible work later.

Status shows a neutral **1 paused** or **2 paused** count and keeps both Pause/
Resume buttons next to their named state. The Managed shuns navigation link repeats
this count of paused scheduling controls (not a count of blocked addresses).
Monitoring, activity and error indicators stay independent. Queue keeps its actual
work counts; it does not use operator pauses as a substitute for queue progress.
An operator pause is not a red error.

## Initial application versus restoration

Classification is exact device/IP/current intent and generation. Restoration
means the original scope adopted an observed block, an exact current attempt
recorded VERIFIED/NOOP/OBSERVED_PRESENT, or retained observation was seen at/after
the current rule was saved. This is scheduling classification, not proof of
service creation. An old retired generation's attempts alone do not classify a
new rule as restoration.

Recheck classification at discovery, admission and pre-send claim. SQL filters a
paused category before the bounded scan limit: a long paused import prefix must
not starve missing restorations. Paused queued ADDs do not consume the other
category's per-device refill window. Original total queue/session/time/lease/root/
protection/uncertainty limits remain.

## Resuming safely

Resume affects only the selected control and records its new UTC fresh-read
barrier. A pre-resume absence cannot authorize another ADD: require a complete
new read and all current eligibility checks. It does not clear errors, replay
unknown writes, enable retired rules, change gates, release ATTENTION or override
recovery/maintenance suspension. The other pause remains unchanged.

Each control has independent revision checks and immutable real-actor/idempotency
records, plus `MANAGED_ADDITIONS_PAUSED` / `MANAGED_ADDITIONS_RESUMED` audit events
identifying `imports` or `restoration`. Stale concurrent changes conflict. An
original-key retry returns current state without toggling it again. After an
unknown reply, inspect status and retry only the same request; browser mutations
are not automatically resent.

## Storage and existing lab profiles

The experimental deferred-v7 coordinator also honors both pauses before scheduling
retry reads. Paused retry candidates do not trigger extra SSH sessions; other
eligible work can continue. Manual/periodic checks, first confirmation of an
already sent group and Protected-IP unblocking remain available. A resumed retry
must use a fresh read after its own control's Resume. Preparing that separate
profile is documented in [Fresh Working-Version Lab](fresh-development.md#optional-deferred-confirmation-development-storage);
it does not activate a configured v7 runtime. Matching explicit v0.5.0 selection
is documented in that manual; current lab/defaults are unchanged.

Fresh explicit development initialization includes this optional profile.
Startup, GET and browsing never initialize it. Older exact bulk profiles remain
readable but honestly show pause controls unavailable.

For an existing lab: drain/stop API and Web, verify actual exit, IDLE fences and
no pending/unresolved work, retain a checked private SQLite backup, and rehearse
on its copy. Then explicitly call `ManagedAdditionControls(store).initialize()`
on the stopped profile. It revalidates existing schema/quiescence and adds two
control rows plus an empty immutable request ledger. No authority, outcomes or
protection are converted. Retain integrity and original-data fingerprints. It
refuses partial/unsupported profiles and never repairs held sessions.

Old writers deliberately reject this extra schema. Do not downgrade to an image
that ignores these pauses, remove guards or restore stale authority. Retain or
build a compatible forward image for rollback. History is bounded to 10,000
retained changes per category; capacity conflicts never prune or silently resume.
This is not a production upgrade procedure.
