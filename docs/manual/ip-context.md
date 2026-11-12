# Cached IP Information

Shuns, Unmanaged and Managed shuns display **country · ASN · network operator**
under an IP. The shared component keeps address/badges on one stable line and
reserves a separate line for metadata or its missing-information placeholder. IP pages and addition/unblock dialogs include the network prefix,
range, source and source-database time. **IPFire Location** is the primary provider;
an optional **Team Cymru** supplement fills missing routing information.
This is advisory context: country is approximate, a network operator is not the
identity of an attacker, and metadata never changes blocking policy. Missing
information never blocks an action.

## How entries receive information

- A background worker fills missing context for **all current observations**, not
  just new addresses. Existing lists are populated in local batches of500.
- New detections are picked up from a dedicated observation feed, normally within
  a few seconds. Additional devices share the same IP context. Page views,
  searches and dialogs read cached results; they do not trigger provider work.
- The worker downloads a signed IPFire database once daily by default. After a
  different verified database arrives, it refreshes active entries locally.
  It also refreshes entries after seven days when the source is unchanged.
- Addresses missing from the source are checked again after a database change or
  the configured refresh interval. Local failures back off15 minutes, preserving
  useful previous data. Download failures preserve the last verified database
  and retry after one hour. Restart preserves the update schedule.
- Confirmed disappearance stops periodic work on that IP. A new occurrence gets
  fresh local context. Failed or incomplete device reads do not cause removal.
  Private/documentation/special-use addresses are skipped.

