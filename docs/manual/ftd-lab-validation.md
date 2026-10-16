# FTD Laboratory Validation

This procedure validates the typed snapshot and removal agent and collects safe parser fixtures. Run it only against a non-production FTD under the organization's normal change process.

## Objectives

1. Confirm that the agent can authenticate with the pinned host key and dedicated service identity.
2. Capture the exact supported `show shun` output shape for parser fixtures.
3. Validate a single device-scoped removal and its post-write verification.
4. Validate complete typed snapshot collection and reconciliation.
5. Confirm that expected security failures are fail-closed.

Do not use this procedure to create shuns, alter FTD configuration, or test against a production device. The product has no shun-creation operation.
The separate [addition readiness procedure](addition-lab-validation.md) defines
an explicitly approved, one-address direct-CLI experiment and the snapshot
capacity blocker. It does not enable imports or bypass this removal checklist.

## Prepare the lab configuration

1. Copy the protected deployment configuration as described in the [Deployment Manual](deployment.md).
2. Create a dedicated FTD lab service account with `Basic` access first, then test both the required read and removal commands. FTD does not offer a per-command CLI role. On the supported FPR1010 / FTD 7.6.6 profile, do not promote this user to `Config` merely to configure an SSH public key; provide its unique password as the protected agent secret instead.
3. Collect the FTD SSH public host key through an approved out-of-band method. Put the full OpenSSH public-key line in `ssh_host_key`; do not rely on TOFU or automatic enrollment.
4. Populate `allowed_interfaces` with the lab interfaces that may contain the selected test shun.
5. Enforce the host/network egress rule allowing the agent host only to the configured FTD management IPv4 address on TCP/22. Configure the corresponding FTD SSH source restriction.
6. Supply the dedicated service-account password only through `deploy/secrets/ftd_ssh_password`. Never paste it into an issue, chat, fixture, `.env`, or Git.

## Collect parser fixtures

From the lab FTD, capture these read-only command results exactly as returned by the CLI:

```text
show shun
show shun <known-test-ipv4>
```

Collect examples for:

- no matching shun;
- one matching interface;
- more than one matching interface, if the lab can safely provide it; and
- an error or unexpected response, if it can be obtained without changing configuration.

Also record the exact FTD software version and the interface names used in the test. Redact IP addresses, device names, usernames, and comments consistently if required, but preserve line breaks, whitespace, parentheses, column order, and all fixed words. Do not include credentials, private keys, authorization headers, configuration exports, or unrelated command output.

Store the sanitized fixtures in the repository only after a security review. They become the authoritative inputs for the typed read parser tests.

## Recorded laboratory evidence

The following sanitized fixture was captured on 2026-10-13 from a non-production Cisco Firepower 1010 Threat Defense running version 7.6.6 (Build 115). The target is a TEST-NET-2 address and the fixture contains no production address, hostname, or credential.

```text
shun (management) 198.51.100.250 0.0.0.0 0 0 0
```

The corresponding direct CLI lifecycle was successful:

```text
shun 198.51.100.250
Shun 198.51.100.250 added in context: single_vf
Shun 198.51.100.250 successful

show shun
shun (management) 198.51.100.250 0.0.0.0 0 0 0

no shun 198.51.100.250

show shun

shun 198.51.100.250
no shun 198.51.100.250 interface management

show shun
```

This direct-CLI evidence validates the current parser's observed line shape, the empty-output case, and the agent's explicit `no shun <IPv4> interface management` command form. By itself, it did not validate pinned-host-key authentication or the full service path; the later typed-agent result below adds that evidence.

The same removal was then performed by a newly created local user with the FTD `Basic` role. This establishes that, on this FPR1010 / FTD 7.6.6 fixture, `Basic` is sufficient for the product's required read and removal commands. Do not promote the product account to `Config` for this version.

Interactive SSH with a PTY successfully reached the FTD `>` prompt after the login banner. The banner took approximately 1.5 seconds in the observed lab session. This is a compatibility requirement for the agent, not a delay value: the agent waits for the prompt within its operation timeout and never uses a fixed login sleep. Plain SSH `exec` mode was rejected by the FTD login path and is intentionally unsupported by the agent.

