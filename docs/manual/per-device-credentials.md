# Per-Device FTD Credentials

## Scope and current rollout

The agent supports separate SSH logins and password files keyed by permanent
device ID. Public inventory remains credential-free. This is a configuration-only
migration: no database migration, managed-policy grant, ADD switch or restoration
activation is involved. Existing deployments retain explicit legacy `shared` mode.
The lab has **not** migrated its credentials; this manual is not that approval.

Use Basic accounts, pinned host keys and the management source-address restriction
in [Deployment](deployment.md). Do not grant Config to make authentication work.
DNS addresses/custom SSH ports and parallel execution are not implemented here;
connection addresses are still IPv4 and SSH uses TCP/22.

## Files and ownership

| File | Consumers | Contents |
| --- | --- | --- |
| `deploy/devices.json` | API and agent | Stable ID, hostname, IPv4, pinned host key, interface allowlist, enabled state and optional addition profile |
| `deploy/agent-credentials.json` | Agent only | Exact device ID, SSH login, password-secret basename |
| `deploy/secrets/ftd/<name>` | Agent only | That device's exact UTF-8 password bytes |

`.env` may set `FTD_SHUN_DEVICE_INVENTORY_PATH` to the public inventory's host path.
Relative paths resolve against `deploy/`, not the current shell directory. Keep
the same path for API and agent. Never reuse an ID for a replacement device.
An address change under the same ID preserves database links and credentials;
it does not authorize a different host key. Edit the public file and recreate
API/agent together when changing that file/path. The separately configured
[continuous observation runtime](configured-runtime.md) only asserts an already
matching DB projection: it refuses address/host-key/identity changes rather than
applying the legacy upsert behavior. Such changes require a future reviewed
inventory transition. Public files are bounded to 256 KiB and must be regular
files, not final symlinks/FIFOs/directories. Missing devices must not be
deleted/reassigned to discard history, pending cleanup or maintained policy.

Copy `deploy/agent-credentials.example.json` to the ignored private filename.
For example, a second device requires a separate entry:

```json
[
  {"device_id": 1, "username": "basic-office", "password_secret": "office.password"},
  {"device_id": 2, "username": "basic-branch", "password_secret": "branch.password"}
]
```

Include exactly every configured ID, including disabled devices. Names must be
distinct per-device secret references: 1–128 ASCII letters/digits/`.`/`_`/`-`,
starting with a letter/digit. No paths, traversal or shell syntax. Logins are
1–64 ASCII letters/digits/`.`/`_`/`-`/`@`. Unexpected/duplicate JSON fields, missing/
duplicate/unknown/zero IDs and oversized mappings (>256 KiB) fail closed.
This validates references, not password uniqueness or whether the FTD login works.
Do not put password values in JSON or `.env`. Public inventory rejects credential
and other unknown fields rather than silently ignoring them.

Provision regular, non-symlink files from an approved password store. Do not echo
passwords in a command, log or terminal transcript. For rootful Docker, grant only
agent UID10002 the needed host ACLs, for example after installing private files:

```bash
install -d -m 0700 deploy/secrets/ftd
chmod 0600 deploy/agent-credentials.json
setfacl -m u:10002:r-- deploy/agent-credentials.json
setfacl -m u:10002:r-x deploy/secrets/ftd
setfacl -m u:10002:r-- deploy/secrets/ftd/office.password
setfacl -m u:10002:r-- deploy/secrets/ftd/branch.password
```

Install password files with owner-only permissions before granting those ACLs;
do not broaden group/world access. Rootless Docker/Podman require separately
validated UID mappings. SELinux bind labels must also permit only the intended
container access; never disable SELinux globally to make a mount work.

Password files are read exactly (including any newline), must be nonempty UTF-8
and at most 16 KiB. Final symlinks, directories/FIFOs and oversized files are
rejected in both modes. Source buffers are zeroized after authentication/checks;
this is not a claim that SSH library/kernel copies never exist. Password files
remain mounted for reconnects. Directory mounts let an approved atomic secret
replacement be seen at the next authentication; existing SSH sessions are not
re-authenticated. Mapping/inventory changes require agent restart.

