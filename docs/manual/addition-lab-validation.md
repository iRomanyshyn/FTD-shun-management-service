# Addition Readiness and Laboratory Validation

## Release boundary

This is a staged operator-run laboratory procedure, not an executable import
or permission to apply a pasted list. The service still has no ADD operation.
Use only an isolated non-production FTD under the normal change process.
Do not upgrade the dedicated account from Basic to Config to pass a test.

There are two independent gates before implementing/enabling large imports:

1. **Read capacity:** complete snapshots must support the resulting device
   population, including pre-existing entries and multiple interfaces.
2. **Creation semantics:** verify Basic permission, actual creation scope,
   duplicate behavior, strict response parsing, observation and cleanup.

## Known capacity blocker

The deployed/default legacy agent caps a command's complete SSH output at 65,536 bytes. Each
legacy or experimental cycle response is also limited to 65,536 bytes. These
limits deliberately fail closed; they must not be bypassed by truncation.

For 7,307 entries on `management` (10 ASCII bytes), the binary legacy response
requires `3 + 7307 * (4 + 1 + 10) = 109608` bytes. A cycle response requires
109612 bytes. Both exceed the current packet cap. Synthetic matching CRLF CLI
rows using benchmark-range addresses require 337679 bytes before command echo
and prompt. Real output length/timing depends on the device; this is a size
calculation, not live load evidence. Even the 4,368-entry binary boundary is
not a supported FTD capacity: the independent CLI cap can be reached earlier.

The preview's 10,000-row/100,000-pair budget is a local parsing/classification
budget only. It does not prove that this many device entries can be monitored
or written. Do not apply the operator's 7,307-address list to the current agent.

The next implementation must preserve fixed binary validation and complete-
snapshot reconciliation. Review a bounded multi-frame snapshot with version,
ordering, total entry/byte/time budgets and an explicit end-of-snapshot check,
alongside a separately bounded console-output reader. No partial snapshot may
reach reconciliation or imply disappearances. Interrupted/oversized/duplicate/
out-of-order snapshots must retain previous observations and stale/error state.
Changing a Python buffer alone cannot fix the SSH cap or packet transport.
Validate kernel SOCK_SEQPACKET limits rather than assuming one huge packet
will work. Measure prompt timing/paging and preserve bounded session budgets.
No new reader/writer service, broker or network listener is needed.

The [large-snapshot extension](large-snapshots.md) implements this bounded read
path behind a separate default-off flag. Synthetic 7,307/20,000-entry tests do
not establish live FTD paging/timing, data-plane behavior or ADD capability.
The blocker remains for legacy/v1 and for unvalidated large device populations;
complete the extension's live-read checks before a large import is admitted.

## Stage 1 — Preflight, read only

1. Confirm the exact FTD model/version and login as the existing dedicated
   **Basic** account. Never paste its password or a configuration export.
2. Choose a dedicated test address not used by management, VPN clients, probes,
   DNS or other lab traffic. The examples use `198.51.100.251`; independently
   confirm this TEST-NET address is unused in the particular lab.
3. In Protected IPs, confirm the fixture is not enabled for automatic removal.
   Check Queue for pending/running fixture removals. Do not edit unrelated
   entries, disable fleet-wide controls or race an existing request.
4. Record these reads, retaining exact whitespace and prompts:

   ```text
   show shun
   show shun 198.51.100.251
   ```

If the fixture is already present, stop: do not remove or relabel a pre-existing
shun. Choose another approved unused test address and repeat preflight.

## Stage 2 — One explicitly approved direct CLI creation

Only after Stage 1 confirms absence and the operator approves this one target,
run from that same Basic session:

```text
shun 198.51.100.251
show shun 198.51.100.251
```

Capture exact success/error text, elapsed time and the observed interface(s).
The source-only command form was observed under the operator-reported Basic
login in the recorded test below. That is one fixture, not fleet admission.
Do not guess a creation
interface argument, send arbitrary diagnostic commands through the service,
or add more targets if the first command fails or the prompt is lost.

An observed `management` entry does not establish data-plane blocking or a
valid fleet-wide creation scope. Record only what the device actually reports.
Do not run a second add merely to investigate duplicate behavior in this stage.

## Stage 3 — Scoped cleanup and evidence

Remove only the newly created fixture, using the already validated explicit
removal form for the observed interface. If the observed interface is exactly
`management`, the cleanup is:

```text
no shun 198.51.100.251 interface management
show shun 198.51.100.251
```

Do not run `clear shun`, an unscoped bulk removal or this cleanup against a
pre-existing entry. If a different/unexpected interface is reported, stop and
review it before choosing the cleanup command. If a command disconnects, inspect
state using read-only commands after reconnecting; do not blindly replay it.

Record model/version, role, exact outputs, interface, timing and cleanup result.
Keep credentials, unrelated addresses/hostnames and production logs out of Git.
Sanitize fixtures without changing fixed words, whitespace or field layout.
A failed/unverified attempt is evidence too; it must not become success by
assumption. Add confirmed evidence to the project log, not a predicted result.

## Recorded evidence — 2026-10-16

The operator confirmed access as `ftd-shun-lab` with the Basic role on the
previously recorded FPR1010 / FTD 7.6.6 laboratory profile. The version/role
were not independently re-read in this exchange. Target preflight returned
no entry, followed by this direct CLI result:

```text
> show shun 198.51.100.251
>
> shun 198.51.100.251
Shun 198.51.100.251 added in context: single_vf
Shun 198.51.100.251 successful
> show shun 198.51.100.251
shun (management) 198.51.100.251 0.0.0.0 0 0 0
>
> no shun 198.51.100.251 interface management
> show shun 198.51.100.251
>
```

This establishes operator-observed Basic creation and target visibility on
`management` for one initially absent TEST-NET fixture. The operator then
confirmed scoped cleanup: interface-qualified removal returned to the prompt,
and the subsequent target read was empty. This completes the direct CLI
absent → added → observed → removed → absent lifecycle for this fixture.
No command duration, duplicate/no-op behavior, data-plane traffic blocking,
automated ADD verification or large-population capability was established.
The direct CLI experiment has no service manual-import provenance.

## Remaining gates and next implementation

After Stage 1–3 evidence, separately approve duplicate/no-op and representative
lab data-plane tests. Verify real blocking using dedicated synthetic traffic,
never by blocking an operator/VPN/management address or the long pasted list.
Confirm initial/final full snapshots remain complete at the intended load.
Finish the existing [cycle checklist](agent-cycle-protocol.md#migration-and-laboratory-validation).

Then review typed ADD encoding and configured creation scope before agent code,
followed by durable admission/provenance and worker integration. The operation
must reserve verification budget, fail closed on unknown output, retain uncertain
writes without automatic replay, and exclude enabled Protected IPs at admission
and dispatch. Existing short authorization expiry and shared cycle limits remain.

Imports are one-time actions: a later removal/disappearance/restart must not
automatically add the address again. Do not claim manual-import provenance for
an entry already present or for this direct CLI experiment.

## Deployment and rollback impact

This readiness procedure and the capacity regressions change no running
service, schema, protocol, setting or credential. No rollout is required.
The optional direct CLI fixture is a separate scoped operator change with the
cleanup above; documentation/test rollback does not clean up device state.
