# Check and Resume an Interrupted Import

Open **Queue → Needs attention → Check and resume import**. The authenticated
page inspects local retained evidence, shows the device/session and original
unknown count, and offers a downloadable report. It sends no Cisco command,
does not clear attention, and never treats a later presence as proof an earlier
write succeeded. A failure to inspect is not an empty/healthy queue.

## Current implementation: host-assisted, not one-click browser recovery

Web intentionally has no Docker socket, SSH key or host-control privilege.
Current recovery requires actual API/Web/agent quiescence. The page prepares an
exact host command for the known **single-device fpr1010-lab** inventory only.
For other targets use [the existing offline procedure](quiescent-managed-reconciliation.md).
No online fence-release endpoint or automatic unknown-write replay exists.

On the Docker host, open the repository root and activate its Python environment.
Use the command shown on the page, for example (values are placeholders):

```bash
python -m ftd_shun_manager.lab_recovery \
  --device 1 --expect-epoch 123 --actor YOUR-OPERATOR-LABEL --confirm-lab
```

The expected epoch is mandatory; an old page/command cannot release a later
failure. The actor is a trusted-host maintenance label, not an impersonated Web
role. `--extended-v6` is supplied explicitly only for an eligible 17–64-claim
tracked-v6 review. Normal reviews remain bounded to 1–16 claims.

The helper:

1. Checks the exact single-device lab inventory, held epoch, existing recovery
   contract, all three overlays and matching running/tagged API image. Unsupported
   state refuses before stopping services. It does not build/pull/replace images.
2. Retains private failure logs, original review and container IDs on the host.
3. Stops API/Web, then agent, with their drain allowance. Every original container
   must actually exit 0. Expiry, a stop request or process timeout is not proof.
4. Rehearses on a separate DB copy. Checks original eleven authority/outcome/data
   tables, existing receipts, integrity/FKs and real same-epoch release.
5. Inspects again, creates a new exclusive private backup and applies the existing
   offline reconciliation with a fresh UUID. Original unknowns remain unknown;
   no old job is retried or old policy re-enabled.
6. Restarts the same agent, then API/Web. This is **waiting for a fresh read**,
   not import completion. The worker must obtain a new complete read and recheck
   current standing policy/protection before creating any new missing-target work.

The persistent DB-volume archive is `recovery-assistance-NEW-UUID/`, including
`before-live-reconciliation.db`. The host evidence directory and receipt/backup
paths are printed. Keep them; no automatic deletion or stale-state restoration.
The existing tool may install its recognized optional recovery ledger when absent;
this is explicit offline recovery, never GET/startup initialization.

## Failures and limitations

Do not close the terminal mid-procedure or build images/change configuration
concurrently. Failures after stopping leave services stopped for inspection,
not forcibly released or silently restarted. Pending jobs,
captured cleanup, unrelated unknowns, changed images/epochs and unsupported evidence
refuse. Read the printed error/private evidence and retained backup; do not edit
outcomes, drop guards, reset the import or renew old consent to bypass refusal.

Other devices, production inventories, uncertain REMOVE and generalized crash
recovery are outside this lab helper. A future true browser recovery needs a
separately designed quiescence/coordinator protocol, not host privileges added to
Web. This helper does not cure the underlying FTD timeout or SQLite contention.
