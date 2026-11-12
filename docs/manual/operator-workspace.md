# Compact Operator Workspace

The interface puts search, observations and actions before reference material.
Status and Queue remain beside the page heading on wide screens, and below it
on narrow screens. Their existing activity/error indicators and live updates are
unchanged. Open either panel for execution details.

Protected IPs describes what the service does: **automatically unblock this IP**
on enabled devices after a successful check. Turning it off stops automatic
unblocking; it does not add a block or turn auto-restore back on. If an imported
IP should be kept blocked again, disable protection and create a new import.
The short page explanation stays visible; timing, concurrent edits and the
imported-IP example live under **How protection works** and in the
[Protected IPs manual](protected-ips.md#what-the-switches-mean).

Each execution pause has its own compact outlined group: name, state and button
stay together rather than stretching across the available width. The groups
wrap independently on small screens.

Queue is for current work and unresolved attention, not a history viewer.
Finished operations, completed/cancelled imports without attention, and reviewed
old outcomes are not rendered there. Active imports still show whole-task
progress, including their completed portion; inactive imports with unresolved
attention remain visible. **Audit history** and available **Saved imports** links
lead to retained records. Nothing is deleted, acknowledged or retried by hiding
history. Invalid/missing review metadata still warns conservatively.

## Lists and IP labels

Observed lists retain their 100-row pages and top/bottom navigation. IP addresses
and their badges stay together on a stable first line. Cached country/ASN/operator
and the missing-information placeholder occupy a separate reserved second line; table content scrolls horizontally
within its own frame when it cannot fit. No addresses, states or actions are
truncated to fit the screen. Explanations and user-entered notes may still wrap.
The layout supports both light and dark browser themes.

Search is still universal across current, protected and historical addresses;
it does not issue a Cisco command. The Unmanaged table's narrower filter does
not restrict universal search. Observed/maintained states retain their meanings:
see [Shuns and Maintenance](shuns-and-maintenance.md).

## Actions and help

**IP links** in lists, Protected IPs, history, Queue and import reports open the
IP workspace in a frame over the current page. The address bar becomes
`/shuns/<IP>` so you can copy the link. Back, Close or a click on the backdrop returns to the original
list/query/page; Forward reopens the IP frame. Reloading or opening the copied
link directly gives the complete IP page. Ctrl/Cmd-click and Open page keep
ordinary navigation. Opening this frame reads local state only.

The same IP component and cached data are used across these surfaces; no full
import input is scanned for metadata, and a view never starts a provider lookup.
Background list updates remain bound to the original list URL. IP-frame refreshes
are read-only and preserve disclosures/focus; an open action review stays frozen.

The visible device cards in the IP workspace offer **Unblock…** and **Stop restoring…**.
No disclosure must be opened first. There is no execution-mode choice to make.
Unblock stops matching restoration and requests cleanup; Stop restoring leaves
the existing device block unchanged. Device-disabled and protection warnings stay
visible. **Unblock everywhere…** appears only for multiple devices and reviews
their complete scope together. Confirmation buttons use short names such as
**Confirm unblock**; the frozen scope and consequences remain in the review.

Before creating the first confirmation, Web reads a complete local preflight.
If no addition is running, it prepares the ordinary unblock review. If a safely
identified addition is running, it prepares a review explaining that unblocking
waits for that command and its session to settle. A blocker produces a readable
explanation and no confirmation token, not an ordinary-removal fallback. A failed
or unknown running command still requires Queue recovery; waiting is not replay.
When ordered inspection is not advertised, only the ordinary review is available
and its existing conflicts still apply. Missing/invalid inspection fails closed.

This choice happens **before consent**, never after a confirmation or an unknown
reply. The selected frozen review, identity/cookie, full device scope, request key,
deadlines and separate admission gates remain unchanged. A state change can reject
confirmation; it cannot silently switch mode, replace scope or retry a write.
Old explicit ordered inspections that find no running addition offer **Review
unblock**: an explicit new preflight, not execution or automatic conversion.
Review screens keep consequences, device list, blockers and explicit confirmation
visible, while UUIDs/revisions/session evidence live under **Technical details**.

The v2 workspace uses the existing complete local removal-scope read (up to ten
devices), including enabled managed targets with no current observation. It
validates the exact IP, fleet mode, readonly flags, full target metadata and
digest without allocating a review token. An unavailable/empty/oversized scope
is not treated as an empty managed registry; observations/history remain visible
with an explicit notice. Legacy profiles retain their existing observed actions.

**Block on devices…** opens an import draft form with the address pasted, without choosing
devices or saving anything. **Protect IP… / Edit protection** opens the matching
protected-IP editor with the address already selected. These GET links do not
change policy or enqueue work. The same roles, CSRF, revision checks, explicit
device selection, frozen review and final consent remain required. Normal page
refresh hints are unchanged; reading local scope sends no device command.

In Managed shuns, **Actions** above the list opens and focuses an existing
editor below it. This shortcut does not submit a request. The same capability,
identity, typed confirmation, frozen review and final consent checks still apply.
Escape or clicking outside closes the shortcut menu. Each row's **Note** and
**Activity** disclosures expose its author/import context and historical evidence.

Static reference text is available under **About**, **Rule details**, **What
does pausing do?**, **Formats and limits**, and retention disclosures. Real errors,
uncertainty, current-block warnings, and review consequences remain visible in
their operational context; collapsing help never changes policy or permissions.
Existing live updates continue to preserve open editors and entered values.

## Protected IPs and imports

Protected-IP cards use the available width, with the address and state badge
together. Disabled protection that is still shunned remains visibly flagged.
Editing and guarded deletion are unchanged.

The import workspace places pasted text beside device selection, label and
reason on wide screens, stacking them on small screens. **Save and review
addresses** still saves only a draft. Capacity limits, input preservation,
selected-device review and explicit final confirmation are unchanged.

This is a Web presentation change. It requires rebuilding/recreating Web and
reloading old tabs, not an API/agent restart, database extension, new consent,
device operation or recovery action.

## Disclosure state

Expanding a section is a presentation choice. Stable IDs or semantic keys retain
that choice and summary focus through live updates, including IP information and
cleanup sections without DOM IDs. Same-tab reloads remember at most1000 disclosure
booleans per URL in session storage; storage denial simply disables this reload
convenience. Form values, CSRF/review tokens and request bodies are never stored
there. Existing server checks still refresh/remove changed actions; keeping a
section open cannot recreate unavailable controls or rebase a frozen review.
