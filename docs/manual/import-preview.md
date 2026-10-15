# Blocklist Import Preview

## Release boundary

Open **Import preview**. This is a **non-executable preview**, not an import:
there is no Queue import button, addition opcode, admission token, persistence,
provenance migration or worker dispatch. Nothing is written to FTD or queued.
Existing removal/policy execution remains independent and unchanged.

The creation interface, Basic-account addition permission, strict ADD response
parser, actual blocking behavior and post-write verification still require
separate implementation/review and laboratory validation. The removal-interface
allowlist is not proof of a valid creation scope. Do not infer write readiness
from a Ready preview row, mock tests or the number of candidates.

## Workflow

1. Sign in normally through Authelia. Preview is available to every authenticated
   user, including users without a mapped group; future write admission remains
   a separate Operator/Administrator capability.
2. Optionally enter a batch label (100 characters) and reason (500 characters).
   These are preview context only and are not stored or sent to the agent.
3. Explicitly select target devices. Nothing is preselected, disabled devices
   cannot be selected, and the API rejects unknown/disabled/duplicate IDs.
4. Paste the text and select **Parse preview**.
5. Review every outcome, source line, bounded excerpt/comment and selected
   device state. The candidate pair count excludes duplicates, protected IPs
   and already observed device/IP matches. It is not a queued-operation count.

The classification reads one SQLite snapshot. Status gives observation
freshness; preview does not query Cisco or request a refresh. A snapshot may be
stale and policy may change after parsing. **Parse again** to recheck; background
status updates intentionally preserve both the paste/draft and the old preview
rather than silently reinterpreting it. Normal Status refresh controls remain
available separately. Reloading/navigating away does not save a server-side batch.

## Supported input

```text
# Whole-line comments do not create targets
// This whole-line comment is also ignored
198.51.100.10 # A bounded comment is shown as context
203.0.113.20, 203.0.113.21
192.0.2.30;192.0.2.31
Suspicious source 198.51.100.40 detected
src=198.51.100.41
```

Plain individual IPv4 literals, whitespace/comma/semicolon address-only lists,
and one address in surrounding text are accepted. Simple balanced token
wrappers (quotes/brackets/parentheses, up to four layers) are accepted. An inline
`#` comment is removed before candidate recognition; IPs in it are not targets.
Only **whole-line** `//` comments are supported. Inline `//`, JSON, URLs and
other structured input are not interpreted as an instruction or list format.

Multiple address-like tokens in free text are **Ambiguous**: the parser does
not guess which is the attacker. Split them into explicit address-only lines.
CIDRs, ranges, IPv6, URL/path and IP:port forms are **Unsupported**; addresses
are never expanded or recovered as substrings. A line containing IPv4 range,
CIDR or port notation is excluded as a whole, including spaced notation.
Malformed/leading-zero/partial IPv4 tokens are **Invalid**. Review context
before correcting anything: parser refusal is not permission to truncate input.

| Result | Meaning |
| --- | --- |
| Ready | Exact unique IPv4 with at least one selected device not currently showing it; candidate only, addition unavailable. |
| Duplicate | Same canonical IP appeared earlier; source-line references and per-line comments are retained. |
| Already shunned | All selected devices already show an active shun for this IP in local state. |
| Protected | Enabled fleet-wide protection policy excludes this IP from addition candidates. |
| Invalid | No exact supported IPv4 token can be accepted. |
| Unsupported | An unsupported address/route/URL/range/port form; no substring/expansion is used. |
| Ambiguous | Multiple address-like candidates in free text; no target is selected. |

## Limits and privacy

- 64 KiB of UTF-8 source text, 2,000 lines, 1,000 total preview rows (including
  duplicates/refused rows), up to 64 selected devices and 5,000 expanded unique
  device/IP pairs before exclusions. Exceeding limits rejects the preview;
  there is no silently accepted partial batch.
- The URL-encoded form body is capped at 256 KiB before decoding, including
  chunked requests. Multipart/file uploads are unsupported. Unexpected/repeated
  scalar fields and excessive field counts are rejected. The larger encoded
  limit allows percent-encoded UTF-8 and ordinary metadata overhead.
- Source excerpts and inline comments are each bounded to 200 characters and
  HTML-escaped, as are the paste, label and reason. All source is treated as data.
- Raw paste/labels/reason remain in Web memory/browser form only. They are not
  sent to the state API/agent, persisted in SQLite or emitted in application
  logs. The API receives only canonical typed IPv4 addresses and selected device
  IDs; inventory responses contain ID/hostname/enabled only, not credentials,
  SSH keys or management routes. Host collectors must not enable request-body logging.
- The form requires the existing secure CSRF cookie/token. Responses are
  no-store. Normal service authentication and session expiration remain in force.

## Deployment, rollback and next gate

Upgrade paired API/Web and reload tabs. No schema migration, environment
setting, agent update or state reset is needed. Reverting to the preceding paired
images removes preview routes/UI without touching existing policy/history/queue.
No real test shun needs to be created to validate this preview.

Next, finish the existing removal-cycle laboratory evidence and separately
design/lab validate the narrow ADD operation before creating import admission,
durable provenance or an executable Queue import action. Protected-IP checks
must be repeated at future admission and dispatch; a preview is never authority
to execute a write.
