//! Privileged, deliberately narrow FTD SSH agent.
//!
//! This binary accepts fixed AF_UNIX/SOCK_SEQPACKET requests only. Cisco CLI
//! strings are source-code constants; neither a command nor an interface name
//! can cross the Web/API-to-agent boundary.

mod cycle;

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
use nix::sys::socket::sockopt::PeerCredentials;
use nix::sys::socket::{
    AddressFamily, Backlog, MsgFlags, SockFlag, SockType, UnixAddr, accept4, bind, getsockopt,
    listen, recv, send, socket,
};
use russh::client;
use russh::keys::{PublicKey, PublicKeyOrCertificate};
use russh::{Channel, ChannelMsg, Disconnect};
use serde::Deserialize;
use tokio::runtime::Handle;
use tokio::time::timeout;
use zeroize::Zeroizing;

const RESPONSE_OK: [u8; 1] = [0x00];
const RESPONSE_REJECTED: [u8; 1] = [0x01];
const MAX_REQUEST_BYTES: usize = 8;
const MAX_AGENT_RESPONSE_BYTES: usize = 64 * 1024;
const MAX_CISCO_OUTPUT_BYTES: usize = 64 * 1024;
const FTD_INTERACTION_TIMEOUT: Duration = Duration::from_secs(15);
const SHOW_SHUN_PREFIX: &str = "show shun ";
const REMOVE_SHUN_PREFIX: &str = "no shun ";
const FTD_PROMPT: &[u8] = b"> ";

#[derive(Clone)]
struct Agent {
    devices: BTreeMap<u16, Device>,
    username: String,
    password_file: PathBuf,
    operation_timeout: Duration,
    cycles_enabled: bool,
}

