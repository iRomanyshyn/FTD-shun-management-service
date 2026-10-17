# Browser Import Review and Confirmation

## Boundary

Import preview remains a read-only parse/classification step. Operators and
Administrators can now prepare a separate, frozen review and explicitly submit
it to the existing private admission API. Every request still goes through
Caddy/Authelia and the BFF; actor/roles never come from form fields. Viewer and
unmapped users retain preview, not import admission. Shared Protected IP editing
permissions are unchanged.

All import/ADD flags remain default-off and off in the current lab. A review
can be inspected with intake disabled, but its Queue button is disabled and a
forged submit is rejected before an admission call. No new FTD operation, socket
opcode, writer, secret, database table or authentication bypass is introduced.
This UI is not approval to enable general writes or import the long list.

## Operator workflow

1. Open **Import preview**, select enabled devices and paste the source. Parse
   and inspect refused/duplicate/protected/current rows using the existing pages.
2. Select **Review candidate import**. This re-parses the *current* form and
   rechecks local state; it does not reuse an outdated preview or request SSH.
3. Inspect every frozen device/IP target, hostname, label/reason, exclusion
   counts, policy revision, retry key and expiry. Only absent Ready pairs are
   included. An address present on one device may still target another.
4. At most 1000 candidate pairs can be reviewed. Zero or larger sets are rejected
   as a whole. Explicitly edit the paste/device selection; the service never
   silently selects the first page, truncates, chunks or renews authorization.
5. If separately authorized and intake is enabled, type the exact target count
   and select **Queue N targets**. This submits the *entire reviewed set*, not
   just visible rows. Protected-policy/device/conflict/capacity/role checks run
   again atomically in the API; changed policy rejects rather than adapting the
   frozen set behind the operator's back.
6. **Accepted into Queue** is not device success. With execution disabled,
   work is held and expires normally. Open Queue for processed/verified/no-op/
   failed/unverified outcomes and existing ownership-bound cancellation.

Enabled Protected IPs and already observed pairs are excluded; disabled policy
entries are not import exclusions. Review state comes from retained local
observations, not a fresh Cisco query or proof of creation scope. Scope still
requires the separately reviewed agent-owned profile and independent gates.

## Retry, uncertainty and concurrency

Each review owns an independent UUID key and immutable canonical targets,
policy revision and normalized label/reason. A native confirmation POST never
passes browser-supplied actor/target/digest JSON through to the API. Concurrent
users have independent reviews and the same atomic ADD/REMOVE coalescing and
conflict rules. Current identity/write role and CSRF are required on every try.

A transport failure or malformed success response is **uncertain**, not failed
device work or verified success. Inspect Queue; an explicit retry of the *same
review* uses the same key/body and returns the original result after admission,
even if work completed or was later removed. There is no automatic retry,
new key on error, scope reclassification, renewed delegation or re-add.

Reviews expire within ten minutes (or the shorter sensitive-action age), bound
to the subject and CSRF cookie. A cookie change, different user, expiry or Web
restart fails closed. After any uncertainty, inspect Queue/history using the
displayed request key **before** preparing a new review; do not interpret loss
of a review as proof that admission failed. Review tokens never appear in URLs.
Back/reload may prompt native form resubmission: the original review/key is
idempotent, but a newly prepared review is a distinct intention.

Status and Queue keep polling while a review is open; they never GET the POST
result URL, replace its immutable targets/token, reset typed confirmation or
request extra Cisco reads. Gate labels describe the last explicit review/try;
each submit checks authoritative current admission state. No automatic Web
reauthorization is added. Existing queued delegation stays at most 15 minutes;
large imports still require a separate bounded scheduling design and live load
evidence. Even a permitted batch is not promised completion before expiry.

## Privacy, limits and storage

Raw paste/source comments are not retained in the review cache, database, API or
logs. Only canonical intent, bounded labels/reason, counts, hostnames, subject,
cookie hash and key exist temporarily in Web process memory. Accepted metadata
is retained by the existing audited admission path. Labels/reason are not secret
fields. Output is escaped; responses are no-store; confirmation bodies are
limited to 4 KiB, URL-encoded only, with unknown/repeated fields rejected.

At most five reviews per subject and 256 process-wide coexist. Overflow rejects
new reviews, never evicts a review whose admission might have succeeded. Expired
reviews are pruned on access. No server-side session database, shared secret or
new dependency is needed. This cache assumes the current single Web process;
multiple Web replicas need a reviewed shared draft design or routing affinity,
not fallback reconstruction of a lost review.

## Deployment and rollback

Run Python/static/Chromium checks using temporary synthetic state only. Rebuild
and recreate API/Web together; the API change corrects queued eligibility reasons
without rewriting stored outcomes/audit. Preserve previous paired images and a
SQLite-safe backup. Stop the sole API executor cleanly before replacement; its
restart may execute existing removal/policy work under the usual budgets.
Agent/Caddy/Authelia, secrets, inventory, .env and schema remain unchanged. Keep
all ADD gates off; do not create a live test job or forge a Web identity for
deployment validation. Reload browser tabs once.

Read-only checks: disabled admission/execution, zero eligible devices, unchanged
queue/policy/stable shun fields, SQLite integrity/foreign keys, normal v2 cycle,
private anonymous review/confirm 401 and normal TLS-verified Authelia redirect.
Restore the preceding API/Web images to roll back this increment without a
database restore/schema change. Web replacement loses ephemeral reviews, so
check Queue before preparing new ones. Existing active/uncertain work must
never be reset or replayed; older pre-ADD downgrades still require the queue
manual's offline suspension procedure.

Authenticated live submission, broader ADD acceptance and large-list execution
remain separate scoped laboratory work, not established by offline browser tests.
