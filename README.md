# FTD Shun Management Service

Security-focused internal service for monitoring and managing Cisco Secure Firewall Threat Defense (FTD) `shun` entries.

This repository is currently in the design phase. The governing specification is the [Architecture and Security Design](docs/architecture-and-security-design.md).

## Design goals

- Monitor, reconcile, and retain the history of active FTD shuns.
- Allow operators to remove a specific shun through a secured web interface.
- Prevent arbitrary Cisco CLI execution at every trust boundary.
- Isolate the privileged SSH capability and Cisco credential material.
- Use default-deny network segmentation and hardened containers.

## Status

No application code has been added yet. The next implementation work should follow the acceptance criteria and the preferred technology stack defined in the design document.
