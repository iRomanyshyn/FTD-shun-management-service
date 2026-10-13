//! Privileged, deliberately narrow FTD SSH agent.
//!
//! This binary accepts fixed AF_UNIX/SOCK_SEQPACKET requests only. Cisco CLI
//! strings are source-code constants; neither a command nor an interface name
//! can cross the Web/API-to-agent boundary.

use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::net::Ipv4Addr;
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
use std::os::unix::fs::{FileTypeExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result, bail};
use nix::sys::socket::{
    AddressFamily, Backlog, MsgFlags, SockFlag, SockType, UnixAddr, accept4, bind, getsockopt,
    listen, recv, send, socket,
};
use nix::sys::socket::sockopt::PeerCredentials;
use russh::client;
use russh::keys::{PrivateKeyWithHashAlg, PublicKey, PublicKeyOrCertificate, decode_secret_key};
use russh::{ChannelMsg, Disconnect};
use serde::Deserialize;
use tokio::runtime::Handle;
use tokio::time::timeout;
use zeroize::Zeroizing;

const RESPONSE_OK: [u8; 1] = [0x00];
const RESPONSE_REJECTED: [u8; 1] = [0x01];
const MAX_REQUEST_BYTES: usize = 8;
const MAX_CISCO_OUTPUT_BYTES: usize = 64 * 1024;
const SHOW_SHUN_PREFIX: &str = "show shun ";
const REMOVE_SHUN_PREFIX: &str = "no shun ";

#[derive(Clone)]
struct Agent {
    devices: BTreeMap<u16, Device>,
    username: String,
    private_key_file: PathBuf,
    operation_timeout: Duration,
}

#[derive(Clone)]
struct Device {
    management_ip: Ipv4Addr,
    pinned_host_key: PublicKey,
    allowed_interfaces: BTreeSet<String>,
    enabled: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct InventoryDevice {
    id: u16,
    hostname: String,
    management_ip: Ipv4Addr,
    ssh_host_key: String,
    #[serde(default = "enabled_by_default")]
    enabled: bool,
    allowed_interfaces: Vec<String>,
}

fn enabled_by_default() -> bool {
    true
}

impl Agent {
    fn from_environment() -> Result<(Self, PathBuf, u32)> {
        let inventory_file = required_env_path("FTD_SHUN_DEVICE_INVENTORY")?;
        let raw_inventory = fs::read_to_string(&inventory_file)
            .with_context(|| format!("could not read inventory {}", inventory_file.display()))?;
        let inventory: Vec<InventoryDevice> = serde_json::from_str(&raw_inventory)
            .context("device inventory is not valid JSON")?;
        if inventory.is_empty() {
            bail!("device inventory cannot be empty");
        }

        let mut devices = BTreeMap::new();
        for entry in inventory {
            if entry.hostname.trim().is_empty() || entry.hostname.len() > 255 {
                bail!("inventory has an invalid hostname for device {}", entry.id);
            }
            let host_key = PublicKey::from_openssh(entry.ssh_host_key.trim())
                .with_context(|| format!("inventory host key is invalid for device {}", entry.id))?;
            if entry.allowed_interfaces.is_empty() {
                bail!("device {} must declare at least one allowed interface", entry.id);
            }
            let mut allowed_interfaces = BTreeSet::new();
            for interface in entry.allowed_interfaces {
                if !is_safe_interface(&interface) {
                    bail!("device {} has an invalid allowed interface", entry.id);
                }
                if !allowed_interfaces.insert(interface) {
                    bail!("device {} has duplicate allowed interfaces", entry.id);
                }
            }
            if devices
                .insert(
                    entry.id,
                    Device {
                        management_ip: entry.management_ip,
                        pinned_host_key: host_key,
                        allowed_interfaces,
                        enabled: entry.enabled,
                    },
                )
                .is_some()
            {
                bail!("inventory has duplicate device ID {}", entry.id);
            }
        }

        let socket_file = env_path("FTD_SHUN_AGENT_SOCKET", "/run/ftd-shun-manager-agent/agent.sock");
        let peer_uid = env_u32("FTD_SHUN_AGENT_PEER_UID", 10001)?;
        let operation_timeout = Duration::from_secs(env_u64("FTD_SHUN_AGENT_TIMEOUT_SECONDS", 45)?);
        if !(5..=120).contains(&operation_timeout.as_secs()) {
            bail!("FTD_SHUN_AGENT_TIMEOUT_SECONDS must be between 5 and 120");
        }

        Ok((
            Self {
                devices,
                username: required_env("FTD_SHUN_SSH_USERNAME")?,
                private_key_file: required_env_path("FTD_SHUN_SSH_PRIVATE_KEY_FILE")?,
                operation_timeout,
            },
            socket_file,
            peer_uid,
        ))
    }

