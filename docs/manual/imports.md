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

The paste limits are 1 MiB UTF-8, 20,000 lines and 10,000 parsed rows, with up to
10 selected devices / 100,000 pairs. Invalid/unsupported/ambiguous inputs,
duplicates and protected exclusions remain visible. Raw pasted text and comments
are not saved. Drafts expire after ten minutes; reopening or retrying does not
extend the deadline. Reports are paginated in groups of 100, without dropping
the rest of the selection.

## Understand the result

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
