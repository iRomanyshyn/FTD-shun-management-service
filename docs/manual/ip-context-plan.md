# IP Registration Context — Implementation Plan

Requested 2026-10-21; UI alignment updated 2026-11-12. This page retains the
original design record. Isolated background RDAP on the known lab was
authorized on2026-11-12. Source v0.8.0 implements the feed/cache/worker and Web
presentation; its two-IP experiment is complete. The operator subsequently chose
local IPFire enrichment for all current/missing IPs and periodic refresh in0.9.0;
that newer architecture amendment supersedes the old lifecycle limits below. Follow
[IP Registration Information](ip-context.md) for implemented behavior.

## Presentation

Show a compact **registration country · network / registered organization** line
under an IP in current, unmanaged and managed lists. Keep it to one short line;
put full text, allocated range, source and lookup time in the IP workspace and
its unblock/addition review. Reuse cached data during actions, including when a
block is about to be removed. A missing lookup must not delay a review or action.

RDAP describes network registrations. Its country and network name must not be
presented as the attacker's location or a verified retail provider. Use
**Registration country**, **Registered organization** or **Network** as appropriate;
do not invent a country/ASN/provider when the registry omits it. Field definitions
come from [RFC 9083, section 5.4](https://www.rfc-editor.org/rfc/rfc9083.html#section-5.4).
Do not retain contact-person, email or postal-address records for this feature.

Use the [IANA IPv4 RDAP bootstrap registry](https://www.iana.org/assignments/rdap-ipv4)
to select authoritative services. Any implemented client needs an explicit bounded
HTTPS destination policy and response/redirect validation; browser-facing markup
must never follow arbitrary URLs supplied by a registry response.

## Lookup lifecycle

- Run deduplicated, rate-limited lookups in a nonprivileged background component.
  Keep credentials, device RPC and mutation access away from it. Web/API page
  rendering and the SSH agent must not gain unrestricted outbound access.
- Attempt once for a newly detected global IP occurrence. Additional-device
  sightings reuse the same context. Persist the attempt marker before network
  I/O so process failure cannot create repeated attempts for an active occurrence.
- Keep ready/unavailable/failed context while the occurrence is active. Page
  views, search, dialogs, cache age, polling, adoption and restarts never trigger
  another request for it. Confirmed disappearance followed by new detection may
  start a new occurrence and attempt.
- Addition/import reviews may show existing cached context, but must not fan
  out into live lookups for every pasted candidate. Initial activation must not
  silently backfill the existing large dataset.
- Skip private/special-use addresses. Bound queue/cache size, concurrency,
  request rate, response bytes and total timeout; honour provider throttling.
  A failed or throttled attempt records unavailable context, without an automatic
  retry loop for that active occurrence.

Context never grants blocking, adoption, protection, removal or restoration
authority. Country/organization changes must not alter policy. Keep the cache
separate from immutable execution evidence and original import authority.

## Delivery and acceptance

First choose the narrow read-only observation feed and separate cache storage,
then add provider parsing/cache/occurrence tests and bounded Web batch reads
(at most the displayed page of IPs). Render available cache entries in rows and
review dialogs. Test missing/oversized/malformed responses, redirects, throttling,
concurrent sightings, restart, disappearance/redetection and zero network activity
from list views. Only after the outbound decision and isolated checks should a
labelled, small lab sample be enabled. Do not backfill or reset the original DB.
