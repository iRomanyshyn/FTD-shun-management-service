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
2. Create a dedicated FTD lab service account and install only the approved public key.
3. Collect the FTD SSH public host key through an approved out-of-band method. Put the full OpenSSH public-key line in `ssh_host_key`; do not rely on TOFU or automatic enrollment.
4. Populate `allowed_interfaces` with the lab interfaces that may contain the selected test shun.
5. Enforce the host/network egress rule allowing the agent host only to the configured FTD management IPv4 address on TCP/22. Configure the corresponding FTD SSH source restriction.
6. Supply the matching private key only through `deploy/secrets/ftd_ssh_private_key`. Never paste it into an issue, chat, fixture, `.env`, or Git.

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

Do not intentionally test malformed Cisco output on a production FTD. Use sanitized fixtures and agent unit tests for parser-negative cases.

## Exit criteria for the next milestone

The project may begin typed list/read RPC, polling, and reconciliation only when:

- the successful removal path has been observed on the supported FTD version;
- all required fail-closed checks have their recorded outcomes;
- approved sanitized fixtures cover the expected `show shun` variants; and
- the host egress and FTD SSH source restrictions have been independently reviewed.