#[derive(Clone)]
struct Device {
    management_ip: Ipv4Addr,
    pinned_host_key: PublicKey,
    allowed_interfaces: BTreeSet<String>,
    enabled: bool,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct ObservedShun {
    target: Ipv4Addr,
    interface: String,
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
        let inventory: Vec<InventoryDevice> =
            serde_json::from_str(&raw_inventory).context("device inventory is not valid JSON")?;
        if inventory.is_empty() {
            bail!("device inventory cannot be empty");
        }

        let mut devices = BTreeMap::new();
        for entry in inventory {
            if entry.hostname.trim().is_empty() || entry.hostname.len() > 255 {
                bail!("inventory has an invalid hostname for device {}", entry.id);
            }
            let host_key =
                PublicKey::from_openssh(entry.ssh_host_key.trim()).with_context(|| {
                    format!("inventory host key is invalid for device {}", entry.id)
                })?;
            if entry.allowed_interfaces.is_empty() {
                bail!(
                    "device {} must declare at least one allowed interface",
                    entry.id
                );
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

        let socket_file = env_path(
            "FTD_SHUN_AGENT_SOCKET",
            "/run/ftd-shun-manager-agent/agent.sock",
        );
        let peer_uid = env_u32("FTD_SHUN_AGENT_PEER_UID", 10001)?;
        let operation_timeout = Duration::from_secs(env_u64("FTD_SHUN_AGENT_TIMEOUT_SECONDS", 45)?);
        if !(5..=120).contains(&operation_timeout.as_secs()) {
            bail!("FTD_SHUN_AGENT_TIMEOUT_SECONDS must be between 5 and 120");
        }
        let cycles_enabled = match env::var("FTD_SHUN_AGENT_CYCLES_ENABLED").as_deref() {
            Ok("true") => true,
            Ok("false") | Err(env::VarError::NotPresent) => false,
            _ => bail!("FTD_SHUN_AGENT_CYCLES_ENABLED must be true or false"),
        };

        Ok((
            Self {
                devices,
                username: required_env("FTD_SHUN_SSH_USERNAME")?,
                password_file: required_env_path("FTD_SHUN_SSH_PASSWORD_FILE")?,
                operation_timeout,
                cycles_enabled,
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
        let mut session = {
            let password = load_ssh_password(&self.password_file)?;
            SshSession::connect(device, &self.username, password.as_str()).await?
        };

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

    async fn list_shuns(&self, device_id: u16) -> Result<BTreeSet<ObservedShun>> {
        let device = self
            .devices
            .get(&device_id)
            .filter(|device| device.enabled)
            .context("unknown or disabled device")?;
        let mut session = {
            let password = load_ssh_password(&self.password_file)?;
            SshSession::connect(device, &self.username, password.as_str()).await?
        };
        let entries = session.list_shuns(&device.allowed_interfaces).await?;
        session.close().await;
        Ok(entries)
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
    channel: Channel<client::Msg>,
}

enum CiscoOperation {
    ListShuns,
    ShowShun(Ipv4Addr),
    RemoveShun { target: Ipv4Addr, interface: String },
}

impl SshSession {
    async fn connect(device: &Device, username: &str, password: &str) -> Result<Self> {
        let configuration = client::Config {
            inactivity_timeout: Some(Duration::from_secs(15)),
            ..Default::default()
        };
        let mut handle = timeout(
            FTD_INTERACTION_TIMEOUT,
            client::connect(
                Arc::new(configuration),
                (device.management_ip.to_string(), 22),
                HostKeyVerifier {
                    pinned: device.pinned_host_key.clone(),
                },
            ),
        )
        .await
        .context("SSH connection or host-key verification timed out")?
        .context("SSH connection or host-key verification failed")?;

        let authenticated = timeout(
            FTD_INTERACTION_TIMEOUT,
            handle.authenticate_password(username, password),
        )
        .await
        .context("SSH password authentication timed out")?
        .context("SSH password authentication failed")?;
        if !authenticated.success() {
            bail!("SSH password authentication was rejected");
        }

        let mut channel = handle
            .channel_open_session()
            .await
            .context("could not open FTD SSH session channel")?;
        timeout(
            FTD_INTERACTION_TIMEOUT,
            channel.request_pty(true, "xterm", 80, 24, 0, 0, &[]),
        )
        .await
        .context("FTD pseudo-terminal request timed out")?
        .context("FTD rejected the SSH pseudo-terminal request")?;
        timeout(FTD_INTERACTION_TIMEOUT, channel.request_shell(true))
            .await
            .context("FTD interactive SSH shell request timed out")?
            .context("FTD rejected the interactive SSH shell request")?;
        timeout(FTD_INTERACTION_TIMEOUT, read_until_ftd_prompt(&mut channel))
            .await
            .context("FTD initial shell prompt timed out")??;

        Ok(Self { handle, channel })
    }

    async fn show_shun(&mut self, target: Ipv4Addr) -> Result<String> {
        self.run(CiscoOperation::ShowShun(target)).await
    }

    async fn list_shuns(
        &mut self,
        allowed_interfaces: &BTreeSet<String>,
    ) -> Result<BTreeSet<ObservedShun>> {
        let output = self.run(CiscoOperation::ListShuns).await?;
        parse_show_shun_entries(&output, allowed_interfaces)
    }

    async fn remove_shun(&mut self, target: Ipv4Addr, interface: &str) -> Result<()> {
        if !is_safe_interface(interface) {
            bail!("attempted to use an unsafe interface name");
        }
        let output = self
            .run(CiscoOperation::RemoveShun {
                target,
                interface: interface.to_owned(),
            })
            .await?;
        if !output.trim().is_empty() {
            bail!("FTD removal returned unexpected output");
        }
        Ok(())
    }

    async fn run(&mut self, operation: CiscoOperation) -> Result<String> {
        let command = match operation {
            CiscoOperation::ListShuns => "show shun".to_owned(),
            CiscoOperation::ShowShun(target) => format!("{SHOW_SHUN_PREFIX}{target}"),
            CiscoOperation::RemoveShun { target, interface } => {
                format!("{REMOVE_SHUN_PREFIX}{target} interface {interface}")
            }
        };
        self.channel
            .data_bytes(format!("{command}\n"))
            .await
            .context("could not send fixed Cisco command to FTD shell")?;
        let output = timeout(
            FTD_INTERACTION_TIMEOUT,
            read_until_ftd_prompt(&mut self.channel),
        )
        .await
        .context("FTD command prompt timed out")??;
        parse_shell_command_output(&output, &command)
    }

    async fn close(self) {
        let _ = self.channel.data_bytes(b"exit\n".as_slice()).await;
        let _ = self
            .handle
            .disconnect(Disconnect::ByApplication, "", "en")
            .await;
    }
}

async fn read_until_ftd_prompt(channel: &mut Channel<client::Msg>) -> Result<Vec<u8>> {
    let mut output = Vec::new();
    while let Some(message) = channel.wait().await {
        match message {
            ChannelMsg::Data { data } => {
                if output.len().saturating_add(data.len()) > MAX_CISCO_OUTPUT_BYTES {
                    bail!("FTD shell response exceeded the maximum size");
                }
                output.extend_from_slice(&data);
                if output.ends_with(FTD_PROMPT) || output.ends_with(b">") {
                    return Ok(output);
                }
            }
            ChannelMsg::ExitStatus { .. } | ChannelMsg::Eof | ChannelMsg::Close => {
                bail!("FTD shell closed before returning its prompt")
            }
            _ => {}
        }
    }
    bail!("FTD shell closed before returning its prompt")
}

fn parse_shell_command_output(raw: &[u8], command: &str) -> Result<String> {
    let normalized = String::from_utf8(raw.to_vec())
        .context("FTD shell output was not UTF-8")?
        .replace("\r\n", "\n")
        .replace('\r', "\n");
    let mut lines: Vec<&str> = normalized.lines().collect();

    while lines.first().is_some_and(|line| line.trim().is_empty()) {
        lines.remove(0);
    }
    if lines.first().is_some_and(|line| line.trim() == command) {
        lines.remove(0);
    }
    while lines.last().is_some_and(|line| line.trim().is_empty()) {
        lines.pop();
    }
    let prompt = lines
        .pop()
        .context("FTD shell response omitted its prompt")?;
    if prompt.trim() != ">" {
        bail!("FTD shell returned an unexpected prompt");
    }
    Ok(lines.join("\n"))
}

fn load_ssh_password(path: &Path) -> Result<Zeroizing<String>> {
    let password = Zeroizing::new(
        fs::read_to_string(path)
            .with_context(|| format!("could not read SSH password secret {}", path.display()))?,
    );
    if password.is_empty() {
        bail!("SSH password secret must not be empty");
    }
    Ok(password)
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
    let entries = parse_show_shun_entries(output, allowed_interfaces)?;
    let mut interfaces = BTreeSet::new();
    for entry in entries {
        if entry.target != target {
            bail!("FTD show shun returned an unexpected target address");
        }
        interfaces.insert(entry.interface);
    }
    Ok(interfaces)
}

fn parse_show_shun_entries(
    output: &str,
    allowed_interfaces: &BTreeSet<String>,
) -> Result<BTreeSet<ObservedShun>> {
    let mut entries = BTreeSet::new();
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
        let fields: Vec<&str> = fields.split_ascii_whitespace().collect();
        if fields.len() != 5 {
            bail!("FTD shun entry did not match the validated field layout");
        }
        let target = fields[0]
            .parse::<Ipv4Addr>()
            .context("FTD shun entry contained an invalid IPv4 address")?;
        fields[1]
            .parse::<Ipv4Addr>()
            .context("FTD shun entry contained an invalid IPv4 mask")?;
        for field in &fields[2..] {
            field
                .parse::<u16>()
                .context("FTD shun entry contained an invalid numeric field")?;
        }
        if !entries.insert(ObservedShun {
            target,
            interface: interface.to_owned(),
        }) {
            bail!("FTD show shun output contained a duplicate entry");
        }
    }
    Ok(entries)
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
        if cycle::set_ipc_timeout(&connection, Duration::from_secs(10)).is_err() {
            continue;
        }
        let response = match getsockopt(&connection, PeerCredentials) {
            Ok(credentials) if credentials.uid() == peer_uid => {
                handle_connection(&agent, &connection, &runtime)
            }
            Ok(_) => RESPONSE_REJECTED.to_vec(),
            Err(_) => RESPONSE_REJECTED.to_vec(),
        };
        let _ = send(connection.as_raw_fd(), &response, MsgFlags::MSG_NOSIGNAL);
    }
}

fn accept_connection(listener: std::os::fd::RawFd) -> Result<OwnedFd> {
    let raw_fd = accept4(listener, SockFlag::SOCK_CLOEXEC)?;
    // `accept4` transfers a newly allocated descriptor to this process. Converting
    // it immediately gives Rust ownership, so it is closed on every path below.
    Ok(unsafe { OwnedFd::from_raw_fd(raw_fd) })
}

fn handle_connection(agent: &Agent, connection: &OwnedFd, runtime: &Handle) -> Vec<u8> {
    let mut packet = [0u8; MAX_REQUEST_BYTES];
    let received = match recv(connection.as_raw_fd(), &mut packet, MsgFlags::MSG_TRUNC) {
        Ok(received) if received <= packet.len() => received,
        Ok(_) => return RESPONSE_REJECTED.to_vec(),
        Err(_) => return RESPONSE_REJECTED.to_vec(),
    };
    if packet.first() == Some(&0x10) {
        return match cycle::handle(agent, connection, runtime, &packet[..received]) {
            Ok(response) => response,
            Err(error) => {
                eprintln!(
                    "{}",
                    serde_json::json!({"event":"agent.cycle.rejected", "reason":error.to_string()})
                );
                RESPONSE_REJECTED.to_vec()
            }
        };
    }
    let (operation, device_id, ip) = match decode_request(&packet[..received]) {
        Ok(request) => request,
        Err(_) => return RESPONSE_REJECTED.to_vec(),
    };
    match operation {
        Operation::Health
            if agent
                .devices
                .get(&device_id)
                .is_some_and(|device| device.enabled) =>
        {
            RESPONSE_OK.to_vec()
        }
        Operation::ListShuns => match runtime.block_on(timeout(
            agent.operation_timeout,
            agent.list_shuns(device_id),
        )) {
            Ok(Ok(entries)) => match encode_list_shuns_response(entries) {
                Ok(response) => response,
                Err(error) => {
                    log_list_failure(device_id, error.to_string());
                    RESPONSE_REJECTED.to_vec()
                }
            },
            Ok(Err(error)) => {
                log_list_failure(device_id, error.to_string());
                RESPONSE_REJECTED.to_vec()
            }
            Err(_) => {
                log_list_failure(
                    device_id,
                    "operation timed out before a complete snapshot was available".to_owned(),
                );
                RESPONSE_REJECTED.to_vec()
            }
        },
        Operation::RemoveShun => {
            let Some(ip) = ip else {
                return RESPONSE_REJECTED.to_vec();
            };
            match runtime.block_on(timeout(
                agent.operation_timeout,
                agent.remove_shun(device_id, ip),
            )) {
                Ok(Ok(())) => RESPONSE_OK.to_vec(),
                Ok(Err(error)) => {
                    log_remove_failure(device_id, ip, error.to_string());
                    RESPONSE_REJECTED.to_vec()
                }
                Err(_) => {
                    log_remove_failure(
                        device_id,
                        ip,
                        "operation timed out before verified completion".to_owned(),
                    );
                    RESPONSE_REJECTED.to_vec()
                }
            }
        }
        Operation::Health
        | Operation::GetShun
        | Operation::GetRaAuthStatus
        | Operation::GetRaInitStatus => RESPONSE_REJECTED.to_vec(),
    }
}

fn log_remove_failure(device_id: u16, target: Ipv4Addr, reason: String) {
    // The fixed socket protocol deliberately returns only success or rejection. Keep
    // diagnostics local, structured, and free of credentials or raw Cisco output.
    eprintln!(
        "{}",
        serde_json::json!({
            "event": "agent.remove_shun.failed",
            "device_id": device_id,
            "target_ip": target.to_string(),
            "reason": reason,
        })
    );
}

fn log_list_failure(device_id: u16, reason: String) {
    eprintln!(
        "{}",
        serde_json::json!({
            "event": "agent.list_shuns.failed",
            "device_id": device_id,
            "reason": reason,
        })
    );
}

fn encode_list_shuns_response(entries: BTreeSet<ObservedShun>) -> Result<Vec<u8>> {
    let count = u16::try_from(entries.len()).context("FTD shun snapshot has too many entries")?;
    let mut response = Vec::with_capacity(3 + entries.len() * 16);
    response.push(RESPONSE_OK[0]);
    response.extend_from_slice(&count.to_be_bytes());
    for entry in entries {
        let interface = entry.interface.as_bytes();
        let interface_length =
            u8::try_from(interface.len()).context("FTD interface name is too long")?;
        if response.len().saturating_add(5 + interface.len()) > MAX_AGENT_RESPONSE_BYTES {
            bail!("FTD shun snapshot exceeds the maximum response size");
        }
        response.extend_from_slice(&entry.target.octets());
        response.push(interface_length);
        response.extend_from_slice(interface);
    }
    Ok(response)
}

fn remove_existing_socket(path: &Path) -> Result<()> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_socket() => fs::remove_file(path)
            .with_context(|| format!("could not remove stale socket {}", path.display())),
        Ok(_) => bail!("refusing to replace non-socket path {}", path.display()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => {
            Err(error).with_context(|| format!("could not inspect socket {}", path.display()))
        }
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
        Ok(value) => value
            .parse()
            .with_context(|| format!("{name} must be an integer")),
        Err(env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(error).with_context(|| format!("could not read {name}")),
    }
}

fn env_u64(name: &str, default: u64) -> Result<u64> {
    match env::var(name) {
        Ok(value) => value
            .parse()
            .with_context(|| format!("{name} must be an integer")),
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
            (
                Operation::RemoveShun,
                7,
                Some(Ipv4Addr::new(203, 0, 113, 17))
            )
        );
    }

    #[test]
    fn malformed_requests_are_rejected() {
        for packet in [
            vec![],
            vec![3, 0, 7],
            vec![3, 0, 0, 203, 0, 113, 17],
            vec![255, 0, 1],
        ] {
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
    fn parser_accepts_recorded_fpr1010_766_management_output() {
        let output = "shun (management) 198.51.100.250 0.0.0.0 0 0 0\n";
        let allowed_interfaces = BTreeSet::from(["management".to_owned()]);

        assert_eq!(
            parse_show_shun(
                output,
                Ipv4Addr::new(198, 51, 100, 250),
                &allowed_interfaces,
            )
            .unwrap(),
            allowed_interfaces
        );
    }

    #[test]
    fn list_parser_accepts_a_complete_multi_entry_snapshot() {
        let output = concat!(
            "shun (outside) 203.0.113.17 0.0.0.0 0 0 0\n",
            "shun (inside) 198.51.100.250 0.0.0.0 0 0 0\n"
        );
        assert_eq!(
            parse_show_shun_entries(output, &interfaces()).unwrap(),
            BTreeSet::from([
                ObservedShun {
                    target: Ipv4Addr::new(198, 51, 100, 250),
                    interface: "inside".to_owned(),
                },
                ObservedShun {
                    target: Ipv4Addr::new(203, 0, 113, 17),
                    interface: "outside".to_owned(),
                },
            ])
        );
    }

    #[test]
    fn parser_fails_closed_on_unknown_interface_or_unexpected_text() {
        let target = Ipv4Addr::new(203, 0, 113, 17);
        assert!(parse_show_shun("shun (dmz) 203.0.113.17\n", target, &interfaces()).is_err());
        assert!(parse_show_shun("ERROR: invalid input\n", target, &interfaces()).is_err());
        assert!(
            parse_show_shun(
                "shun (outside) 203.0.113.17 0.0.0.0 0 0 0 unexpected\n",
                target,
                &interfaces(),
            )
            .is_err()
        );
    }

    #[test]
    fn list_response_has_only_typed_snapshot_fields() {
        let entries = BTreeSet::from([ObservedShun {
            target: Ipv4Addr::new(198, 51, 100, 250),
            interface: "management".to_owned(),
        }]);
        assert_eq!(
            encode_list_shuns_response(entries).unwrap(),
            b"\x00\x00\x01\xc6\x33\x64\xfa\x0a\x6d\x61\x6e\x61\x67\x65\x6d\x65\x6e\x74"
        );
    }

    #[test]
    fn shell_output_strips_command_echo_and_prompt() {
        let command = "show shun 198.51.100.250";
        let raw =
            b"show shun 198.51.100.250\r\nshun (management) 198.51.100.250 0.0.0.0 0 0 0\r\n> ";

        assert_eq!(
            parse_shell_command_output(raw, command).unwrap(),
            "shun (management) 198.51.100.250 0.0.0.0 0 0 0"
        );
    }

    #[test]
    fn shell_output_accepts_an_empty_successful_command_response() {
        assert_eq!(
            parse_shell_command_output(
                b"no shun 198.51.100.250 interface management\r\n\r\n> ",
                "no shun 198.51.100.250 interface management",
            )
            .unwrap(),
            ""
        );
    }

    #[test]
    fn shell_output_rejects_an_unexpected_prompt() {
        assert!(parse_shell_command_output(b"show shun\r\n# ", "show shun").is_err());
    }
}
