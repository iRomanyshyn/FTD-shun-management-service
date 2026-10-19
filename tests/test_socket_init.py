"""Keep volume initialization bounded; private backup trees are not migrations."""

import json
import shlex
from pathlib import Path


def test_socket_initializer_changes_only_mount_roots():
    compose = (Path(__file__).resolve().parents[1] / "deploy/compose.yml").read_text()
    service = compose.split("  socket-init:\n", 1)[1].split("\n  caddy:", 1)[0]
    command = next(line.split("command:", 1)[1].strip() for line in service.splitlines()
                   if line.strip().startswith("command:"))
    shell, option, script = json.loads(command)
    assert (shell, option) == ("/bin/sh", "-ec")
    # An explicit allowlist prevents recursion, globs, child paths and added repair
    # primitives. Execution/permission behavior is also checked on disposable Docker
    # volumes during deployment validation; unit tests do not require Docker/root.
    assert [shlex.split(part) for part in script.split("&&")] == [
        ["mkdir", "-p", "/web", "/api", "/agent", "/state"],
        ["chown", "10001:10001", "/web", "/api", "/state"],
        ["chown", "0:0", "/agent"],
        ["chmod", "0770", "/agent"],
        ["chown", "10002:10001", "/agent"],
    ]
    assert "network_mode: none" in service
    assert "read_only: true" in service
    assert "security_opt: [no-new-privileges:true]" in service
    assert "cap_drop: [ALL]" in service
    assert "cap_add: [CHOWN]" in service