On 2026-10-14, the isolated agent successfully completed a device-scoped removal through its fixed Unix socket protocol. The request was issued from the API container with the typed `UnixAgentClient` for device ID `1` and target `198.51.100.250`; it returned `verified removal`. This demonstrates the pinned-host-key, password-authentication, prompt-driven PTY, typed `show shun`, interface-qualified removal, and post-write verification path against the FPR1010 laboratory fixture. The direct test intentionally bypassed the Web/BFF and API HTTP workflow, so it does not validate browser authentication, CSRF, SQLite audit events, or Caddy routing.

Also on 2026-10-14, the API container issued typed `LIST_SHUNS` for device ID `1` through the agent socket and received `[]`. This validates the empty `show shun` path, the complete binary snapshot response, and its client decoding against the same FPR1010 lab. It does not validate a non-empty snapshot, SQLite reconciliation, polling/freshness metadata, or the browser workflow.

Later that day, an approved non-empty lab snapshot returned two allowlisted `management` entries, including the documented TEST-NET fixture. The API startup sweep persisted both active records with the configured device hostname and generated `SHUN_DETECTED` for the fixture. Its status showed a successful refresh and next-baseline timestamp; a hint issued seconds after that sweep was correctly marked `rate_limited`, without opening a second immediate FTD session. The additional test address is intentionally not recorded here.

## Validate the typed snapshot path

On 2026-10-15, following explicit operator approval, the new agent/API/Web were
deployed to the non-production stack with session cycles enabled. The database
received its four additive operation tables and `PRAGMA quick_check` returned
`ok`. Startup completed at `2026-10-15T15:59:05Z`; an internal refresh hint was
accepted with `202` and completed at `2026-10-15T16:00:56Z`. Agent logs recorded
one session cycle per sweep, two full-snapshot commands, zero removal steps,
and durations of 8151 ms and 7941 ms. A subsequent hint inside the cooldown was
`rate_limited`. All four previously active entries remained and no policy
match or queued mutation was present.

This validates live BEGIN/END session reuse, non-empty snapshot decoding,
reconciliation, and refresh scheduling only. It does not validate REMOVE in
the new conversation, multi-item writes, mid-batch priority SNAPSHOT, browser
submission, or failure recovery. Those remain required controlled lab checks.
The operator waived a backup for this development migration; no data volume
was removed or reinitialized. The repository default remains feature-off.

Later on 2026-10-15, the operator reported that queued removals worked well in
the browser. Read-only private API inspection confirmed two VERIFIED results,
no queued/running work, a successful completed cycle, and no device error.
This records the operator's UI result and durable API outcomes; it is not an
independent direct FTD observation or evidence that both removals shared one
session. Remaining concurrency, failure, and priority checkpoints still need
their controlled lab cases.

Rebuild the API and agent after deploying this increment. This check only reads
the FTD and is safe to run when no shun is present; an empty list is a valid
result.

```bash
docker compose --env-file .env -f deploy/compose.yml up -d --build agent api
docker compose --env-file .env -f deploy/compose.yml exec -T api python -c \
  "from ftd_shun_manager.agent_client import UnixAgentClient; print(UnixAgentClient('/run/ftd-shun-manager-agent/agent.sock').list_shuns(1))"
```

For the recorded fixture, create an approved TEST-NET shun only through the
normal lab change process, then repeat the command. Confirm that the returned
address and `management` interface exactly match `show shun` on the FTD. Wait
for the initial API sweep or trigger an authenticated state-page view, then
confirm that SQLite/UI state contains that shun and one `SHUN_DETECTED` event.
After removing it by the approved path, wait for a successful snapshot and
confirm `SHUN_DISAPPEARED` only when the disappearance was external rather than
the recorded verified UI removal. Do not use a malformed production FTD response
as a parser test.

## Validate the current removal path

Choose an existing, approved lab shun whose target IPv4 and affected interfaces are known. Do not use a production address.