## Mode and deployment

`FTD_SHUN_SSH_CREDENTIALS_MODE` is one of:

- `shared` (compatibility default): require the legacy agent-only password file
  and `FTD_SHUN_SSH_USERNAME`. The base Compose file selects this explicitly.
- `per-device`: require `FTD_SHUN_SSH_CREDENTIALS_FILE`. Legacy shared variables
  are ignored, never used as a fallback. Missing/bad credentials or an SSH failure
  cannot try a neighboring device's credentials.

Use Compose 2.24.4+ for the overlay's `!reset` support. Include the overlay on
**every** subsequent Compose invocation/recreation, alongside the existing lab
overlay when applicable. It removes the shared secret mount and supplies only
agent-owned read-only mapping and secret-directory mounts; absent host sources
are errors, not silently created directories. API/Web receive neither mount.

Before a separately approved transition:

1. Record the existing image ID and exact Compose file set. Retain a private
   recoverable copy of current inventory, credential settings/files and ACLs.
   Keep backups outside every container mount/build context. A database restore
   is not needed for this increment; do not undo policy/audit to undo credentials.
2. Validate non-secret Compose settings without printing resolved environments.
   Review the merged agent mounts and ensure API/Web have no credential mounts.
3. Run the new image's non-network check with the proposed mounts:

   ```bash
   docker compose --env-file .env -f deploy/compose.yml \
     -f deploy/compose.per-device-credentials.yml \
     run --rm --no-deps agent --check-config
   ```

   The command validates inventory, gates, mapping and readability/format of all
   configured password files, then exits. It never binds the service socket,
   opens SSH, writes the database or executes queued work. Output includes only
   the credential mode and device count. Success is not proof of FTD authentication
   or host-key validity. Invalid arguments exit rather than starting a listener.
4. At an authorized quiescent point, recreate **only agent** with the same overlay.
   An interrupted write may be uncertain: wait for settled work; never replay it
   to test credentials. Reads/removals and cycles v1/v2/v3 all share the ID lookup.
5. Let ordinary read-only monitoring confirm authentication and host-key pinning.
   Observe API status and sanitized agent errors. Do not submit mutations or enable
   ADD/restoration merely to verify the migration. Keep all prior gates unchanged.

Add the local-lab overlay to the example command when that environment uses it.
Operators must not run the migration in the current lab without scoped approval
to change credentials/configuration. Compatible code deployment in shared mode
does not constitute such a migration.

## Failure and rollback

A wrong/missing mapping prevents startup. A later unreadable/empty password or
authentication failure rejects that operation without alternate credentials.
Current scheduling is still globally serialized; per-device outage isolation is
a later increment. A failed operation is not verified success.

Keep the existing paused/uncertainty handling before a rollback. Restore the
previous agent image and its **matching** Compose file set/settings/mounts and
still-valid credentials. An older agent ignores the new mode, so never run it
with the per-device overlay. If legacy credentials were revoked, image rollback
alone cannot restore access; use a separately approved credential recovery.
Restart ordinary monitoring and verify a fresh successful read. Preserve all
queue/policy/evidence records, host-key pins and feature gates; do not restore
old database state or clear uncertainty. Remove obsolete credential backups only
under the operator's credential-retention policy, not an application cleanup.

## Validation boundary

Rust tests cover ID selection, complete mapping, strict fields/bounds, no shared
fallback, secret-name/login checks, exact secret bytes, missing/invalid/oversized/
symlink secrets and process-isolated preflight with no listener. Python tests
cover credential-free inventory, strict types and stable-ID address updates.
Synthetic Compose/container checks verify mount isolation and preflight as the
non-root agent. None of these establish per-device live authentication, hardware
capacity, write readiness or production acceptance.