    async fn remove_shun(&self, device_id: u16, target: Ipv4Addr) -> Result<()> {
        let device = self
            .devices
            .get(&device_id)
            .filter(|device| device.enabled)
            .context("unknown or disabled device")?;
        let private_key = load_private_key(&self.private_key_file)?;
        let mut session = SshSession::connect(device, &self.username, private_key).await?;

        let before = session.show_shun(target).await?;
        let interfaces = parse_show_shun(&before, target, &device.allowed_interfaces)?;
        for interface in interfaces {
            session.remove_shun(target, &interface).await?;
        }

        let after = session.show_shun(target).await?;
        if !parse_show_shun(&after, target, &device.allowed_interfaces)?.is_empty() {
            bail!("FTD still reports the target shun after removal verification");
        }
        session.close().await;
        Ok(())
    }
}

struct HostKeyVerifier {
    pinned: PublicKey,
}

impl client::Handler for HostKeyVerifier {
    type Error = russh::Error;

    async fn check_server_key(
        &mut self,
        presented: &PublicKeyOrCertificate,
    ) -> std::result::Result<bool, Self::Error> {
        Ok(presented.public_key() == self.pinned)
    }
}

struct SshSession {
    handle: client::Handle<HostKeyVerifier>,
}

impl SshSession {
    async fn connect(device: &Device, username: &str, private_key: russh::keys::PrivateKey) -> Result<Self> {
        let configuration = client::Config {
            inactivity_timeout: Some(Duration::from_secs(15)),
            ..Default::default()
        };
        let mut handle = client::connect(
            Arc::new(configuration),
            (device.management_ip.to_string(), 22),
            HostKeyVerifier {
                pinned: device.pinned_host_key.clone(),
            },
        )
        .await
        .context("SSH connection or host-key verification failed")?;

        let key = PrivateKeyWithHashAlg::new(
            Arc::new(private_key),
            handle.best_supported_rsa_hash().await?.flatten(),
        );
        let authenticated = handle
            .authenticate_publickey(username, key)
            .await
            .context("SSH public-key authentication failed")?;
        if !authenticated.success() {
            bail!("SSH public-key authentication was rejected");
        }
        Ok(Self { handle })
    }

    async fn show_shun(&mut self, target: Ipv4Addr) -> Result<String> {
        self.execute(&format!("{SHOW_SHUN_PREFIX}{target}")).await
    }

    async fn remove_shun(&mut self, target: Ipv4Addr, interface: &str) -> Result<()> {
        if !is_safe_interface(interface) {
            bail!("attempted to use an unsafe interface name");
        }
        let output = self
            .execute(&format!("{REMOVE_SHUN_PREFIX}{target} interface {interface}"))
            .await?;
        if output.len() > MAX_CISCO_OUTPUT_BYTES {
            bail!("FTD removal response exceeded the maximum size");
        }
        Ok(())
    }

    async fn execute(&mut self, command: &str) -> Result<String> {
        let mut channel = self.handle.channel_open_session().await?;
        channel.exec(true, command).await?;
        let mut output = Vec::new();
        let mut exit_status = None;
        while let Some(message) = channel.wait().await {
            match message {
                ChannelMsg::Data { data } => {
                    if output.len().saturating_add(data.len()) > MAX_CISCO_OUTPUT_BYTES {
                        bail!("FTD command response exceeded the maximum size");
                    }
                    output.extend_from_slice(&data);
                }
                ChannelMsg::ExitStatus { exit_status: status } => exit_status = Some(status),
                _ => {}
            }
        }
        if exit_status != Some(0) {
            bail!("FTD command returned a non-zero status");
        }
        String::from_utf8(output).context("FTD command output was not UTF-8")
    }