1. Record the direct pre-operation `show shun <IPv4>` output.
2. Open the Web/BFF, confirm the displayed device hostname and interface summary, and select **Queue removal from this device**.
3. Confirm acceptance appears as QUEUED, not removal success; wait for the background worker and a VERIFIED result in the queue. In session mode, queue several approved fixtures during the shared cooldown to test one bounded batch, and separately observe their actual disappearance on FTD.
4. Record the direct post-operation `show shun <IPv4>` output.
5. Confirm that the target no longer appears and that SQLite history contains `SHUN_REMOVE_REQUESTED` followed by `SHUN_REMOVED_BY_UI` for the correct device, actor, and request ID.
6. Record the test timestamp, FTD version, agent image digest, inventory revision, and outcome in the deployment change record.

## Validate the trusted-IP automatic-removal policy

This is a write test. Use an isolated non-production deployment and one dedicated
TEST-NET fixture. Policy is managed through SQLite-backed **Protected IPs**,
not `FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS`; that obsolete environment input has no
effect after the one-time migration marker. Do not alter unrelated policy.

1. Record the current policy/revision and enabled-address count. Add the fixture IPv4 through **Protected IPs**, enabled with a clear laboratory name. No API restart is required. Review the fleet scope before saving.
2. Create the approved fixture shun through the normal lab change process and record direct `show shun <IPv4>` output.
3. Wait for the next successful snapshot, or use one authenticated state-page view and wait for its permitted background sweep. Do not use a direct agent command to trigger the policy.
4. Confirm the agent performs a verified removal, direct FTD output no longer lists the fixture, and history contains `SHUN_TRUSTED_AUTO_REMOVE_REQUESTED` followed by `SHUN_TRUSTED_AUTO_REMOVED` under `system:trusted-ip-policy`.
5. Delete only the fixture through **Protected IPs**, using typed confirmation. Verify the enabled-address count returns to its recorded baseline, unrelated entries remain unchanged and no fixture request remains running. Record the outcome before adding any real trusted address. Deletion cancels unstarted policy work, not an already running command.

Also test one agent-unavailable failure in a lab. The history must contain
`SHUN_TRUSTED_AUTO_REMOVE_FAILED`, must not contain a corresponding success,
and the locally observed active state must remain visible.

## Required fail-closed checks

Perform these only in a lab and restore the approved configuration afterward.

| Check | Expected result |
| --- | --- |
| Wrong pinned host key | SSH connection and removal fail; no Cisco write is attempted. |
| Target reported on an interface absent from `allowed_interfaces` | Agent rejects the removal; no Cisco write is attempted. |
| Agent socket unavailable | API returns an unavailable error; state is not marked removed. |
| Invalid binary RPC packet | Agent rejects the packet without opening SSH. |
| SSH authentication failure | Removal fails; no audit success is recorded. |
| Basic FTD CLI role cannot remove an approved lab shun | Do not silently promote the account. Record the result; Config access requires an explicit risk decision. |
| Trusted-IP policy agent failure | A policy failure is audited, does not claim removal, and leaves observed state active. |

Do not intentionally test malformed Cisco output on a production FTD. Use sanitized fixtures and agent unit tests for parser-negative cases.

## Exit criteria for production consideration

Experimental single-session cycles have a separate
[protocol/lab checklist](agent-cycle-protocol.md#migration-and-laboratory-validation).
Existing per-operation lab success does not validate session reuse. Keep
`FTD_SHUN_AGENT_CYCLES_ENABLED=false` until the new procedure is executed and
its evidence recorded; addition/import is still unavailable.

Do not treat polling or removal as production-ready until:

- the successful removal path has been observed on the supported FTD version;
- the typed complete snapshot path and SQLite reconciliation have been observed on the supported FTD version;
- if the trusted-IP policy will be enabled, its successful and fail-closed laboratory outcomes have been recorded;
- all required fail-closed checks have their recorded outcomes;
- approved sanitized fixtures cover the expected `show shun` variants; and
- the host egress and FTD SSH source restrictions have been independently reviewed.

