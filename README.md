# FTD Shun Management Service

![FTD Shun Management Service — Monitor. Block. Unblock.](static/branding/banners/readme-banner.png)

An internal Web service for monitoring and managing Cisco FTD `shun` entries
across multiple devices. The project is unreleased and runs on a desk FPR1010
laboratory device; it has no production deployment.

## What it does

- **Shuns / Unmanaged:** browse and search observed blocks and retained history,
  with bounded 100-row pages and cached country/provider context.
- **Managed shuns / Imports:** import pasted IPv4 lists, choose devices and keep
  accepted addresses blocked through automatic restoration after disappearance.
  Readable import links show which device/IP pairs the import still manages,
  separately from skipped, replaced and historical entries.
- **Unblock:** review a device or fleet scope, stop matching restoration and queue
  removal. Interactive refresh and removals take priority over bulk additions.
- **Protected IPs:** all signed-in users can maintain exact addresses that should
  be automatically unblocked. Enabling protection retires matching restoration;
  disabling protection does not re-enable it.
- **Deployment protection:** optional IPv4 addresses/CIDRs from
  `FTD_SHUN_ENV_PROTECTED_NETWORKS` in `.env` cannot be imported or added. Matches
  found on a device are queued for unblocking, with distinct detection/result logs.
  These ranges are visible but cannot be edited in the Web UI.
- **Status / Queue:** independent import/restoration pauses, live progress,
  cancellation and explicit attention for uncertain outcomes.

The architecture is Web/BFF → local Unix socket → state API/SQLite → local Unix
socket → Rust SSH agent → FTD. Caddy and Authelia provide HTTPS and sign-in. Only
Caddy publishes a port; Web/API have no network interfaces. FTD credentials stay
with the agent. A separate background worker supplies cached IPFire/Team Cymru
context without page-triggered provider calls.

See [System Architecture and Data Formats](docs/manual/system-architecture.md)
for the complete component/storage diagram and concrete payload formats.

## Current delivery boundary

API/Web **0.18.1** include current-import ownership and confirmed whole-import
unblocking, with rolling verified removal, progress and cancellation. Recovery
refuses to bypass active cleanup and links its task for an explicit decision.
Shared typography and local **?** help remain. See
[Import Unblocking](docs/manual/import-unblocking.md) and
[Interrupted Import Recovery](docs/manual/interrupted-v7-recovery.md).
Consult [Project Status](docs/project-status.md) for exact deployed images,
validation and limitations; a source version does not deploy itself.

The current lab uses the continuous managed runtime with tracked v6 SSH visits.
Deferred confirmation after a later complete `show shun` read is implemented and
has bounded separate-profile interruption/lifecycle acceptance, but persistent v7
activation and wider scale/multi-device acceptance remain pending. An uncertain historical
operation is retained in audit; a later observation does not prove who created it.

Next work is deferred-import failure/lifecycle validation, measured throughput and
deliberate selection of a fresh deferred profile. Whole-managed cleanup and
email/Teams alerts are later increments. The
[Working-Version Plan](docs/working-version-plan.md) records agreed behavior;
it is not a deployment procedure.

## Run the lab

Follow the [Deployment Manual](docs/manual/deployment.md) and
[Fresh Working-Version Lab](docs/manual/fresh-development.md). They cover local
names/TLS, Authelia, inventory, agent-only credentials and explicit fresh-store
setup. Keep old test state as a private archive rather than overwriting it.

Deployment-owned protection is described in
[Environment IP Protection](docs/manual/environment-protection.md).

## Develop and verify

Python 3.12+ and Rust/Cargo are required for the complete application/agent checks.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q
cargo test --locked --manifest-path agent/Cargo.toml
```

The dev extra includes the DNS dependency used by the synthetic Cymru tests;
ordinary application images do not install that optional worker dependency.
[GitHub checks](.github/workflows/checks.yml) run Python tests/lint and Rust
formatting/lint/tests. Browser and device acceptance remain separate checks.
See the [Development Manual](docs/manual/development.md) for those commands.

Confirmed per-import cleanup can retire this import's currently owned rules and
queue verified unblocking with one progress card and cancellation. It requires the
optional cleanup profile; see [Unblock imported IPs](docs/manual/import-unblocking.md).

## Documentation and contributor records

Start with the [manual index](docs/manual/README.md),
[architecture and security design](docs/architecture-and-security-design.md),
[current status](docs/project-status.md) and [versioning](docs/manual/versioning.md).

Follow [AGENTS.md](AGENTS.md). Record material changes and validation in the
[development log](docs/development-log.md), update current status and advance the
product version for each cohesive delivery. Formal released-data compatibility
starts with the first operator-designated GitHub release/tag; core security and
honest results apply throughout development.
