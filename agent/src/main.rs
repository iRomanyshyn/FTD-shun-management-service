//! Privileged, deliberately narrow FTD SSH agent.
//!
//! This binary accepts fixed AF_UNIX/SOCK_SEQPACKET requests only. Cisco CLI
//! strings are source-code constants; neither a command nor an interface name
//! can cross the Web/API-to-agent boundary.

mod addition;
mod batch_addition;
mod cli_timing;
mod credentials;
mod cycle;
mod dispatch;
mod sessions;
mod shutdown;
mod snapshot;
#[cfg(test)]
mod ssh_idle_tests;

// Offline executable specification only; never linked into the shipped agent.
#[cfg(test)]
mod addition_contract;

use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::net::Ipv4Addr;
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
use std::os::unix::fs::{FileTypeExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{Context, Result, bail};
#[cfg(test)]
use dispatch::Completion;
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
const MAX_REQUEST_BYTES: usize = 20;
const MAX_AGENT_RESPONSE_BYTES: usize = 64 * 1024;
const MAX_CISCO_OUTPUT_BYTES: usize = 64 * 1024;
const FTD_INTERACTION_TIMEOUT: Duration = Duration::from_secs(15);
const SHOW_SHUN_PREFIX: &str = "show shun ";
const REMOVE_SHUN_PREFIX: &str = "no shun ";
const FTD_PROMPT: &[u8] = b"> ";

#[derive(Clone)]
struct Agent {
    sessions: Arc<sessions::Sessions>,
    devices: BTreeMap<u16, Device>,
    credentials: credentials::Credentials,
    operation_timeout: Duration,
    cycles_enabled: bool,
    large_snapshots_enabled: bool,
    additions_enabled: bool,
    batch_additions_enabled: bool,
    batch_session_version: u8,
    max_concurrent_devices: usize,
}

#[derive(Clone)]
struct Device {
    management_ip: Ipv4Addr,
    pinned_host_key: PublicKey,
    allowed_interfaces: BTreeSet<String>,
    enabled: bool,
    addition_profile: Option<addition::Profile>,
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
    #[serde(default)]
    addition_profile: Option<addition::Profile>,
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
        let mut hostnames = BTreeSet::new();
        for entry in inventory {
            if entry.id == 0 {
                bail!("inventory device ID must be nonzero");
            }
            if entry.hostname.trim().is_empty() || entry.hostname.len() > 255 {
                bail!("inventory has an invalid hostname for device {}", entry.id);
            }
            if !hostnames.insert(entry.hostname.clone()) {
                bail!("inventory has duplicate hostnames");
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
                        addition_profile: entry.addition_profile,
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
        let max_concurrent_devices = match env::var("FTD_SHUN_AGENT_MAX_CONCURRENT_DEVICES") {
            Ok(value) => dispatch::worker_count(Some(&value))?,
            Err(env::VarError::NotPresent) => dispatch::worker_count(None)?,
            Err(_) => bail!("could not read agent concurrency"),
        };
        let operation_timeout = Duration::from_secs(env_u64("FTD_SHUN_AGENT_TIMEOUT_SECONDS", 45)?);
        if !(5..=120).contains(&operation_timeout.as_secs()) {
            bail!("FTD_SHUN_AGENT_TIMEOUT_SECONDS must be between 5 and 120");
        }
        let cycles_enabled = match env::var("FTD_SHUN_AGENT_CYCLES_ENABLED").as_deref() {
            Ok("true") => true,
            Ok("false") | Err(env::VarError::NotPresent) => false,
            _ => bail!("FTD_SHUN_AGENT_CYCLES_ENABLED must be true or false"),
        };
        let large_snapshots_enabled = match env::var("FTD_SHUN_LARGE_SNAPSHOTS_ENABLED").as_deref()
        {
            Ok("true") => true,
            Ok("false") | Err(env::VarError::NotPresent) => false,
            _ => bail!("FTD_SHUN_LARGE_SNAPSHOTS_ENABLED must be true or false"),
        };

        let additions_enabled = match env::var("FTD_SHUN_AGENT_ADDITIONS_ENABLED").as_deref() {
            Ok("true") => true,
            Ok("false") | Err(env::VarError::NotPresent) => false,
            _ => bail!("FTD_SHUN_AGENT_ADDITIONS_ENABLED must be true or false"),
        };
        if additions_enabled && (!cycles_enabled || !large_snapshots_enabled) {
            bail!("additions require both session cycles and large snapshots");
        }
        let batch_additions_enabled =
            match env::var("FTD_SHUN_AGENT_BATCH_ADDITIONS_ENABLED").as_deref() {
                Ok("true") => true,
                Ok("false") | Err(env::VarError::NotPresent) => false,
                _ => bail!("FTD_SHUN_AGENT_BATCH_ADDITIONS_ENABLED must be true or false"),
            };
        if batch_additions_enabled && !additions_enabled {
            bail!("batch additions require explicitly enabled additions");
        }
        let deferred_confirmation =
            match env::var("FTD_SHUN_DEFERRED_CONFIRMATION_ENABLED").as_deref() {
                Ok("true") => true,
                Ok("false") | Err(env::VarError::NotPresent) => false,
                _ => bail!("FTD_SHUN_DEFERRED_CONFIRMATION_ENABLED must be true or false"),
            };
        let batch_session_version =
            match env::var("FTD_SHUN_AGENT_BATCH_SESSION_VERSION").as_deref() {
                Ok("5") | Err(env::VarError::NotPresent) => 5,
                Ok("6") if batch_additions_enabled => 6,
                Ok("7") if deferred_confirmation && batch_additions_enabled => 7,
                _ => bail!(
                    "batch session version requires 5, grouped 6, or explicitly enabled deferred 7"
                ),
            };
        if deferred_confirmation && batch_session_version != 7 {
            bail!("deferred confirmation requires explicit grouped session version 7");
        }
        for device in devices.values() {
            if let Some(profile) = device.addition_profile {
                profile.validate(&device.allowed_interfaces)?;
            }
        }

        Ok((
            Self {
                sessions: Arc::new(sessions::Sessions::default()),
                credentials: credentials::Credentials::from_environment(
                    &devices.keys().copied().collect(),
                )?,
                devices,
                operation_timeout,
                cycles_enabled,
                large_snapshots_enabled,
                additions_enabled,
                batch_additions_enabled,
                batch_session_version,
                max_concurrent_devices,
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
        let mut session = self.connect_device(device_id).await?;

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

    async fn list_shuns(&self, device_id: u16, large: bool) -> Result<BTreeSet<ObservedShun>> {
        let device = self
            .devices
            .get(&device_id)
            .filter(|device| device.enabled)
            .context("unknown or disabled device")?;
        let mut session = self.connect_device(device_id).await?;
        session.large_snapshots = large;
        let entries = session.list_shuns(&device.allowed_interfaces).await?;
        session.close().await;
        Ok(entries)
    }

    async fn connect_device(&self, device_id: u16) -> Result<SshSession> {
        self.connect_device_with_idle(device_id, Duration::from_secs(15))
            .await
    }

    async fn connect_device_with_idle(
        &self,
        device_id: u16,
        inactivity_timeout: Duration,
    ) -> Result<SshSession> {
        let device = self
            .devices
            .get(&device_id)
            .filter(|device| device.enabled)
            .context("unknown or disabled device")?;
        let credential = self.credentials.for_device(device_id)?;
        let password = load_ssh_password(&credential.password_file)?;
        SshSession::connect(
            device,
            &credential.username,
            password.as_str(),
            inactivity_timeout,
        )
        .await
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
    large_snapshots: bool,
    timing: cli_timing::CliTiming,
}

enum CiscoOperation {
    ListShuns,
    ShowShun(Ipv4Addr),
    RemoveShun { target: Ipv4Addr, interface: String },
    AddShun(Ipv4Addr),
}

impl CiscoOperation {
    fn timing_phase(&self) -> cli_timing::Phase {
        match self {
            Self::ListShuns => cli_timing::Phase::FullRead,
            Self::ShowShun(_) => cli_timing::Phase::TargetRead,
            Self::AddShun(_) => cli_timing::Phase::Add,
            Self::RemoveShun { .. } => cli_timing::Phase::Remove,
        }
    }
}

impl SshSession {
    fn configuration(inactivity_timeout: Duration) -> client::Config {
        client::Config {
            inactivity_timeout: Some(inactivity_timeout),
            ..Default::default()
        }
    }

    async fn connect(
        device: &Device,
        username: &str,
        password: &str,
        inactivity_timeout: Duration,
    ) -> Result<Self> {
        let configuration = Self::configuration(inactivity_timeout);
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

        Ok(Self {
            handle,
            channel,
            large_snapshots: false,
            timing: cli_timing::CliTiming::default(),
        })
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
        let phase = operation.timing_phase();
        let output_limit = if self.large_snapshots && matches!(operation, CiscoOperation::ListShuns)
        {
            snapshot::MAX_OUTPUT_BYTES
        } else {
            MAX_CISCO_OUTPUT_BYTES
        };
        let command = match operation {
            CiscoOperation::ListShuns => "show shun".to_owned(),
            CiscoOperation::ShowShun(target) => format!("{SHOW_SHUN_PREFIX}{target}"),
            CiscoOperation::AddShun(target) => format!("shun {target}"),
            CiscoOperation::RemoveShun { target, interface } => {
                format!("{REMOVE_SHUN_PREFIX}{target} interface {interface}")
            }
        };
        self.timing
            .measure(phase, async {
                self.channel
                    .data_bytes(format!("{command}\n"))
                    .await
                    .context("could not send fixed Cisco command to FTD shell")?;
                let output = timeout(
                    FTD_INTERACTION_TIMEOUT,
                    read_until_ftd_prompt_bounded(&mut self.channel, output_limit),
                )
                .await
                .context("FTD command prompt timed out")??;
                parse_shell_command_output(&output, &command)
            })
            .await
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
    read_until_ftd_prompt_bounded(channel, MAX_CISCO_OUTPUT_BYTES).await
}

fn append_ftd_output(output: &mut Vec<u8>, data: &[u8], limit: usize) -> Result<()> {
    if output.len().saturating_add(data.len()) > limit {
        bail!("FTD shell response exceeded the maximum size");
    }
    output.extend_from_slice(data);
    Ok(())
}

async fn read_until_ftd_prompt_bounded(
    channel: &mut Channel<client::Msg>,
    limit: usize,
) -> Result<Vec<u8>> {
    let mut output = Vec::new();
    while let Some(message) = channel.wait().await {
        match message {
            ChannelMsg::Data { data } => {
                append_ftd_output(&mut output, &data, limit)?;
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
    use std::io::Read;
    use std::os::unix::fs::OpenOptionsExt;
    const MAX_PASSWORD_BYTES: u64 = 16 * 1024;
    // Operator-provisioned regular files only; never block on a FIFO or follow
    // a secret basename symlink out of its mount. Preserve password bytes exactly.
    let file = fs::OpenOptions::new()
        .read(true)
        .custom_flags(nix::libc::O_NOFOLLOW | nix::libc::O_NONBLOCK)
        .open(path)
        .context("could not open SSH password secret")?;
    if !file
        .metadata()
        .context("could not inspect SSH password secret")?
        .is_file()
    {
        bail!("SSH password secret must be a regular file");
    }
    let mut password = Zeroizing::new(String::new());
    file.take(MAX_PASSWORD_BYTES + 1)
        .read_to_string(&mut password)
        .context("could not read SSH password secret as UTF-8")?;
    if password.len() as u64 > MAX_PASSWORD_BYTES {
        bail!("SSH password secret exceeds 16 KiB");
    }
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
    ListShunsLarge = 0x07,
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
        0x07 => Operation::ListShunsLarge,
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
        if entries.len() > snapshot::MAX_ENTRIES {
            bail!("FTD shun snapshot has too many entries");
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

fn serve(
    agent: Agent,
    socket_file: PathBuf,
    peer_uid: u32,
    runtime: Handle,
    stop: shutdown::Shutdown,
) -> Result<()> {
    remove_existing_socket(&socket_file)?;
    let listener = socket(
        AddressFamily::Unix,
        SockType::SeqPacket,
        SockFlag::SOCK_CLOEXEC | SockFlag::SOCK_NONBLOCK,
        None,
    )?;
    bind(listener.as_raw_fd(), &UnixAddr::new(&socket_file)?)?;
    fs::set_permissions(&socket_file, fs::Permissions::from_mode(0o660))?;
    listen(&listener, Backlog::new(16)?)?;

    let guards = Arc::new(dispatch::DeviceGuards::new(
        agent
            .devices
            .iter()
            .map(|(id, device)| (*id, device.management_ip)),
    ));
    let agent = Arc::new(agent);
    let workers = {
        let count = agent.max_concurrent_devices;
        let agent = Arc::clone(&agent);
        let guards = Arc::clone(&guards);
        let runtime = runtime.clone();
        dispatch::Pool::new(count, move |(connection, accepted): (OwnedFd, Instant)| {
            let (settlement, tracked) =
                respond_for_worker(&agent, &connection, &runtime, &guards, accepted);
            ConnectionCompletion {
                connection,
                settlement,
                tracked: tracked.map(|key| (Arc::clone(&agent.sessions), key)),
            }
        })?
    };

    eprintln!("{{\"event\":\"agent.listener.ready\"}}");
    let result = (|| -> Result<()> {
        while stop.wait_readable(&listener)? {
            if agent.max_concurrent_devices == 1 && workers.all_busy() {
                // Preserve legacy serial handoffs: leave successors in the
                // bounded kernel backlog, not an application/SSH work queue.
                std::thread::sleep(Duration::from_millis(100));
                continue;
            }
            let connection = match accept_connection(listener.as_raw_fd()) {
                Ok(connection) => connection,
                Err(error)
                    if matches!(
                        error.downcast_ref::<nix::errno::Errno>(),
                        Some(nix::errno::Errno::EAGAIN | nix::errno::Errno::EINTR)
                    ) =>
                {
                    continue;
                }
                Err(error) => return Err(error),
            };
            if stop.requested() {
                break; // Accepted but not admitted: close, never invent a receipt.
            }
            let accepted = Instant::now();
            if cycle::set_ipc_timeout(&connection, Duration::from_secs(10)).is_err() {
                continue;
            }
            if !authorized_peer(&connection, peer_uid) {
                let _ = send(
                    connection.as_raw_fd(),
                    &RESPONSE_REJECTED,
                    MsgFlags::MSG_NOSIGNAL,
                );
                continue;
            }
            // This last stop observation is the admission boundary. Work already
            // admitted here is drained even if the signal arrives before submit.
            if stop.requested() {
                break;
            }
            if let Err(error) = workers.submit((connection, accepted)) {
                let connection = match error {
                    std::sync::mpsc::TrySendError::Full((connection, _)) => connection,
                    std::sync::mpsc::TrySendError::Disconnected(_) => {
                        bail!("all agent connection workers stopped")
                    }
                };
                eprintln!("{{\"event\":\"agent.dispatch.saturated\"}}");
                let _ = send(
                    connection.as_raw_fd(),
                    &RESPONSE_REJECTED,
                    MsgFlags::MSG_NOSIGNAL,
                );
            } else {
                eprintln!("{{\"event\":\"agent.dispatch.admitted\"}}");
            }
        }
        Ok(())
    })();
    drop(listener); // Refuse new connections before waiting for admitted RPCs.
    eprintln!("{{\"event\":\"agent.shutdown.draining\"}}");
    let drained = workers.drain();
    result.and(drained)?;
    eprintln!("{{\"event\":\"agent.shutdown.completed\"}}");
    Ok(())
}

fn authorized_peer(connection: &OwnedFd, peer_uid: u32) -> bool {
    getsockopt(connection, PeerCredentials).is_ok_and(|credentials| credentials.uid() == peer_uid)
}

#[derive(Debug, PartialEq)]
enum Reply {
    Packet(Vec<u8>),
    Settled([u8; 4]),
    Tracked(Option<[u8; 4]>, sessions::Key),
}

struct ConnectionCompletion {
    connection: OwnedFd,
    settlement: Option<[u8; 4]>,
    tracked: Option<(Arc<sessions::Sessions>, sessions::Key)>,
}

impl dispatch::Completion for ConnectionCompletion {
    fn complete(self) {
        if let Some((sessions, key)) = self.tracked
            && sessions.complete(key).is_err()
        {
            eprintln!("{{\"event\":\"agent.session.completion_unavailable\"}}");
        }
        if let Some(record) = self.settlement {
            // Handler/cleanup/guard have finished and the pool is already IDLE.
            // A slow/disconnected peer must never hold a free worker here.
            if send(
                self.connection.as_raw_fd(),
                &record,
                MsgFlags::MSG_NOSIGNAL | MsgFlags::MSG_DONTWAIT,
            ) != Ok(record.len())
            {
                eprintln!("{{\"event\":\"agent.cycle.settlement_failed\"}}");
            }
        }
        // OwnedFd closes here. There is no SSH/CLI action in this postamble.
    }
}

fn respond_for_worker(
    agent: &Agent,
    connection: &OwnedFd,
    runtime: &Handle,
    guards: &dispatch::DeviceGuards,
    accepted: Instant,
) -> (Option<[u8; 4]>, Option<sessions::Key>) {
    // Fixed std workers do not inherit spawn_blocking's Tokio context. Timer/SSH
    // futures are constructed below before Handle::block_on enters the runtime.
    let _runtime_context = runtime.enter();
    let remaining = Duration::from_secs(10).saturating_sub(accepted.elapsed());
    let response = if remaining.is_zero() || cycle::set_ipc_timeout(connection, remaining).is_err()
    {
        Reply::Packet(RESPONSE_REJECTED.to_vec())
    } else {
        handle_connection(agent, connection, runtime, guards)
    };
    match response {
        Reply::Settled(record) => (Some(record), None),
        Reply::Tracked(record, key) => {
            if record.is_none() {
                let _ = send(
                    connection.as_raw_fd(),
                    &RESPONSE_REJECTED,
                    MsgFlags::MSG_NOSIGNAL,
                );
            }
            (record, Some(key))
        }
        Reply::Packet(response) => {
            if !response.is_empty() {
                let _ = send(connection.as_raw_fd(), &response, MsgFlags::MSG_NOSIGNAL);
            }
            (None, None)
        }
    }
}

#[cfg(test)]
fn respond(
    agent: &Agent,
    connection: &OwnedFd,
    runtime: &Handle,
    guards: &dispatch::DeviceGuards,
    accepted: Instant,
) -> Option<[u8; 4]> {
    respond_for_worker(agent, connection, runtime, guards, accepted).0
}

fn accept_connection(listener: std::os::fd::RawFd) -> Result<OwnedFd> {
    let raw_fd = accept4(listener, SockFlag::SOCK_CLOEXEC)?;
    // `accept4` transfers a newly allocated descriptor to this process. Converting
    // it immediately gives Rust ownership, so it is closed on every path below.
    Ok(unsafe { OwnedFd::from_raw_fd(raw_fd) })
}

fn handle_connection(
    agent: &Agent,
    connection: &OwnedFd,
    runtime: &Handle,
    guards: &dispatch::DeviceGuards,
) -> Reply {
    let mut packet = [0u8; MAX_REQUEST_BYTES];
    let received = match recv(connection.as_raw_fd(), &mut packet, MsgFlags::MSG_TRUNC) {
        Ok(received) if received <= packet.len() => received,
        Ok(_) => return Reply::Packet(RESPONSE_REJECTED.to_vec()),
        Err(_) => return Reply::Packet(RESPONSE_REJECTED.to_vec()),
    };
    if matches!(packet[0], sessions::LOOKUP | sessions::LOOKUP_PENDING) {
        return sessions::decode(&packet[..received], packet[0])
            .and_then(|key| {
                if !agent
                    .devices
                    .get(&key.device)
                    .is_some_and(|device| device.enabled)
                {
                    bail!("unknown or disabled lookup device");
                }
                if packet[0] == sessions::LOOKUP_PENDING {
                    agent.sessions.lookup_pending(key)
                } else {
                    agent.sessions.lookup(key)
                }
            })
            .map(Reply::Packet)
            .unwrap_or_else(|_| Reply::Packet(RESPONSE_REJECTED.to_vec()));
    }
    let device_id = if matches!(
        packet.first().copied(),
        Some(0x10 | cycle::BEGIN_SETTLED | cycle::BEGIN_RECOVERABLE | sessions::BEGIN)
    ) {
        cycle::decode_begin(&packet[..received]).map(|(device, _)| device)
    } else {
        decode_request(&packet[..received]).map(|(_, device, _)| device)
    };
    let Ok(device_id) = device_id else {
        return Reply::Packet(RESPONSE_REJECTED.to_vec());
    };
    if !agent
        .devices
        .get(&device_id)
        .is_some_and(|device| device.enabled)
    {
        return Reply::Packet(RESPONSE_REJECTED.to_vec());
    }
    guards
        .run(device_id, || {
            handle_packet(agent, connection, runtime, &packet[..received])
        })
        .unwrap_or_else(|| {
            eprintln!(
                "{}",
                serde_json::json!({"event":"agent.device_busy", "device_id":device_id})
            );
            Reply::Packet(RESPONSE_REJECTED.to_vec())
        })
}

fn handle_packet(agent: &Agent, connection: &OwnedFd, runtime: &Handle, packet: &[u8]) -> Reply {
    if packet.first() == Some(&sessions::BEGIN) {
        let key = match sessions::decode(packet, sessions::BEGIN) {
            Ok(key) if agent.sessions.reserve(key).is_ok() => key,
            _ => return Reply::Packet(RESPONSE_REJECTED.to_vec()),
        };
        let record = match cycle::handle(agent, connection, runtime, packet) {
            Ok(record) => record,
            Err(error) => {
                eprintln!(
                    "{}",
                    serde_json::json!({"event":"agent.cycle.rejected","reason":error.to_string()})
                );
                None
            }
        };
        return Reply::Tracked(record, key);
    }
    if matches!(
        packet.first().copied(),
        Some(0x10 | cycle::BEGIN_SETTLED | cycle::BEGIN_RECOVERABLE)
    ) {
        return match cycle::handle(agent, connection, runtime, packet) {
            Ok(Some(record)) => Reply::Settled(record),
            Ok(None) => Reply::Packet(Vec::new()),
            Err(error) => {
                eprintln!(
                    "{}",
                    serde_json::json!({"event":"agent.cycle.rejected", "reason":error.to_string()})
                );
                Reply::Packet(RESPONSE_REJECTED.to_vec())
            }
        };
    }
    let (operation, device_id, ip) = match decode_request(packet) {
        Ok(request) => request,
        Err(_) => return Reply::Packet(RESPONSE_REJECTED.to_vec()),
    };
    let response = match operation {
        Operation::Health
            if agent
                .devices
                .get(&device_id)
                .is_some_and(|device| device.enabled) =>
        {
            RESPONSE_OK.to_vec()
        }
        Operation::ListShunsLarge => {
            if !agent.large_snapshots_enabled {
                return Reply::Packet(RESPONSE_REJECTED.to_vec());
            }
            let deadline = std::time::Instant::now() + agent.operation_timeout;
            let result = runtime
                .block_on(timeout(
                    agent.operation_timeout,
                    agent.list_shuns(device_id, true),
                ))
                .context("large snapshot operation timed out")
                .and_then(|result| result)
                .and_then(|entries| snapshot::encode(entries, 7, 0))
                .and_then(|frames| snapshot::send_frames(connection, &frames, deadline));
            match result {
                Ok(()) => Vec::new(),
                Err(error) => {
                    log_list_failure(device_id, error.to_string());
                    RESPONSE_REJECTED.to_vec()
                }
            }
        }
        Operation::ListShuns => match runtime.block_on(timeout(
            agent.operation_timeout,
            agent.list_shuns(device_id, false),
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
                return Reply::Packet(RESPONSE_REJECTED.to_vec());
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
    };
    Reply::Packet(response)
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
    let args: Vec<_> = env::args_os().skip(1).collect();
    let check_only = match args.as_slice() {
        [] => false,
        [arg] if arg == "--check-config" => true,
        _ => bail!("usage: ftd-shun-agent [--check-config]"),
    };
    let (agent, socket_file, peer_uid) = Agent::from_environment()?;
    if check_only {
        for device_id in agent.devices.keys() {
            let credential = agent.credentials.for_device(*device_id)?;
            let _password = load_ssh_password(&credential.password_file)?;
        }
        println!(
            "{}",
            serde_json::json!({
                "event": "agent.configuration.checked", "devices": agent.devices.len(),
                "credential_mode": agent.credentials.mode(),
                "max_concurrent_devices": agent.max_concurrent_devices,
                "batch_session_version": agent.batch_session_version,
                "deferred_confirmation_enabled": agent.batch_session_version == 7,
            })
        );
        return Ok(());
    }
    use tokio::signal::unix::{SignalKind, signal};
    let mut terminate =
        signal(SignalKind::terminate()).context("could not install SIGTERM handler")?;
    let mut interrupt =
        signal(SignalKind::interrupt()).context("could not install SIGINT handler")?;
    let runtime = Handle::current();
    let stop = shutdown::Shutdown::default();
    let serving_stop = stop.clone();
    let mut serving = tokio::task::spawn_blocking(move || {
        serve(agent, socket_file, peer_uid, runtime, serving_stop)
    });
    let result = tokio::select! {
        result = &mut serving => result,
        _ = terminate.recv() => {
            stop.request();
            eprintln!("{{\"event\":\"agent.shutdown.requested\",\"signal\":\"SIGTERM\"}}");
            serving.await
        },
        _ = interrupt.recv() => {
            stop.request();
            eprintln!("{{\"event\":\"agent.shutdown.requested\",\"signal\":\"SIGINT\"}}");
            serving.await
        },
    };
    result.context("agent listener thread stopped unexpectedly")??;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn typed_cli_timing_is_argument_free_and_not_semantic_verification() -> Result<()> {
        let mut timing = cli_timing::CliTiming::default();
        let target = Ipv4Addr::new(198, 51, 100, 251);
        for operation in [
            CiscoOperation::ListShuns,
            CiscoOperation::ShowShun(target),
            CiscoOperation::RemoveShun {
                target,
                interface: "synthetic-interface".to_owned(),
            },
        ] {
            timing
                .measure(operation.timing_phase(), async { Ok(()) })
                .await?;
        }
        let output = timing
            .measure(CiscoOperation::AddShun(target).timing_phase(), async {
                Ok("unexpected CLI output")
            })
            .await?;
        assert!(
            addition::acknowledgement(output, target, addition::Profile::Fpr1010Management)
                .is_err()
        );
        let report = timing.report();
        for phase in ["full_read", "target_read", "add", "remove"] {
            assert_eq!(report[phase]["calls"], 1);
            assert_eq!(report[phase]["returned"], 1);
            assert_eq!(report[phase]["errors"], 0);
        }
        let serialized = report.to_string();
        assert!(!serialized.contains("198.51"));
        assert!(!serialized.contains("synthetic-interface"));
        assert!(!serialized.contains(output));
        Ok(())
    }

    fn synthetic_dispatch_agent() -> Result<Agent> {
        let key = PublicKey::from_openssh(
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        )?;
        Ok(Agent {
            sessions: Arc::new(sessions::Sessions::default()),
            devices: [1, 2, 3]
                .into_iter()
                .map(|id| {
                    (
                        id,
                        Device {
                            management_ip: Ipv4Addr::new(
                                192,
                                0,
                                2,
                                if id == 3 { 1 } else { id as u8 },
                            ),
                            pinned_host_key: key.clone(),
                            allowed_interfaces: BTreeSet::from(["management".into()]),
                            enabled: true,
                            addition_profile: None,
                        },
                    )
                })
                .collect(),
            credentials: credentials::Credentials::PerDevice(BTreeMap::new()),
            operation_timeout: Duration::from_secs(5),
            cycles_enabled: false,
            large_snapshots_enabled: false,
            additions_enabled: false,
            batch_additions_enabled: false,
            batch_session_version: 5,
            max_concurrent_devices: 2,
        })
    }

    #[test]
    fn opening_failure_receipt_waits_for_real_handler_guard_and_idle_slot() -> Result<()> {
        use nix::sys::socket::socketpair;
        let mut agent = synthetic_dispatch_agent()?;
        agent.cycles_enabled = true;
        agent.large_snapshots_enabled = true;
        agent.additions_enabled = true;
        agent
            .devices
            .get_mut(&1)
            .context("device")?
            .addition_profile = Some(addition::Profile::Fpr1010Management);
        // Empty credential mapping fails inside connect_device before any TCP/CLI.
        let guards = Arc::new(dispatch::DeviceGuards::new([(
            1,
            Ipv4Addr::new(192, 0, 2, 1),
        )]));
        let shared = Arc::clone(&guards);
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let handle = runtime.handle().clone();
        let pool = dispatch::Pool::new(1, move |connection: OwnedFd| {
            let settlement = respond(&agent, &connection, &handle, &shared, Instant::now());
            ConnectionCompletion {
                connection,
                settlement,
                tracked: None,
            }
        })?;
        for index in 0..30 {
            let version = 1 + index % 3;
            let (client, server) = socketpair(
                AddressFamily::Unix,
                SockType::SeqPacket,
                None,
                SockFlag::SOCK_CLOEXEC,
            )?;
            cycle::set_ipc_timeout(&client, Duration::from_secs(2))?;
            cycle::set_ipc_timeout(&server, Duration::from_secs(2))?;
            pool.submit(server)?; // No yield/retry after the preceding receipt.
            send(
                client.as_raw_fd(),
                &[cycle::BEGIN_RECOVERABLE, version, 0, 1],
                MsgFlags::MSG_NOSIGNAL,
            )?;
            let mut response = [0; 16];
            let length = recv(client.as_raw_fd(), &mut response, MsgFlags::MSG_TRUNC)?;
            assert_eq!(
                &response[..length],
                &[3, version, cycle::BEGIN_RECOVERABLE, 0]
            );
            assert_eq!(guards.run(1, || true), Some(true));
        }
        Ok(())
    }

    #[test]
    fn invalid_gated_busy_and_legacy_opening_never_get_recovery_proof() -> Result<()> {
        use nix::sys::socket::socketpair;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        for case in [
            "cycles", "large", "addition", "profile", "device", "shape", "busy", "legacy",
        ] {
            let mut agent = synthetic_dispatch_agent()?;
            agent.cycles_enabled = case != "cycles";
            agent.large_snapshots_enabled = case != "large";
            agent.additions_enabled = case != "addition";
            if case != "profile" {
                agent
                    .devices
                    .get_mut(&1)
                    .context("device")?
                    .addition_profile = Some(addition::Profile::Fpr1010Management);
            }
            let guards = dispatch::DeviceGuards::new([(1, Ipv4Addr::new(192, 0, 2, 1))]);
            let (client, server) = socketpair(
                AddressFamily::Unix,
                SockType::SeqPacket,
                None,
                SockFlag::SOCK_CLOEXEC,
            )?;
            let mut packet = vec![cycle::BEGIN_RECOVERABLE, 3, 0, 1];
            if case == "legacy" {
                packet[0] = cycle::BEGIN_SETTLED;
            }
            if case == "device" {
                packet[3] = 99;
            }
            if case == "shape" {
                packet.push(0);
            }
            send(client.as_raw_fd(), &packet, MsgFlags::MSG_NOSIGNAL)?;
            let run = || respond(&agent, &server, runtime.handle(), &guards, Instant::now());
            let record = if case == "busy" {
                guards.run(1, run).context("guard")?
            } else {
                run()
            };
            assert!(record.is_none(), "{case}");
            let mut response = [0; 16];
            let length = recv(client.as_raw_fd(), &mut response, MsgFlags::MSG_TRUNC)?;
            assert_eq!(&response[..length], RESPONSE_REJECTED, "{case}");
        }
        Ok(())
    }

    #[test]
    fn local_settlement_follows_cleanup_guard_release_and_worker_idle() -> Result<()> {
        use nix::errno::Errno;
        use nix::sys::socket::socketpair;
        use std::sync::{Mutex, mpsc};
        let guards = Arc::new(dispatch::DeviceGuards::new([(
            7,
            Ipv4Addr::new(192, 0, 2, 7),
        )]));
        let shared = Arc::clone(&guards);
        let (release, cleanup) = mpsc::channel();
        let cleanup = Mutex::new(cleanup);
        let pool = dispatch::Pool::new(1, move |(connection, hold): (OwnedFd, bool)| {
            let record = shared
                .run(7, || -> Result<[u8; 4]> {
                    let mut packet = [0; 8];
                    let size = recv(connection.as_raw_fd(), &mut packet, MsgFlags::MSG_TRUNC)?;
                    assert_eq!(cycle::decode_begin(&packet[..size])?, (7, 1));
                    assert_eq!(packet[0], cycle::BEGIN_SETTLED);
                    send(
                        connection.as_raw_fd(),
                        &[0, 1, cycle::BEGIN_SETTLED, 0, 0, 0, 0],
                        MsgFlags::MSG_NOSIGNAL,
                    )?;
                    let size = recv(connection.as_raw_fd(), &mut packet, MsgFlags::MSG_TRUNC)?;
                    assert_eq!(&packet[..size], &[0x13, 1, 1]);
                    send(
                        connection.as_raw_fd(),
                        &[0, 1, 0x13, 1, 0, 0, 0],
                        MsgFlags::MSG_NOSIGNAL,
                    )?;
                    if hold {
                        cleanup
                            .lock()
                            .map_err(|_| anyhow::anyhow!("synthetic lock"))?
                            .recv_timeout(Duration::from_secs(2))?;
                    }
                    Ok([0, 1, cycle::BEGIN_SETTLED, 1])
                })
                .and_then(Result::ok);
            ConnectionCompletion {
                connection,
                settlement: record,
                tracked: None,
            }
        })?;
        for index in 0..100 {
            let (client, server) = socketpair(
                AddressFamily::Unix,
                SockType::SeqPacket,
                None,
                SockFlag::SOCK_CLOEXEC,
            )?;
            cycle::set_ipc_timeout(&client, Duration::from_secs(2))?;
            cycle::set_ipc_timeout(&server, Duration::from_secs(2))?;
            // No retry/yield loop: a received receipt really precedes the next assignment.
            pool.submit((server, index == 0))?;
            send(
                client.as_raw_fd(),
                &[cycle::BEGIN_SETTLED, 1, 0, 7],
                MsgFlags::MSG_NOSIGNAL,
            )?;
            let mut packet = [0; 16];
            assert_eq!(
                recv(client.as_raw_fd(), &mut packet, MsgFlags::MSG_TRUNC)?,
                7
            );
            send(client.as_raw_fd(), &[0x13, 1, 1], MsgFlags::MSG_NOSIGNAL)?;
            assert_eq!(
                recv(client.as_raw_fd(), &mut packet, MsgFlags::MSG_TRUNC)?,
                7
            );
            if index == 0 {
                assert_eq!(guards.run(7, || true), None);
                assert_eq!(
                    recv(client.as_raw_fd(), &mut packet, MsgFlags::MSG_DONTWAIT),
                    Err(Errno::EAGAIN)
                );
                release.send(())?;
            }
            assert_eq!(
                recv(client.as_raw_fd(), &mut packet, MsgFlags::MSG_TRUNC)?,
                4
            );
            assert_eq!(&packet[..4], &[0, 1, cycle::BEGIN_SETTLED, 1]);
            assert_eq!(guards.run(7, || true), Some(true));
        }
        Ok(())
    }

    #[test]
    fn nonblocking_settlement_does_not_wait_for_a_closed_peer() -> Result<()> {
        use nix::sys::socket::socketpair;
        let (peer, connection) = socketpair(
            AddressFamily::Unix,
            SockType::SeqPacket,
            None,
            SockFlag::SOCK_CLOEXEC,
        )?;
        drop(peer);
        let started = Instant::now();
        ConnectionCompletion {
            connection,
            settlement: Some([0, 1, cycle::BEGIN_SETTLED, 1]),
            tracked: None,
        }
        .complete();
        assert!(started.elapsed() < Duration::from_secs(1));
        Ok(())
    }

    #[test]
    fn read_failure_terminal_waits_for_handler_guard_and_worker_idle() -> Result<()> {
        use nix::errno::Errno;
        use nix::sys::socket::socketpair;
        use std::sync::{Mutex, mpsc};
        let guards = Arc::new(dispatch::DeviceGuards::new([(
            7,
            Ipv4Addr::new(192, 0, 2, 7),
        )]));
        let shared = Arc::clone(&guards);
        let (entered, waiting) = mpsc::channel();
        let (release, cleanup) = mpsc::channel();
        let cleanup = Mutex::new(cleanup);
        let pool = dispatch::Pool::new(1, move |connection: OwnedFd| {
            let record = shared.run(7, || -> Result<Option<[u8; 4]>> {
                entered.send(())?;
                cleanup
                    .lock()
                    .map_err(|_| anyhow::anyhow!("cleanup lock"))?
                    .recv()?;
                cycle::finish_result(
                    cycle::BEGIN_RECOVERABLE,
                    3,
                    Err(anyhow::anyhow!("synthetic read failed")),
                    Ok(()),
                    Some((0x13, 1)),
                    0,
                )
            });
            assert!(matches!(&record, Some(Ok(Some(_)))));
            let record = record.and_then(Result::ok).flatten();
            ConnectionCompletion {
                connection,
                settlement: record,
                tracked: None,
            }
        })?;
        for _ in 0..30 {
            let (client, server) = socketpair(
                AddressFamily::Unix,
                SockType::SeqPacket,
                None,
                SockFlag::SOCK_CLOEXEC,
            )?;
            cycle::set_ipc_timeout(&client, Duration::from_secs(2))?;
            pool.submit(server)?;
            waiting.recv_timeout(Duration::from_secs(2))?;
            assert_eq!(guards.run(7, || true), None);
            let mut packet = [0; 16];
            assert_eq!(
                recv(client.as_raw_fd(), &mut packet, MsgFlags::MSG_DONTWAIT),
                Err(Errno::EAGAIN)
            );
            release.send(())?;
            assert_eq!(
                recv(client.as_raw_fd(), &mut packet, MsgFlags::MSG_TRUNC)?,
                4
            );
            assert_eq!(&packet[..4], &[4, 3, 0x13, 1]);
            assert_eq!(guards.run(7, || true), Some(true));
            // Receipt means the next assignment can follow without a sleep.
        }
        pool.drain()?;
        Ok(())
    }

    #[test]
    fn lost_bound_terminal_is_published_only_in_postamble_and_lookup_never_opens_ssh() -> Result<()>
    {
        use nix::sys::socket::socketpair;
        let mut agent = synthetic_dispatch_agent()?;
        agent.cycles_enabled = true;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let guards = dispatch::DeviceGuards::new([(1, Ipv4Addr::new(192, 0, 2, 1))]);
        let key = sessions::Key {
            device: 1,
            version: 1,
            id: [1; 16],
        };
        let mut packet = vec![sessions::BEGIN, 1, 0, 1];
        packet.extend(key.id);
        let (client, server) = socketpair(
            AddressFamily::Unix,
            SockType::SeqPacket,
            None,
            SockFlag::SOCK_CLOEXEC,
        )?;
        send(client.as_raw_fd(), &packet, MsgFlags::MSG_NOSIGNAL)?;
        // Synthetic credentials are unavailable: failure occurs before TCP/CLI.
        let (record, tracked) =
            respond_for_worker(&agent, &server, runtime.handle(), &guards, Instant::now());
        assert_eq!(record, Some([3, 1, sessions::BEGIN, 0]));
        assert_eq!(tracked, Some(key));
        assert_eq!(agent.sessions.lookup(key)?[0], 2);
        assert_eq!(guards.run(1, || true), Some(true));
        drop(client); // Force terminal delivery failure, not outcome fabrication.
        ConnectionCompletion {
            connection: server,
            settlement: record,
            tracked: Some((Arc::clone(&agent.sessions), key)),
        }
        .complete();
        assert_eq!(agent.sessions.lookup(key)?[0], 0);
        let (client, server) = socketpair(
            AddressFamily::Unix,
            SockType::SeqPacket,
            None,
            SockFlag::SOCK_CLOEXEC,
        )?;
        packet[0] = sessions::LOOKUP;
        send(client.as_raw_fd(), &packet, MsgFlags::MSG_NOSIGNAL)?;
        // A held FTD guard cannot block/turn lookup into another SSH session.
        let reply = guards
            .run(1, || {
                handle_connection(&agent, &server, runtime.handle(), &guards)
            })
            .context("guard")?;
        assert_eq!(reply, Reply::Packet(agent.sessions.lookup(key)?));
        packet[0] = sessions::BEGIN;
        send(client.as_raw_fd(), &packet, MsgFlags::MSG_NOSIGNAL)?;
        assert_eq!(
            handle_connection(&agent, &server, runtime.handle(), &guards),
            Reply::Packet(vec![1])
        );
        assert_eq!(agent.sessions.lookup(key)?[0], 0);
        Ok(())
    }

    #[test]
    fn pending_completion_lookup_is_distinct_and_never_enters_a_busy_device() -> Result<()> {
        use nix::sys::socket::socketpair;
        let agent = synthetic_dispatch_agent()?;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let guards = dispatch::DeviceGuards::new([(1, Ipv4Addr::new(192, 0, 2, 1))]);
        let key = sessions::Key {
            version: 7,
            device: 1,
            id: [7; 16],
        };
        agent.sessions.reserve(key)?;
        agent.sessions.prepare_pending(
            key,
            4,
            &[
                Ipv4Addr::new(198, 51, 100, 251),
                Ipv4Addr::new(198, 51, 100, 252),
            ],
        )?;
        assert_eq!(agent.sessions.lookup_pending(key)?[0], 2);
        let (peer, server) = socketpair(
            AddressFamily::Unix,
            SockType::SeqPacket,
            None,
            SockFlag::SOCK_CLOEXEC,
        )?;
        drop(peer); // Real terminal send failure cannot erase the completed journal.
        ConnectionCompletion {
            connection: server,
            settlement: Some([0, 7, sessions::BEGIN, 4]),
            tracked: Some((Arc::clone(&agent.sessions), key)),
        }
        .complete();
        assert_eq!(agent.sessions.lookup_pending(key)?[0], 0);
        assert_eq!(agent.sessions.lookup(key)?[0], 1);
        let (peer, server) = socketpair(
            AddressFamily::Unix,
            SockType::SeqPacket,
            None,
            SockFlag::SOCK_CLOEXEC,
        )?;
        let mut packet = vec![sessions::LOOKUP_PENDING, 7, 0, 1];
        packet.extend(key.id);
        send(peer.as_raw_fd(), &packet, MsgFlags::MSG_NOSIGNAL)?;
        let response = guards
            .run(1, || {
                handle_connection(&agent, &server, runtime.handle(), &guards)
            })
            .context("held guard")?;
        assert_eq!(response, Reply::Packet(agent.sessions.lookup_pending(key)?));
        for version in [1, 6, 8] {
            packet[1] = version;
            send(peer.as_raw_fd(), &packet, MsgFlags::MSG_NOSIGNAL)?;
            assert_eq!(
                handle_connection(&agent, &server, runtime.handle(), &guards),
                Reply::Packet(vec![1])
            );
        }
        Ok(())
    }

    #[test]
    fn real_seqpacket_dispatch_keeps_busy_and_alias_devices_out_of_ssh() -> Result<()> {
        use nix::sys::socket::socketpair;
        let agent = Arc::new(synthetic_dispatch_agent()?);
        let guards = Arc::new(dispatch::DeviceGuards::new(
            agent
                .devices
                .iter()
                .map(|(id, device)| (*id, device.management_ip)),
        ));
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let cloned_agent = Arc::clone(&agent);
        let cloned_guards = Arc::clone(&guards);
        let handle = runtime.handle().clone();
        let pool = dispatch::Pool::new(2, move |(connection, accepted): (OwnedFd, Instant)| {
            respond(
                &cloned_agent,
                &connection,
                &handle,
                &cloned_guards,
                accepted,
            );
        })?;
        // Health is local-only: empty credential mappings make SSH unavailable by design.
        for (opcode, device, expected) in [
            (6, 1u8, RESPONSE_REJECTED),
            (6, 2, RESPONSE_OK),
            (6, 3, RESPONSE_REJECTED),
            // Empty credentials fail before TCP; constructing the timeout still
            // requires the actual production worker's explicit Tokio context.
            (1, 2, RESPONSE_REJECTED),
            (6, 2, RESPONSE_OK),
        ] {
            let (sender, receiver) = socketpair(
                AddressFamily::Unix,
                SockType::SeqPacket,
                None,
                SockFlag::SOCK_CLOEXEC,
            )?;
            cycle::set_ipc_timeout(&sender, Duration::from_secs(2))?;
            let uid = getsockopt(&receiver, PeerCredentials)?.uid();
            assert!(authorized_peer(&receiver, uid));
            assert!(!authorized_peer(&receiver, u32::MAX));
            send(
                sender.as_raw_fd(),
                &[opcode, 0, device],
                MsgFlags::MSG_NOSIGNAL,
            )?;
            guards
                .run(1, || -> Result<()> {
                    // A free slot may finish its prior reply just after the peer receives it.
                    let deadline = Instant::now() + Duration::from_secs(2);
                    let mut item = (receiver, Instant::now());
                    loop {
                        match pool.submit(item) {
                            Ok(()) => break,
                            Err(std::sync::mpsc::TrySendError::Full(value))
                                if Instant::now() < deadline =>
                            {
                                item = value;
                                std::thread::yield_now();
                            }
                            Err(_) => bail!("synthetic dispatch unavailable"),
                        }
                    }
                    let mut response = [0; 8];
                    let length = recv(sender.as_raw_fd(), &mut response, MsgFlags::MSG_TRUNC)?;
                    assert_eq!(&response[..length], expected);
                    Ok(())
                })
                .context("synthetic device guard unavailable")??;
        }
        Ok(())
    }

    #[test]
    fn expired_assignment_rejects_without_reading_or_dispatching_packet() -> Result<()> {
        use nix::sys::socket::socketpair;
        let agent = synthetic_dispatch_agent()?;
        let guards = dispatch::DeviceGuards::new(
            agent
                .devices
                .iter()
                .map(|(id, device)| (*id, device.management_ip)),
        );
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let (sender, receiver) = socketpair(
            AddressFamily::Unix,
            SockType::SeqPacket,
            None,
            SockFlag::SOCK_CLOEXEC,
        )?;
        cycle::set_ipc_timeout(&sender, Duration::from_secs(2))?;
        send(sender.as_raw_fd(), &[6, 0, 2], MsgFlags::MSG_NOSIGNAL)?;
        respond(
            &agent,
            &receiver,
            runtime.handle(),
            &guards,
            Instant::now() - Duration::from_secs(11),
        );
        let mut response = [0; 8];
        let length = recv(sender.as_raw_fd(), &mut response, MsgFlags::MSG_TRUNC)?;
        assert_eq!(&response[..length], RESPONSE_REJECTED);
        let mut unread = [0; 8];
        assert_eq!(
            recv(receiver.as_raw_fd(), &mut unread, MsgFlags::MSG_TRUNC)?,
            3
        );
        assert_eq!(&unread[..3], &[6, 0, 2]);
        Ok(())
    }

    fn interfaces() -> BTreeSet<String> {
        ["inside", "outside"]
            .into_iter()
            .map(str::to_owned)
            .collect()
    }

    #[test]
    fn fixed_binary_remove_request_is_decoded() -> Result<()> {
        assert_eq!(
            decode_request(&[0x03, 0x00, 0x07, 203, 0, 113, 17])?,
            (
                Operation::RemoveShun,
                7,
                Some(Ipv4Addr::new(203, 0, 113, 17))
            )
        );
        Ok(())
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
    fn parser_accepts_only_allowed_interfaces_for_the_requested_ip() -> Result<()> {
        let output = "shun (outside) 203.0.113.17 10.0.0.1 123 443 6\nshun (inside) 203.0.113.17 10.0.0.2 456 443 6\n";
        assert_eq!(
            parse_show_shun(output, Ipv4Addr::new(203, 0, 113, 17), &interfaces())?,
            interfaces()
        );
        Ok(())
    }

    #[test]
    fn parser_accepts_recorded_fpr1010_766_management_output() -> Result<()> {
        let output = "shun (management) 198.51.100.250 0.0.0.0 0 0 0\n";
        let allowed_interfaces = BTreeSet::from(["management".to_owned()]);

        assert_eq!(
            parse_show_shun(
                output,
                Ipv4Addr::new(198, 51, 100, 250),
                &allowed_interfaces,
            )?,
            allowed_interfaces
        );
        Ok(())
    }

    #[test]
    fn list_parser_accepts_a_complete_multi_entry_snapshot() -> Result<()> {
        let output = concat!(
            "shun (outside) 203.0.113.17 0.0.0.0 0 0 0\n",
            "shun (inside) 198.51.100.250 0.0.0.0 0 0 0\n"
        );
        assert_eq!(
            parse_show_shun_entries(output, &interfaces())?,
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
        Ok(())
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
    fn list_response_has_only_typed_snapshot_fields() -> Result<()> {
        let entries = BTreeSet::from([ObservedShun {
            target: Ipv4Addr::new(198, 51, 100, 250),
            interface: "management".to_owned(),
        }]);
        assert_eq!(
            encode_list_shuns_response(entries)?,
            b"\x00\x00\x01\xc6\x33\x64\xfa\x0a\x6d\x61\x6e\x61\x67\x65\x6d\x65\x6e\x74"
        );
        Ok(())
    }

    #[test]
    fn shell_output_strips_command_echo_and_prompt() -> Result<()> {
        let command = "show shun 198.51.100.250";
        let raw =
            b"show shun 198.51.100.250\r\nshun (management) 198.51.100.250 0.0.0.0 0 0 0\r\n> ";

        assert_eq!(
            parse_shell_command_output(raw, command)?,
            "shun (management) 198.51.100.250 0.0.0.0 0 0 0"
        );
        Ok(())
    }

    #[test]
    fn shell_output_accepts_an_empty_successful_command_response() -> Result<()> {
        assert_eq!(
            parse_shell_command_output(
                b"no shun 198.51.100.250 interface management\r\n\r\n> ",
                "no shun 198.51.100.250 interface management",
            )?,
            ""
        );
        Ok(())
    }

    #[test]
    fn shell_output_rejects_an_unexpected_prompt() {
        assert!(parse_shell_command_output(b"show shun\r\n# ", "show shun").is_err());
    }
}