    async fn close(self) {
        let _ = self
            .handle
            .disconnect(Disconnect::ByApplication, "", "en")
            .await;
    }
}

fn load_private_key(path: &Path) -> Result<russh::keys::PrivateKey> {
    let encoded = Zeroizing::new(
        fs::read_to_string(path)
            .with_context(|| format!("could not read private-key secret {}", path.display()))?,
    );
    decode_secret_key(&encoded, None).context("could not decode the SSH private key")
}

#[derive(Copy, Clone, Debug, Eq, PartialEq)]
enum Operation {
    ListShuns = 0x01,
    GetShun = 0x02,
    RemoveShun = 0x03,
    GetRaAuthStatus = 0x04,
    GetRaInitStatus = 0x05,
    Health = 0x06,
}

fn decode_request(packet: &[u8]) -> Result<(Operation, u16, Option<Ipv4Addr>)> {
    let Some(opcode) = packet.first().copied() else {
        bail!("empty request");
    };
    let operation = match opcode {
        0x01 => Operation::ListShuns,
        0x02 => Operation::GetShun,
        0x03 => Operation::RemoveShun,
        0x04 => Operation::GetRaAuthStatus,
        0x05 => Operation::GetRaInitStatus,
        0x06 => Operation::Health,
        _ => bail!("unknown operation"),
    };
    let accepts_ip = matches!(operation, Operation::GetShun | Operation::RemoveShun);
    if packet.len() != if accepts_ip { 7 } else { 3 } {
        bail!("invalid packet length");
    }
    let device_id = u16::from_be_bytes([packet[1], packet[2]]);
    if device_id == 0 {
        bail!("device ID zero is invalid");
    }
    let ip = accepts_ip.then(|| Ipv4Addr::new(packet[3], packet[4], packet[5], packet[6]));
    Ok((operation, device_id, ip))
}

fn parse_show_shun(
    output: &str,
    target: Ipv4Addr,
    allowed_interfaces: &BTreeSet<String>,
) -> Result<BTreeSet<String>> {
    let mut interfaces = BTreeSet::new();
    for line in output.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let remainder = line
            .strip_prefix("shun (")
            .context("unexpected FTD show shun output")?;
        let (interface, fields) = remainder
            .split_once(") ")
            .context("malformed FTD shun entry")?;
        if !is_safe_interface(interface) || !allowed_interfaces.contains(interface) {
            bail!("FTD reported an interface outside the configured allowlist");
        }
        let reported_ip = fields
            .split_ascii_whitespace()
            .next()
            .context("FTD shun entry omitted an IPv4 address")?
            .parse::<Ipv4Addr>()
            .context("FTD shun entry contained an invalid IPv4 address")?;
        if reported_ip != target {
            bail!("FTD show shun returned an unexpected target address");
        }
        interfaces.insert(interface.to_owned());
    }
    Ok(interfaces)
}

fn is_safe_interface(interface: &str) -> bool {
    let bytes = interface.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= 64
        && bytes[0].is_ascii_alphabetic()
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'/' | b'.' | b'_' | b'-'))
}

fn serve(agent: Agent, socket_file: PathBuf, peer_uid: u32, runtime: Handle) -> Result<()> {
    remove_existing_socket(&socket_file)?;
    let listener = socket(
        AddressFamily::Unix,
        SockType::SeqPacket,
        SockFlag::SOCK_CLOEXEC,
        None,
    )?;
    bind(listener.as_raw_fd(), &UnixAddr::new(&socket_file)?)?;
    fs::set_permissions(&socket_file, fs::Permissions::from_mode(0o660))?;
    listen(&listener, Backlog::new(16)?)?;

    loop {
        let connection = accept_connection(listener.as_raw_fd())?;
        let response = match getsockopt(&connection, PeerCredentials) {
            Ok(credentials) if credentials.uid() == peer_uid => {
                handle_connection(&agent, connection.as_raw_fd(), &runtime)
            }
            Ok(_) => RESPONSE_REJECTED,
            Err(_) => RESPONSE_REJECTED,
        };
        let _ = send(connection.as_raw_fd(), &response, MsgFlags::empty());
    }
}

fn accept_connection(listener: std::os::fd::RawFd) -> Result<OwnedFd> {
    let raw_fd = accept4(listener, SockFlag::SOCK_CLOEXEC)?;
    // `accept4` transfers a newly allocated descriptor to this process. Converting
    // it immediately gives Rust ownership, so it is closed on every path below.
    Ok(unsafe { OwnedFd::from_raw_fd(raw_fd) })
}

