//! Isolated process environment: no test mutates its parent's deployment settings.

use std::fs;
use std::os::unix::fs::DirBuilderExt;
use std::path::PathBuf;
use std::process::{Command, Output};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result};

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Result<Self> {
        let dir = std::env::temp_dir().join(format!(
            "ftd-agent-config-{}-{}",
            std::process::id(),
            SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos()
        ));
        fs::DirBuilder::new().mode(0o700).create(&dir)?;
        fs::write(
            dir.join("devices.json"),
            serde_json::to_vec(&serde_json::json!([{
                "id": 1, "hostname": "synthetic-only", "management_ip": "192.0.2.1",
                "ssh_host_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                "allowed_interfaces": ["management"]
            }]))?,
        )?;
        fs::write(dir.join("password"), "synthetic-secret-never-log")?;
        Ok(Self(dir))
    }

    fn command(&self) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_ftd-shun-agent"));
        command
            .env_clear()
            .env("FTD_SHUN_DEVICE_INVENTORY", self.0.join("devices.json"))
            .env("FTD_SHUN_SSH_USERNAME", "synthetic-basic")
            .env("FTD_SHUN_SSH_PASSWORD_FILE", self.0.join("password"))
            .env("FTD_SHUN_AGENT_SOCKET", self.0.join("must-not-bind.sock"));
        command
    }

    fn run(&self, command: &mut Command) -> Result<Output> {
        let output = command.arg("--check-config").output()?;
        assert!(!self.0.join("must-not-bind.sock").exists());
        for buffer in [&output.stdout, &output.stderr] {
            assert!(!String::from_utf8_lossy(buffer).contains("synthetic-secret-never-log"));
        }
        Ok(output)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        // Only this private synthetic directory; never a deployment path.
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn compatibility_check_exits_without_socket_or_ssh() -> Result<()> {
    let fixture = Fixture::new()?;
    for explicit in [false, true] {
        let mut command = fixture.command();
        if explicit {
            command.env("FTD_SHUN_SSH_CREDENTIALS_MODE", "shared");
        }
        let output = fixture.run(&mut command)?;
        assert!(output.status.success());
        let result: serde_json::Value = serde_json::from_slice(&output.stdout)?;
        assert_eq!(result["credential_mode"], "shared");
        assert_eq!(result["devices"], 1);
    }
    Ok(())
}

#[test]
fn invalid_and_incomplete_per_device_mode_never_uses_valid_shared_credentials() -> Result<()> {
    let fixture = Fixture::new()?;
    for mode in ["", "per_device", "unexpected"] {
        let mut command = fixture.command();
        command.env("FTD_SHUN_SSH_CREDENTIALS_MODE", mode);
        assert!(!fixture.run(&mut command)?.status.success());
    }
    let mut command = fixture.command();
    command.env("FTD_SHUN_SSH_CREDENTIALS_MODE", "per-device");
    let output = fixture.run(&mut command)?;
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("FTD_SHUN_SSH_CREDENTIALS_FILE"));
    for raw in [b"[]".as_slice(), b"not-json", b"[{\"device_id\":true}]"] {
        let path = fixture.0.join("credentials.json");
        fs::write(&path, raw)?;
        let mut command = fixture.command();
        command
            .env("FTD_SHUN_SSH_CREDENTIALS_MODE", "per-device")
            .env("FTD_SHUN_SSH_CREDENTIALS_FILE", &path);
        assert!(!fixture.run(&mut command)?.status.success());
    }
    let mut command = fixture.command();
    command
        .env("FTD_SHUN_SSH_CREDENTIALS_MODE", "per-device")
        .env("FTD_SHUN_SSH_CREDENTIALS_FILE", fixture.0.join("absent"));
    assert!(!fixture.run(&mut command)?.status.success());
    Ok(())
}

#[test]
fn unknown_cli_arguments_do_not_start_a_listener() -> Result<()> {
    let fixture = Fixture::new()?;
    let output = fixture.command().arg("--unsupported").output()?;
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("usage:"));
    assert!(!fixture.0.join("must-not-bind.sock").exists());
    Ok(())
}

#[test]
fn zero_or_duplicate_inventory_identity_is_rejected_in_preflight() -> Result<()> {
    let fixture = Fixture::new()?;
    let path = fixture.0.join("devices.json");
    let original: serde_json::Value = serde_json::from_slice(&fs::read(&path)?)?;
    for duplicate in [false, true] {
        let mut inventory = original.clone();
        if duplicate {
            let mut second = inventory[0].clone();
            second["id"] = 2.into();
            inventory.as_array_mut().context("array")?.push(second);
        } else {
            inventory[0]["id"] = 0.into();
        }
        fs::write(&path, serde_json::to_vec(&inventory)?)?;
        assert!(!fixture.run(&mut fixture.command())?.status.success());
    }
    Ok(())
}
