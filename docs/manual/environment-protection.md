# Environment IP Protection

Use this deployment-owned layer for local networks and addresses that the service
must not block, such as management sources, private networks or loopback ranges.
It is separate from the editable exact-address **Protected IPs** list.

## Configuration

Set the same non-secret value for API and agent in `.env`:

```dotenv
FTD_SHUN_ENV_PROTECTED_NETWORKS=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,169.254.0.0/16
```

Up to 64 comma-separated exact IPv4 addresses or canonical IPv4 CIDRs are allowed.
Networks are matched without expansion. Host bits in a CIDR, IPv6, empty list
items and malformed values refuse startup; they never silently disable protection.
An empty setting disables this extra layer. It does not disable editable Protected
IPs. Management/SSH source addresses are not guessed: include the relevant actual
addresses or ranges explicitly, including any NAT source when appropriate.

Restart API and agent together after changing the value. Each process captures its
configuration at startup; editing `.env` alone does not hot-reload a running process.
Web reads the public rule description from API status. No credentials are included.
Existing v6 and prepared v7 use the same protection; no DB/schema/wire conversion
or capability activation is implied.

## Import and Web behavior

Matching addresses are excluded from import/adoption and reported as protected.
The review identifies deployment protection and points to
`FTD_SHUN_ENV_PROTECTED_NETWORKS` in `.env`. A review prepared before configuration
changed cannot silently admit newly protected targets. Scheduling, queued ADD
claims and final API pre-send evidence checks also enforce the configured ranges.
The agent independently rejects a matching ADD before sending its Cisco command.
Reads and removals remain permitted.

Protected IPs displays configured ranges as read-only deployment policy. Exact-IP
UI toggles cannot override them. Counts for editable enabled/disabled addresses
remain counts of that list, not expanded network sizes.

## Detection, automatic unblocking and retirement

After a successful complete device read, normal queue discovery submits matched
observed addresses for verified unblocking under actor
`system:environment-ip-policy`. Existing device serialization, priority, limits,
request expiry, verification and uncertainty handling apply. Operator import/
restoration pauses do not stop these unblocks. Recovery holds and unknown running
commands still require their normal resolution; this setting does not bypass them.

Matching enabled managed rules are permanently retired in bounded batches (up to
256 distinct addresses per complete-read publication). Unprocessed rules are still
excluded from ADD while protection is configured. Removing a range does not revive
rules already retired; create a fresh import if blocking is desired again. Stop
and drain API/agent before weakening configuration while a large retirement batch
is incomplete. The audit retains original imports, generations and results.

Unstarted automatic removal requests are cancelled when neither deployment nor
editable protection still applies. Already-running operations settle normally.
Changing this configuration does not itself create a new block.

## Logs and future notifications

`environment_protection.shun_detected` records device, IP, matched network and the
queued request ID. A coalesced/pending target is not repeatedly admitted on every
poll. `environment_protection.unblock_result` is emitted after the result transaction
commits, with operation/request IDs and VERIFIED, NOOP, FAILED or UNVERIFIED outcome.
`environment_protection.managed_retired` summarizes committed policy retirement.
Original queue/audit events retain the distinct system actor.

Email, Teams and other delivery channels are planned, not implemented. They should
consume detection/outcome events with durable deduplication, include the configured
network and result, and avoid repeating alerts on every ordinary polling cycle.


## Desk-lab acceptance — 2026-11-16

API/Web0.15.0 and the matching agent enabled the eight ranges in `.env.example`
on the existing v6 lab, after a checked quiescent archive. The sole observed/
maintained match,10.10.10.10 on fpr1010-lab, had its restoration retired and one
fresh environment-policy REMOVE verified. A subsequent complete read confirmed
absence. All32,427 other target rows, original imports/protection and26 historical
unknowns were retained. Distinct detection and committed VERIFIED logs were
captured. This does not measure bulk throughput or activate deferred v7.
Exact image identities, private evidence location and rollback tags are in
[Project Status](../project-status.md).
