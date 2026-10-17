# Versioning and Release Identification

## Current implementation

The product version is assigned manually in
[`src/ftd_shun_manager/__init__.py`](../../src/ftd_shun_manager/__init__.py)
as `__version__ = "0.1.0"`. This is the single source for the Python package
version and the Web footer. Hatch reads it through `tool.hatch.version` in
[`pyproject.toml`](../../pyproject.toml); Jinja displays it with a `v` prefix.
The prefix is presentation only, not part of the stored package version.

Commits, tests, container builds, deployments and restarts do not increment the
version. No Git tag, commit count, timestamp or environment override currently
participates. Multiple development builds can therefore display the same number;
the footer alone does not identify their exact source or container image.
Retain image IDs/tags and deployment records for exact rollout/rollback evidence.

The Rust agent has its own crate version in
[`agent/Cargo.toml`](../../agent/Cargo.toml); it is not automatically synchronized
with the Python version. Fixed binary protocol versions and future parser
versions are separate compatibility identifiers, not the product release number.

## Release numbering convention

Use `MAJOR.MINOR.PATCH`, with manual, reviewed changes:

- `PATCH`: compatible fixes or small refinements, for example `0.1.0` to `0.1.1`.
- `MINOR`: a new feature increment, for example `0.1.1` to `0.2.0`.
- `MAJOR`: incompatible changes after the stable public contract is established.

During `0.x` development, the product is not stable: incompatible changes also
require a minor increment and explicit migration/rollback notes. Do not hide a
breaking schema, configuration or API change in a patch release. From `1.0.0`,
minor releases preserve the documented stable contract; breaking changes require
a major increment. Increasing a component/protocol version does not waive its
compatibility checks or release gates.

`1.0.0` must be a deliberate stable-release decision after the documented
acceptance checks, not an automatic consequence of feature count or elapsed
time. A version is never proof of production readiness, live validation or
enabled ADD/restoration gates. Consult [Project Status](../project-status.md)
and the [Architecture and Security Design](../architecture-and-security-design.md).

## Manual release procedure

1. Choose the number from the actual release scope and update `__version__`.
   Do not maintain a second literal in templates or `pyproject.toml`.
2. Update project status, append the development log, and document any relevant
   compatibility, migration and rollback requirements. Review agent version
   changes separately when that component changes.
3. Run the checks applicable to the change in the
   [Development Manual](development.md), including package/footer consistency.
   Build the release artifacts and verify their installed package metadata and
   rendered footer agree. A released version must not be reused for changed
   release artifacts; issue a new version instead.
4. Deploy only within the authorized environment and feature gates. Follow the
   [Deployment Manual](deployment.md), retain rollback artifacts, and record the
   version, exact image identities and validation outcome. Editing the source
   alone does not update a running container.

## Planned development-build identity — not implemented

A future build pipeline may add a Python-compatible development version such
as `0.2.0.dev3` and a separate short Git revision, displayed for example as
`v0.2.0.dev3 · a1b2c3d`. These are examples, not the current version or an
automatic counter already in use. Build identity should be captured at build
time, including how a dirty source tree is identified; Web must not inspect Git,
host information or secrets at request time. Any such automation requires its
own implementation and validation before operators may rely on it.
