# Large-Import Format and Capacity Transition

## Current delivery boundary

`bulk_intent.py` defines a pure **version-2 proposed-import binding** for up to
10,000 distinct IPv4 addresses on ten explicitly selected devices / 100,000 pairs.
It is a capacity foundation, not an expanded live registry, a migration, standing
authority or executable import. The existing 1000-key/accepted-pair limit,
10000-request/attempt bounds and retirement reserve remain unchanged.

The isolated [version-2 storage component](bulk-policy-storage.md) now persists
this format atomically in its distinct suspended development profile. Existing
API/Web forms, legacy registry writes, controllers, queue claims and maintenance
commands still do not accept it. There is no runtime feature flag or initialization
shortcut for it. Never place it into a legacy request row or pass its digest to
an existing grant route. Existing canonical payloads/keys/receipts are immutable
and keep their original interpretation. See [current confirmation](managed-import-confirmation.md)
and the [working-version capacity contract](../working-version-plan.md#capacity-contract-for-the-next-import-increment).

## Exact classified manifest

Each row is a literal `(device_id, IPv4Address, classification)` tuple. The device
selection is a distinct, numerically sorted tuple of 1–10 IDs, each 1–65535.
Rows must be in strict numerical device/IP order and cover every selected device
and every distinct address. No substring extraction, implicit devices, duplicate
removal, truncation, partial Cartesian product or sorting of an arbitrary stream.

All four classifications are bound, including exclusions:

| Class | Fixed record byte | Future interpretation, not authority by itself |
| --- | --- | --- |
| `PROPOSE_ADD` | 1 | Proposed new maintenance over an absent target. |
| `PROPOSE_ADOPT` | 2 | Proposed explicit maintenance over observed unmanaged state, without redundant ADD/provenance. |
| `ALREADY_MANAGED` | 3 | Keep original policy/generation/authorization; do not replace it. |
| `EXCLUDED_PROTECTED` | 4 | No accepted maintenance for this protected pair. |

Stream SHA-256 over the ASCII bytes
`ftd-shun-manager:managed-import-manifest:v2` followed by one LF, then each fixed
seven-byte record: unsigned big-endian two-byte device ID, four IPv4 bytes, one
classification byte. This is an integrity encoding, **not a new agent RPC**.
The descriptor records format `device-u16-ipv4-class-u8-v2`, explicit devices,
address/pair/accepted counts, all four classification counts and the manifest
digest. Accepted count excludes protected pairs. Excluded-only input can have a
summary, but cannot produce a standing proposal.

Verification consumes the full stream once, keeping only the distinct address
set (maximum 10000), counts and hash. Strict ordering prevents duplicate cells;
pair count equal to address count × selected-device count proves the complete
product. Overflow refuses the whole stream, never an accepted prefix. A missing
row/device, replacement address or swapped classification fails the original
binding even when aggregate counts look unchanged.

## Canonical descriptor and verification

`canonical_bulk_intent(...)` returns immutable summary, canonical JSON and its
SHA-256. The JSON is bounded to 8192 UTF-8 bytes, independent of pair count. It
fixes version2, scope `managed_import_policy`, MAINTAIN and `maintain_present`;
it binds separate canonical operation/preparation UUIDs, original preparation
digest, non-negative signed-64-bit managed/protection revisions, normalized
100/500-character label/reason and the complete manifest description.

Canonical encoding is sorted-key compact `json.dumps` with ASCII escaping.
`verify_bulk_intent(canonical, rows, expected_digest)` checks a separately
retained original descriptor digest, strict version/field/type/count rules,
canonical bytes and the full streamed membership. Duplicate JSON keys, unknown
fields, malformed/excessively nested input and substituted formats fail before
reading membership. No coercion of booleans/strings into integers or strings/
integers into IPv4 addresses is performed.

A digest or a constructible summary is **not a bearer capability, actor identity,
grant, confirmation receipt, current-policy check, execution outcome or evidence
that an earlier RPC settled**. Full verification is for proposal construction/
inspection, not a 100000-row scan for every future dispatched job. Durable indexed
membership and validated root references must support that later path.

## Read-only proposal from an existing preparation

The internal `ImportPreparations.propose_bulk_intent(plan_id, owner, digest,
operation_id)` composes the new format with the existing journal; it is not
exposed over HTTP and creates no retained root. One read transaction:

1. Verifies original owner, schema, entire header/membership digest and counts.
2. Refuses cancelled, expired/future or already confirmed preparations. A legacy
   confirmation cannot acquire version-2 meaning under another key.
3. Reads the original classified rows in chunks of at most 100 and checks new
   summary parity with the frozen header. Invalid/duplicate source diagnostics
   remain bound through the original preparation digest; they are not targets.
4. Rechecks expiry/clock before returning canonical descriptor, digest and summary
   with `can_execute=false`, `policy_saved=false`, `device_work_admitted=false`.

No policy, origin, queue, audit, schema, receipt, request reservation or hint is
written. Raw pasted source/comments and actor-role claims are not copied into the
descriptor; label/reason remain intentional plain-text metadata. Repeated reads
with the same operation reference are deterministic across restart, not durable
idempotency admissions. Current observation/protection changes do not rebase a
frozen proposal or make it executable: a later coordinator must reject stale
scope/revisions, check current actor, protection, holds/profiles and explicit consent.

## Persistence and remaining migration work

The [isolated SQLite component](bulk-policy-storage.md) now implements root/
membership/effective-policy persistence, owner recovery and policy retirement with
fixed positive reserve. It does not expand the existing deployed profile or
make old writers compatible. Its initialization is empty-development-state only;
nonempty conversion, protection/cleanup/cancellation/attempts and runtime dispatch
still need integration before expanded admission is exposed.

Before expanded admission, implement and validate the coordinated versioned
storage transition, not a larger legacy limit:

- One actual-actor-attributed immutable root, independently retained indexed exact
  membership and the existing one effective device/IP policy. Root/members/
  effective grants/audit commit atomically; preserve already-managed authority.
- Explicit global retained-key, request and revocation-reserve budgets. Increasing
  policy keys must not make the request reserve negative or block true revocation.
- Compatible retained attempts, original uncertainty/latches/receipts, reports,
  cancellation settlement and queue evidence holds. No automatic deletion,
  successful-outcome reconstruction, old-key reinterpretation or rearming.
- Bounded paged readers, rolling admission/backpressure/restart cursors and status.
  Do not generate 100000 short-lived requests or expire admitted standing consent
  with its draft. Confirmed report data is not a substitute authority registry.
- Checked private backup, exact schema/state-bound review, supported legacy
  conversion and clear older-writer/downgrade restrictions. No startup/GET migration.

No live migration or bulk fixture is authorized by implementing the format.
Until the storage/dispatch transition is delivered and separately activated, the
running system retains its current limits and gates. A formatter that accepts
100000 pairs is not proof of larger persisted authority or executable throughput.

## Validation and operational impact

Run the synthetic format/journal suites:

```bash
python3 -m pytest -q tests/test_bulk_intent.py tests/test_bulk_preparation_intent.py
```

Coverage includes independent fixed vectors, 100000 accepted pairs, mixed
classification/exclusion, bounded descriptor/working memory, strict/corrupt/
incomplete input, restart, owner/expiry/clock refusal, <=100-row SQLite scans,
unchanged independent state and legacy hash/receipt/limit compatibility.
The full existing confirmation/cancellation/security suites must still pass.

The original format increment changes no SQL schema; the separate storage
component adds only explicitly initialized developer schemas. Neither changes
network/credentials, binary protocol or deployed runtime call paths.
No lab service restart/migration is needed; optional journals
remain uninitialized there. Source rollback can omit this isolated format without
database restore because it creates no live state. Populated version2 test data
requires compatible code; see the storage migration/rollback boundary. Synthetic format tests are
not load, recovery/backpressure, FTD capacity or production acceptance.
