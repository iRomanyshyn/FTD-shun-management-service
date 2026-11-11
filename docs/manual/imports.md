# Imports — Operator Guide

Use **Imports** to keep a list of IPv4 addresses blocked on selected devices.
If a service-managed block disappears, active maintenance restores it after a
fresh device read. Automatically detected, unmanaged shuns are not adopted just
because they were observed. This guide describes the configured managed runtime;
other service modes can show unavailable controls rather than enable execution.

## Paste, review, confirm

1. Open **Imports**, paste addresses and select the devices to block on. Optional
   label and reason help identify the import. Choose **Save and review addresses**.
   This saves a private draft, not maintenance or device commands.
2. Inspect the reported input issues and select **Review planned changes**. The
   report uses the original local observations, not a new device query. In
   **What will happen**, review new blocks, already-shunned addresses to maintain,
   already-managed addresses left unchanged and protected addresses skipped.
   Choose **Continue to confirmation**. Nothing has been applied yet.
3. Type the exact accepted **device/IP pair count** and explicitly agree to
   recurring maintenance. One address on two devices counts as two pairs.
   Confirming saves the whole reviewed selection or refuses it on conflict.
   It does not bypass a pause, missing profile, protection or an unresolved
   operation. Suspended maintenance is explicitly identified and stays suspended.

The paste limits are 16 MiB UTF-8, 100,000 lines and 100,000 parsed rows, with up to
100,000 unique addresses, 10 selected devices and 100,000 device/IP pairs in total.
For example, 95,081 addresses fit one device, but not two; select fewer devices or
split the list if the complete product exceeds the pair limit. This limit applies
before protected exclusions. Oversized input is rejected completely, never cut off.
Invalid/unsupported/ambiguous inputs,
duplicates and protected exclusions remain visible. Raw pasted text and comments
are not saved. Drafts expire after ten minutes; reopening or retrying does not
extend the deadline. Reports are paginated in groups of 100, without dropping
the rest of the selection.

You can paste Cisco `show shun` exports directly, for example:

```text
shun (outside_907) 198.51.100.10 0.0.0.0 0 0 0
```

Only the source address (`198.51.100.10`) becomes a candidate. The destination
(`0.0.0.0` here), interface, ports and protocol are validated but not imported.
Your selected devices and their configured ADD profiles determine the new block;
this is not a configuration clone. Malformed export rows are reported, not guessed.
Ordinary IP lists and surrounding text/comments remain supported.

The live byte counter includes native form line endings. Input is not truncated
by the textarea, and size/line/pair errors identify the actual failed limit.
Saving or reviewing even a large draft never starts additions. Confirmation is
still required; test the report before confirming a real list. Synthetic input/
storage tests do not establish 100,000-shun throughput or FPR1010 device capacity.

## Understand the result

### Whole-import progress and stopping the remaining work

Open **Queue** for one progress card per import, not sixteen one-address internal
requests. The denominator is the complete original accepted device/IP scope,
including addresses not yet in the rolling queue. Counts distinguish verified
ADD, verified no-op, adoption/existing maintenance, merely observed presence,
waiting/queued/running, stopped/superseded and failed/unverified/missing evidence.
Processed does not mean successfully created. Observations never prove creation.
The card describes initial application; recurring maintenance can continue after
it finishes. Finished imports leave Queue unless they still need attention;
their original receipts remain available under Saved imports.

The original owner or an Administrator can choose **Cancel remaining import…**
from this card. This opens the existing whole-import confirmation, not an instant
cancellation. Review its frozen consequences and type the accepted pair count.
Already applied/adopted blocks stay maintained and are not unblocked. Unstarted
work is stopped; a running command and its verification finish safely. Unknown
outcomes stay unknown and require attention. Do not individually cancel the
internal one-address delegations as a substitute for cancelling the whole import.

### What a device batch means

One bounded SSH session handles up to 16 ADD/REMOVE operations. Commands on one
FTD remain sequential, with target verification for each IP and initial/final
complete reads. This is not one SSH login per IP or a pasted CLI script. Healthy
devices can progress independently within the configured concurrency. A full
batch can continue with the next session without waiting five minutes; interactive
reads/removals retain their next-checkpoint priority. Time/command limits can end
a batch early, and counts do not promise a throughput or ETA. Large lists on a
slow FTD can still take substantial time; no verification is sacrificed for speed.

Slow local reconciliation/claim/settlement is awaited outside the API event loop.
Status publishes the last completed discovery summary rather than waiting on its
SQL lock. A temporary connection failure keeps old data visible and retries; it
does not submit a second import or mark a timed-out write successful.

If **Status** reports a held/ATTENTION device, the import remains pending and its
Queue card shows attention, not a successful or ordinary waiting device. Restart
does not release that fence. Do not reimport the list, clear the lease or replay
unknown commands to get past it. **Cancel remaining import…** is still a reviewed
policy revocation, not recovery of the device fence. Preserve the original
outcomes and investigate settlement/recovery separately.

**Confirmed imports** records saved maintenance settings, not successful device
writes. Open **Managed shuns** for current maintenance and observations; open
**Queue** for actual operation results and anything needing attention. Verification
is separate from acceptance. A block present on a device is not proof that this
service created it.

**Turn off auto-restore only** leaves the device unchanged; it does not unblock
the address or automatically remove a later FTD-created block. **Turn off
auto-restore and remove block** also requests removal after a separate review and confirmation. The
separate wait-for-addition option handles an addition already in progress; an
unknown result requires attention, not blind retry. Cancelling uncompleted import
work preserves already-applied/adopted blocks and does not unblock addresses.
Enabled protection permanently stops matching maintenance; disabling protection
does not revive the retired import.

Quiet off rules appear in collapsed history, not as current restoration work.
Still-observed blocks, pending work and uncertainty remain visible. Past verified
additions are historical, not proof that an address is currently blocked. See
[Managed shuns](managed-shuns.md#operator-guide-observed-blocks-auto-restoration-and-protection).

## Connection problems and saved drafts

- If saving a draft returns an unknown result, check **Saved drafts** before
  opening a new form. The uncertain form is locked against duplicate creation.
- If confirmation loses its reply, check **Confirmed imports** or explicitly
  retry only the same confirmation form. Do not create a new import to retry it.
- A Web restart clears the temporary confirmation form, not saved drafts or
  confirmations. Recovered confirmations remain historical, not new authority.
- Background status updates preserve pasted text, device choices, focus and the
  frozen review. They never confirm, change the selection or renew its deadline.
- **Technical details** contains full references, digests and revisions for
  troubleshooting. Import storage/protocol versions are implementation details,
  not workflow choices. The product version remains in the footer.

Saved drafts have bounded storage (four per owner / sixteen globally, including
expired and cancelled drafts). Nothing is silently evicted when full. Missing or
unavailable storage is a service problem, not an empty successful import.

For implementation contracts, see [Preparation Web](bulk-preparation-web.md),
[Standing Confirmation](bulk-standing-confirmation.md),
[Concurrent Admission](bulk-concurrent-admission.md) and
[Fresh Working-Version Lab](fresh-development.md). Routes and schema names in
those developer documents remain intentionally technical.
