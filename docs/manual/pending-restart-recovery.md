# Recovery After an Interrupted Pending Handoff

Source v0.6.0 adds automatic recovery for one specific API crash window in the
experimental deferred mode. The current laboratory still runs verified v6;
this increment does not switch its configuration or database.

Source0.11.1 also handles brief SQLite contention before a process crash is
needed: the checkpoint and ordinary live pending handoff use bounded local-only
transaction retries after proved rollback. They keep the original live lease and
exact scope checks. No agent command or completion lookup is repeated. Exhaustion,
non-BUSY errors, expired permission and changed evidence retain normal failure
handling; this does not broaden the restart recovery contract below. See
[Local Result Storage Retry](result-storage-retry.md).

## What the operator sees

If the API stops after the agent has finished sending a final group and closed
the SSH session, the next API instance checks the original completion evidence.
When that evidence matches, the group becomes **Awaiting confirmation**. The
next full device refresh checks which addresses are present. The service does
not send those ADD commands again as part of recovery.

The recovery can wait for the old device lease to expire. It then returns to
the ordinary scheduler so that the confirmation read starts after the saved
settlement time. Import and restoration pauses remain independent; completing
an already-sent handoff does not resume either control. Protected-IP unblocking
and ordinary removals keep their existing behavior.

This does not turn an old **UNVERIFIED** result into success. It does not clear
an **ATTENTION** hold, grant another import, or renew an expired authorization.

## Required evidence

Before sending `END_PENDING`, the worker commits an append-only checkpoint with
the original device/owner/epoch, ordered jobs and ACK sequences, terminal
sequence and a digest of public inventory and original visit evidence. It also
binds any earlier verified/no-op prefix in that same visit. The checkpoint is
intent only; it never proves that a command or session completed.

After an API restart, recovery accepts only all of the following:

- The original expired **LEASED** fence remains unchanged, with no unknown work.
- There is exactly one matching checkpoint and the complete original evidence
  remains unchanged, including public device identity and enabled state.
- The real configured v7 Unix client obtains the exact completed record from
  the agent's local completion journal, matching the original ordered ACKs.
- The full original final group is still **RUNNING**. Earlier visit claims have
  their exact **VERIFIED** or **NOOP** result; other prefix states refuse recovery.

The journal lookup sends one bounded local `0x1e` request, with a maximum five
second timeout. It does not open SSH, replay BEGIN/END, send ADD, reconnect to
Cisco, or poll the device. The current agent journal is process-local and bounded:
an agent restart or eviction can remove the required evidence.

Source0.12.0 optionally retains **completed pending-v7** receipts in a private
agent-only persistent journal. This can preserve the exact proof across an agent
restart; it does not persist active/prepared sessions or change the recovery
checks. Default/main-lab behavior stays process-local. See
[Persistent Agent Completion Evidence](agent-pending-journal.md).

## Atomic handoff and failure behavior

An immediate SQLite transaction rechecks the unchanged original fence, checkpoint,
inventory, original claims and ACKs. It retains the actual terminal receipt,
transitions the original jobs and attempts to **AWAITING_CONFIRMATION**, records
recovery audit and releases that exact original lease together. No intermediate
lease renewal or new device authority is created. A changed owner/epoch, concurrent
expiry handling or persistence failure rolls back the handoff.

Missing, active, malformed or foreign journal evidence leaves the original fence
and jobs in place and reports a held device. Local retry never resends the old
commands. Cancellation drains the bounded lookup/transaction before the task
ends. History retention preserves the checkpoint and its entire unreleased visit;
it does not discard a settled prefix required for this decision.

Once the handoff commits, the existing causal full-read classifier records
**OBSERVED_PRESENT** or **CONFIRMED_ABSENT**. Presence does not attribute original
creation. Any later fresh retry still needs the existing current policy, protection,
pause, causal absence, backoff, hourly limit and new-job checks.

## Scope and remaining work

This uses existing append-only audit and the exact deferred execution profile;
there is no schema converter, implicit setup, new endpoint or operator consent.
The live-lease handoff still enforces its original live lease checks.

Crashes before the checkpoint, lost stage ACKs, missing agent completion evidence,
failed/cancelled prefixes, historical unknown results and already-held epochs
remain outside this automatic recovery. Keep their evidence and use only a
compatible explicit recovery procedure. General held-epoch recovery and bounded
real-device acceptance remain separate work before laboratory cutover. See
[Deferred First Confirmation](deferred-confirmation.md) and
[Queue Recovery](queue-recovery.md).