fn handle_connection(agent: &Agent, connection: std::os::fd::RawFd, runtime: &Handle) -> [u8; 1] {
    let mut packet = [0u8; MAX_REQUEST_BYTES];
    let received = match recv(connection, &mut packet, MsgFlags::empty()) {
        Ok(received) => received,
        Err(_) => return RESPONSE_REJECTED,
    };
    let (operation, device_id, ip) = match decode_request(&packet[..received]) {
        Ok(request) => request,
        Err(_) => return RESPONSE_REJECTED,
    };
    match operation {
        Operation::Health if agent.devices.get(&device_id).is_some_and(|device| device.enabled) => {
            RESPONSE_OK
        }
        Operation::RemoveShun => {
            let Some(ip) = ip else {
                return RESPONSE_REJECTED;
            };
            match runtime.block_on(timeout(agent.operation_timeout, agent.remove_shun(device_id, ip))) {
                Ok(Ok(())) => RESPONSE_OK,
                Ok(Err(_)) | Err(_) => RESPONSE_REJECTED,
            }
        }
        Operation::Health
        | Operation::ListShuns
        | Operation::GetShun
        | Operation::GetRaAuthStatus
        | Operation::GetRaInitStatus => {
            RESPONSE_REJECTED
        }
    }
}

fn remove_existing_socket(path: &Path) -> Result<()> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_socket() => fs::remove_file(path)
            .with_context(|| format!("could not remove stale socket {}", path.display())),
        Ok(_) => bail!("refusing to replace non-socket path {}", path.display()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error).with_context(|| format!("could not inspect socket {}", path.display())),
    }
}

fn required_env(name: &str) -> Result<String> {
    let value = env::var(name).with_context(|| format!("{name} is required"))?;
    if value.trim().is_empty() {
        bail!("{name} must not be empty");
    }
    Ok(value)
}

fn required_env_path(name: &str) -> Result<PathBuf> {
    Ok(PathBuf::from(required_env(name)?))
}

fn env_path(name: &str, default: &str) -> PathBuf {
    PathBuf::from(env::var(name).unwrap_or_else(|_| default.to_owned()))
}

fn env_u32(name: &str, default: u32) -> Result<u32> {
    match env::var(name) {
        Ok(value) => value.parse().with_context(|| format!("{name} must be an integer")),
        Err(env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(error).with_context(|| format!("could not read {name}")),
    }
}

fn env_u64(name: &str, default: u64) -> Result<u64> {
    match env::var(name) {
        Ok(value) => value.parse().with_context(|| format!("{name} must be an integer")),
        Err(env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(error).with_context(|| format!("could not read {name}")),
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let (agent, socket_file, peer_uid) = Agent::from_environment()?;
    let runtime = Handle::current();
    tokio::task::spawn_blocking(move || serve(agent, socket_file, peer_uid, runtime))
        .await
        .context("agent listener thread stopped unexpectedly")??;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn interfaces() -> BTreeSet<String> {
        ["inside", "outside"]
            .into_iter()
            .map(str::to_owned)
            .collect()
    }

    #[test]
    fn fixed_binary_remove_request_is_decoded() {
        assert_eq!(
            decode_request(&[0x03, 0x00, 0x07, 203, 0, 113, 17]).unwrap(),
            (Operation::RemoveShun, 7, Some(Ipv4Addr::new(203, 0, 113, 17)))
        );
    }

    #[test]
    fn malformed_requests_are_rejected() {
        for packet in [vec![], vec![3, 0, 7], vec![3, 0, 0, 203, 0, 113, 17], vec![255, 0, 1]] {
            assert!(decode_request(&packet).is_err());
        }
    }

    #[test]
    fn parser_accepts_only_allowed_interfaces_for_the_requested_ip() {
        let output = "shun (outside) 203.0.113.17 10.0.0.1 123 443 6\nshun (inside) 203.0.113.17 10.0.0.2 456 443 6\n";
        assert_eq!(
            parse_show_shun(output, Ipv4Addr::new(203, 0, 113, 17), &interfaces()).unwrap(),
            interfaces()
        );
    }

    #[test]
    fn parser_fails_closed_on_unknown_interface_or_unexpected_text() {
        let target = Ipv4Addr::new(203, 0, 113, 17);
        assert!(parse_show_shun("shun (dmz) 203.0.113.17\n", target, &interfaces()).is_err());
        assert!(parse_show_shun("ERROR: invalid input\n", target, &interfaces()).is_err());
    }
}