No IP list is sent to IPFire: the worker downloads a shared database, then performs
lookups locally. The official database is updated daily and exposes country,
prefix and ASN/name through libloc. See [IPFire Location](https://www.ipfire.org/location/)
and [Python bindings](https://www.ipfire.org/location/how-to-use/python).

## Configuration

The optional lab overlay selects these worker settings from `.env`:

| Setting | Default | Allowed range |
| --- | --- | --- |
| `FTD_SHUN_LOCATION_UPDATE_INTERVAL_SECONDS` |86400 (one day)|1–7 days|
| `FTD_SHUN_IP_CONTEXT_REFRESH_INTERVAL_SECONDS` |604800 (seven days)|1–30 days|
| `FTD_SHUN_CYMRU_ENABLED` |`false`|`true` or `false`|
| `FTD_SHUN_CYMRU_REFRESH_INTERVAL_SECONDS` |604800 (seven days)|1–30 days|

A source-generation change refreshes context sooner than the fallback interval.
Restart the worker to apply changed settings. Web uses the optional
`FTD_SHUN_IP_CONTEXT_CACHE` path; the lab overlay sets
`/ip-context/location-cache.db`. Empty disables cache presentation.

## Isolation and limits

Web/API/agent keep their network isolation. The worker receives only its own
cache and the dedicated read-only observation UDS: no original database,
credentials, API/agent controls, edge or device network. The networkless feed
opens the existing source with SQLite `query_only=ON`; its source mount permits
WAL/SHM housekeeping, never source DML/DDL or initialization. The separate cache
uses rollback journals so Web can read it on a strictly read-only mount even
after worker exit. Core storage/profile/authority is unchanged.

Only the worker image contains native Debian `location`/`python3-location`
packages. The downloader uses normal TLS verification, a fixed official HTTPS
URL, no redirects/proxies,120s checked download budget,10s network timeouts,
64MiB compressed/256MiB expanded bounds and128MiB LZMA memory bound. Before
atomic replacement, libloc verifies the signature with its packaged vendor key
and checks native readability. Invalid updates never replace a good source.
The worker's bridge uses one bounded15s native process per batch, not one process
or network request per IP. Work is bounded to100,000 cached IPs/200,000 observed
pairs, at most2000 local entries between feed scans. Web batch-reads/revalidates
displayed IPs in100-key SQL chunks (at most1000 distinct keys for the whole
Protected-IP list; ordinary tables retain100-row pages) with a50ms storage timeout and2KiB payload bounds.
Metadata revisions update context-aware lists; frozen dialogs remain unchanged.
Application destination checks are not an OS egress firewall.

The Source link opens IPFire's lookup page for the exact displayed IPv4 address
(`/location/lookup/<IP>`), only when the operator follows the link. It does not
run a background per-IP request. RDAP links keep their original registry targets.
Source attribution and its database time appear in IP details; pages with IPFire
results link to IPFire and [CC BY-SA4.0](https://creativecommons.org/licenses/by-sa/4.0/)
in the footer. The same cache is used for search, history, Protected IPs,
Queue and displayed import rows; these views never query a provider. Names are escaped, and contact-person/email/postal fields are not
collected. Native packages retain their packaged license notices.

## Desk-lab deployment

Keep the existing three lab overlays and append the optional IP-context overlay:

```sh
lab_context() {
  docker compose --env-file .env \
    -f deploy/compose.yml -f deploy/compose.local-lab.yml \
    -f deploy/compose.managed-lab.yml -f deploy/compose.ip-context.lab.yml \
    --profile ip-context "$@"
}

# Build validated source; retain the current Web/worker images first.
lab_context build ip-context-feed ip-context-worker web
# First installation only; existing feed/volumes need no reinitialization.
lab_context up -d --no-deps --no-build ip-context-init
lab_context wait ip-context-init
lab_context up -d --no-deps --no-build ip-context-feed
lab_context up -d --no-deps --no-build ip-context-worker web
```

No API/agent restart is needed. Stop external downloads and local enrichment with
`lab_context stop ip-context-worker`; Web continues displaying retained context.
Do not reset a cache or restore the core DB for a metadata rollback. The old0.8
RDAP cache (`cache.db`) is retained separately from `location-cache.db`; the new
worker refuses to repurpose it. Keep all existing overlays/data. Never run broad
volume cleanup. This is unrelated to the deferred-v7 lab overlay.

## Optional Team Cymru supplement (v0.11.0)

Set `FTD_SHUN_CYMRU_ENABLED=true` in the lab `.env`, then rebuild/update only Web
and `ip-context-worker` with the existing four-overlay composition above. The
worker creates a small supplemental table in its own metadata cache. Core DB,
API, agent, inventory, trust and credentials are unchanged. New installations
default to disabled. The ordinary API/Web images do not install dnspython;
the worker image uses the optional `ip-context` Python dependency extra.

Existing and newly observed public IPs are eligible when local IPFire processing
has no result or lacks ASN/network name. Complete IPFire results are left alone.
The worker processes at most500 IPs per batch, at most once a minute; DNS questions
run with at most8 concurrent requests and a30s whole-batch deadline. ASN-name
questions are deduplicated within the batch (at most500), and a4096-entry resolver
cache respects positive/negative DNS TTLs. Per-IP results/attempts persist across
restart. Successful and unmapped entries refresh weekly by default; failures
retry after15 minutes, preserving useful data. A new observed occurrence can
refresh after the ordinary60s cooldown; inactive addresses are not queried.

Queries use the worker's existing system DNS resolver and fixed Team Cymru
origin/ASN zones. Public IPs appear as reversed-octet DNS questions, shared across
devices; no contacts, credentials, event history or full IP-list file is sent.
The vendor recommends DNS for recurring automation instead of repeated WHOIS
sessions. See [Team Cymru IP-to-ASN mapping](https://www.team-cymru.com/ip-asn-mapping).
DNS context is advisory and must never authorize a block or imply ownership.

IPFire country/prefix/ASN/name stay primary. Supplemental fields are labelled
**Cymru** in the compact information and **Team Cymru DNS** with a retrieval time
in IP/action details. Multiple origin ASNs remain explicit. Cymru country is
shown only as **Routing registration country**, never as geolocation. A name
from a conflicting origin ASN cannot fill an IPFire name. Retained context after
a failed refresh is labelled **Last known information**. An unavailable provider
or malformed supplemental record cannot remove valid IPFire data or block an
operator action. Lists, history, search and dialogs use the same cache reader;
opening any of them never starts DNS work.

To stop external supplement queries, set `FTD_SHUN_CYMRU_ENABLED=false` and
recreate only the worker. Cached routing context remains readable. Rollback to
the retained old worker/Web images does not require cache deletion or restoring
the core database; old images ignore the supplemental table. Keep the IPFire
dataset and both old caches intact.

## Previous RDAP experiment

Version0.8.0 queried only two existing addresses: one ready result and one
unavailable referral. The operator changed the lifecycle/source on2026-11-12:
fill missing existing context and refresh it periodically. The previous
once-per-occurrence/no-backfill restriction applies only to that old RDAP mode;
it does not prohibit this explicitly selected local enrichment. Its cache is
retained, and the Web reader can still display its format. See the development
log for the original acceptance evidence.
