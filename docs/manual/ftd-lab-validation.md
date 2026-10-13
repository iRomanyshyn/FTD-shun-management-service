# FTD Laboratory Validation

This procedure validates the existing removal agent and collects safe parser fixtures before polling or read RPC is implemented. Run it only against a non-production FTD under the organization's normal change process.

## Objectives

1. Confirm that the agent can authenticate with the pinned host key and dedicated service identity.
2. Capture the exact supported `show shun` output shape for parser fixtures.
3. Validate a single device-scoped removal and its post-write verification.
4. Confirm that expected security failures are fail-closed.

Do not use this procedure to create shuns, alter FTD configuration, or test against a production device. The product has no shun-creation operation.

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

This validates the current parser's observed line shape, the empty-output case, and the agent's explicit `no shun <IPv4> interface management` command form. It does **not** yet validate pinned-host-key authentication or the full service path.

The same removal was then performed by a newly created local user with the FTD `Basic` role. This establishes that, on this FPR1010 / FTD 7.6.6 fixture, `Basic` is sufficient for the product's required read and removal commands. Do not promote the product account to `Config` for this version.

Interactive SSH with a PTY successfully reached the FTD `>` prompt after the login banner. The banner took approximately 1.5 seconds in the observed lab session. This is a compatibility requirement for the agent, not a delay value: the agent waits for the prompt within its operation timeout and never uses a fixed login sleep. Plain SSH `exec` mode was rejected by the FTD login path and is intentionally unsupported by the agent.

## Validate the current removal path

Choose an existing, approved lab shun whose target IPv4 and affected interfaces are known. Do not use a production address.

1. Record the direct pre-operation `show shun <IPv4>` output.
2. Open the Web/BFF, confirm the displayed device hostname and interface summary, and select **Remove from this device**.
3. Confirm that the UI reports success only after the agent finishes.
4. Record the direct post-operation `show shun <IPv4>` output.
5. Confirm that the target no longer appears and that SQLite history contains `SHUN_REMOVE_REQUESTED` followed by `SHUN_REMOVED_BY_UI` for the correct device, actor, and request ID.
6. Record the test timestamp, FTD version, agent image digest, inventory revision, and outcome in the deployment change record.

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

Do not intentionally test malformed Cisco output on a production FTD. Use sanitized fixtures and agent unit tests for parser-negative cases.

## Exit criteria for the next milestone

The project may begin typed list/read RPC, polling, and reconciliation only when:

- the successful removal path has been observed on the supported FTD version;
- all required fail-closed checks have their recorded outcomes;
- approved sanitized fixtures cover the expected `show shun` variants; and
- the host egress and FTD SSH source restrictions have been independently reviewed.

