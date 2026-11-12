# IP Actions and Confirmation Dialogs

Shuns, Unmanaged and Managed shuns show actions beside each row:

- **Unblock** reviews the exact device/IP. For a managed target, confirmation
  also turns off its automatic restoration. A running addition finishes first.
- **Make managed** opens an import with this IP and device preselected. Review
  and confirmation are still required; opening it creates no rule or device job.
- **Protect** opens Protected IPs with the address filled in. Saving enabled
  protection automatically unblocks it on enabled devices and turns off its
  automatic restoration. Existing protection can be edited on that page.
- **Details** opens the full IP workspace and retained history.

Unblock and stop-restoring reviews open in a dialog over the current list. Check
the IP, devices and consequences, then press the confirmation button. You do not
need to type the same IP again. **Close** or Escape before confirmation changes
nothing. Without JavaScript, the same forms open normal review pages.

The managed review remains bound to the original scope, user, CSRF cookie,
expiry and request key. Dialogs do not enable unavailable actions or change a
blocked review into another operation. Existing browser tabs may still submit
their old typed-IP confirmation correctly; new forms use explicit button consent.
Whole-import count confirmations, Emergency Purge and Protected-IP deletion keep
their separate safeguards.

List and status updates do not replace the dialog or change its reviewed targets.
**Queued** means accepted, not already removed; Queue reports the actual result.
If a reply is lost, use **Retry the same request**. The dialog retains its exact
body, review token and key, and does not automatically retry a write or prepare
replacement work. Resolve that request before starting another action. Closing
an already submitted request does not cancel it.

Browser form errors show a human-readable HTML message rather than raw JSON.
Explicit JSON clients retain structured errors. The optional
[IP registration component](ip-context.md) supplies cached country, ASN and network context in
lists and dialogs. Opening an action never starts an external lookup.

## IP details without leaving the list

Follow an IP link to open its complete workspace over the current page. The URL
changes to `/shuns/<IP>` for copying. Back/Close or a click on the backdrop returns to the original list,
including its page/query/scroll; Forward reopens the frame. Open page or a copied
link opens the ordinary full page. Modified clicks retain normal browser behavior.
The frame only GETs local state. Existing action dialogs still require their
original explicit confirmation; IP details may be inspected above a review
without replacing its token or submitting it. Frozen reviews never auto-refresh.
