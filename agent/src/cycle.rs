//! Versioned checkpoint protocol. No text/route/interface crosses this boundary.

use super::*;
use nix::sys::socket::setsockopt;
use nix::sys::socket::sockopt::{ReceiveTimeout, SendTimeout};
use nix::sys::time::TimeVal;
use std::time::Instant;

const VERSION: u8 = 1;
const BEGIN: u8 = 0x10;
const SNAPSHOT: u8 = 0x11;
const REMOVE: u8 = 0x12;
const END: u8 = 0x13;
const MAX_REMOVALS: u8 = 16;
const MAX_COMMANDS: usize = 64;
const MAX_DURATION: Duration = Duration::from_secs(120);
const IPC_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_STEP_DURATION: Duration = Duration::from_secs(45);

#[derive(Debug, PartialEq)]
enum Step {
    Snapshot,
    Remove(Ipv4Addr),
    End,
}

fn decode_begin(packet: &[u8]) -> Result<(u16, u8)> {
    if packet.len() != 4 || packet[0] != BEGIN || !matches!(packet[1], VERSION | snapshot::VERSION)
    {
        bail!("invalid cycle begin frame");
    }
    let device = u16::from_be_bytes([packet[2], packet[3]]);
    if device == 0 {
        bail!("invalid cycle device");
    }
    Ok((device, packet[1]))
}

fn decode_step(packet: &[u8], expected: u8, version: u8) -> Result<Step> {
    if packet.len() < 3 || packet[1] != version || packet[2] != expected {
        bail!("invalid cycle version or sequence");
    }
    match (packet[0], packet.len()) {
        (SNAPSHOT, 3) => Ok(Step::Snapshot),
        (END, 3) => Ok(Step::End),
        (REMOVE, 7) => Ok(Step::Remove(Ipv4Addr::new(
            packet[3], packet[4], packet[5], packet[6],
        ))),
        _ => bail!("invalid cycle opcode or length"),
    }
}

trait Console {
    async fn snapshot(&mut self, allowed: &BTreeSet<String>) -> Result<BTreeSet<ObservedShun>>;
    async fn target(
        &mut self,
        ip: Ipv4Addr,
        allowed: &BTreeSet<String>,
    ) -> Result<BTreeSet<String>>;
    async fn remove(&mut self, ip: Ipv4Addr, interface: &str) -> Result<()>;
}

impl Console for SshSession {
    async fn snapshot(&mut self, allowed: &BTreeSet<String>) -> Result<BTreeSet<ObservedShun>> {
        self.list_shuns(allowed).await
    }

    async fn target(
        &mut self,
        ip: Ipv4Addr,
        allowed: &BTreeSet<String>,
    ) -> Result<BTreeSet<String>> {
        parse_show_shun(&self.show_shun(ip).await?, ip, allowed)
    }

    async fn remove(&mut self, ip: Ipv4Addr, interface: &str) -> Result<()> {
        self.remove_shun(ip, interface).await
    }
}

struct Cycle<C> {
    console: C,
    allowed: BTreeSet<String>,
    started: Instant,
    timeout: Duration,
    commands: usize,
    removals: u8,
    priority_used: bool,
    sequence: u8,
    version: u8,
}

impl<C: Console> Cycle<C> {
    fn remaining(&self) -> Duration {
        MAX_DURATION.saturating_sub(self.started.elapsed())
    }

    async fn snapshot(&mut self, opcode: u8, sequence: u8) -> Result<Vec<Vec<u8>>> {
        if self.commands >= MAX_COMMANDS {
            bail!("cycle snapshot command budget exhausted");
        }
        self.commands += 1;
        let entries = self.console.snapshot(&self.allowed).await?;
        if self.version == snapshot::VERSION {
            return snapshot::encode(entries, opcode, sequence);
        }
        let mut response = vec![0, VERSION, opcode, sequence];
        response.extend(encode_list_shuns_response(entries)?);
        if response.len() > MAX_AGENT_RESPONSE_BYTES {
            bail!("cycle snapshot response exceeds maximum size");
        }
        Ok(vec![response])
    }

    async fn execute(&mut self, packet: &[u8]) -> Result<(Vec<Vec<u8>>, bool)> {
        let step = decode_step(packet, self.sequence, self.version)?;
        let seq = self.sequence;
        self.sequence += 1;
        match step {
            Step::Snapshot => {
                if self.priority_used {
                    bail!("cycle priority snapshot budget exhausted");
                }
                self.priority_used = true;
                if self.commands + 2 > MAX_COMMANDS
                    || self.remaining() < FTD_INTERACTION_TIMEOUT * 2
                {
                    return Ok((vec![vec![2, self.version, SNAPSHOT, seq]], false));
                }
                Ok((self.snapshot(SNAPSHOT, seq).await?, false))
            }
            Step::End => Ok((self.snapshot(END, seq).await?, true)),
            Step::Remove(ip) => {
                if self.removals >= MAX_REMOVALS {
                    bail!("cycle removal count exceeded");
                }
                self.removals += 1;
                let deferred = vec![vec![2, self.version, REMOVE, seq]];
                // Reserve a complete operation plus the final full observation.
                if self.remaining() < self.timeout + FTD_INTERACTION_TIMEOUT
                    || self.commands + 4 > MAX_COMMANDS
                {
                    return Ok((deferred, false));
                }
                self.commands += 1;
                let interfaces = self.console.target(ip, &self.allowed).await?;
                if interfaces.is_empty() {
                    return Ok((vec![vec![0, self.version, REMOVE, seq, 0]], false));
                }
                // Reserve ALL interface writes, target verification, and END.
                if self.commands + interfaces.len() + 2 > MAX_COMMANDS {
                    return Ok((deferred, false));
                }
                if interfaces.iter().any(|interface| {
                    !self.allowed.contains(interface) || !is_safe_interface(interface)
                }) {
                    bail!("cycle target interface is not allowlisted");
                }
                for interface in interfaces {
                    self.commands += 1;
                    self.console.remove(ip, &interface).await?;
                }
                self.commands += 1;
                if !self.console.target(ip, &self.allowed).await?.is_empty() {
                    bail!("cycle removal could not verify absence");
                }
                Ok((vec![vec![0, self.version, REMOVE, seq, 1]], false))
            }
        }
    }
}

pub(super) fn set_ipc_timeout(connection: &OwnedFd, duration: Duration) -> Result<()> {
    // Zero means unlimited to SO_*TIMEO; never pass zero on an expired cycle.
    let duration = duration.max(Duration::from_millis(1)).min(IPC_TIMEOUT);
    let value = TimeVal::new(duration.as_secs() as i64, duration.subsec_micros().into());
    setsockopt(connection, ReceiveTimeout, &value)?;
    setsockopt(connection, SendTimeout, &value)?;
    Ok(())
}

pub(super) fn handle(
    agent: &Agent,
    connection: &OwnedFd,
    runtime: &Handle,
    packet: &[u8],
) -> Result<Vec<u8>> {
    let started = Instant::now();
    let (device_id, version) = decode_begin(packet)?;
    if !agent.cycles_enabled {
        bail!("session cycles are disabled pending laboratory validation");
    }
    if version == snapshot::VERSION && !agent.large_snapshots_enabled {
        bail!("large snapshots are disabled pending laboratory validation");
    }
    let device = agent
        .devices
        .get(&device_id)
        .filter(|device| device.enabled)
        .context("unknown or disabled cycle device")?;
    let step_timeout = agent.operation_timeout.min(MAX_STEP_DURATION);
    let mut session = runtime.block_on(timeout(step_timeout, async {
        let password = load_ssh_password(&agent.password_file)?;
        SshSession::connect(device, &agent.username, password.as_str()).await
    }))??;
    session.large_snapshots = version == snapshot::VERSION;
    let mut cycle = Cycle {
        console: session,
        allowed: device.allowed_interfaces.clone(),
        started,
        timeout: step_timeout,
        commands: 0,
        removals: 0,
        priority_used: false,
        sequence: 1,
        version,
    };
    let result = (|| -> Result<Vec<u8>> {
        let initial = runtime.block_on(timeout(
            cycle
                .remaining()
                .min(step_timeout.saturating_sub(started.elapsed())),
            cycle.snapshot(BEGIN, 0),
        ))??;
        snapshot::send_frames(connection, &initial, started + step_timeout)?;
        loop {
            if cycle.remaining().is_zero() {
                bail!("cycle session deadline exceeded");
            }
            set_ipc_timeout(connection, cycle.remaining())?;
            let mut packet = [0u8; MAX_REQUEST_BYTES];
            let size = recv(connection.as_raw_fd(), &mut packet, MsgFlags::MSG_TRUNC)?;
            if size == 0 || size > packet.len() {
                bail!("cycle request closed or oversized");
            }
            let deadline = Instant::now() + cycle.remaining().min(step_timeout);
            let (response, done) = runtime.block_on(timeout(
                cycle.remaining().min(step_timeout),
                cycle.execute(&packet[..size]),
            ))??;
            snapshot::send_frames(connection, &response, deadline)?;
            if done {
                return Ok(Vec::new());
            }
        }
    })();
    // No uncertain CLI exit command: disconnect the transport on failure.
    runtime.block_on(async {
        let _ = timeout(
            Duration::from_secs(2),
            cycle
                .console
                .handle
                .disconnect(Disconnect::ByApplication, "", "en"),
        )
        .await;
    });
    eprintln!(
        "{}",
        serde_json::json!({
            "event": if result.is_ok() { "agent.cycle.completed" } else { "agent.cycle.failed" },
            "protocol_version": version,
            "device_id": device_id, "commands": cycle.commands, "removal_steps": cycle.removals,
            "elapsed_ms": started.elapsed().as_millis(),
            "reason": result.as_ref().err().map(|error| error.to_string()),
        })
    );
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Default)]
    struct FakeConsole {
        interfaces: BTreeSet<String>,
        writes: usize,
        fail_verify: bool,
        slow_verify: bool,
    }

    impl Console for FakeConsole {
        async fn snapshot(&mut self, _: &BTreeSet<String>) -> Result<BTreeSet<ObservedShun>> {
            Ok(BTreeSet::new())
        }
        async fn target(&mut self, _: Ipv4Addr, _: &BTreeSet<String>) -> Result<BTreeSet<String>> {
            if self.slow_verify && self.writes > 0 {
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
            Ok(self.interfaces.clone())
        }
        async fn remove(&mut self, _: Ipv4Addr, interface: &str) -> Result<()> {
            self.writes += 1;
            if !self.fail_verify {
                self.interfaces.remove(interface);
            }
            Ok(())
        }
    }

    fn fixture() -> Cycle<FakeConsole> {
        Cycle {
            console: FakeConsole {
                interfaces: BTreeSet::from(["outside".into()]),
                ..Default::default()
            },
            allowed: BTreeSet::from(["outside".into()]),
            started: Instant::now(),
            timeout: Duration::from_secs(45),
            commands: 1,
            removals: 0,
            priority_used: false,
            sequence: 1,
            version: VERSION,
        }
    }

    #[test]
    fn frames_are_exact_versioned_and_ordered() -> Result<()> {
        assert_eq!(decode_begin(&[BEGIN, VERSION, 0, 7])?, (7, VERSION));
        for packet in [
            vec![],
            vec![BEGIN, VERSION, 0, 0],
            vec![BEGIN, 3, 0, 1],
            vec![BEGIN, VERSION, 0, 1, 0],
        ] {
            assert!(decode_begin(&packet).is_err());
        }
        for packet in [
            vec![],
            vec![REMOVE, VERSION, 1],
            vec![END, VERSION, 2],
            vec![END, VERSION, 1, 0],
            vec![SNAPSHOT, 2, 1],
            vec![0xff, VERSION, 1],
        ] {
            assert!(decode_step(&packet, 1, VERSION).is_err());
        }
        Ok(())
    }

    #[test]
    fn oversize_seqpacket_and_disabled_cycle_are_rejected_before_ssh() -> Result<()> {
        use nix::sys::socket::socketpair;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let mut agent = Agent {
            devices: BTreeMap::new(),
            username: "unused".into(),
            password_file: PathBuf::from("/unused/test-secret"),
            operation_timeout: Duration::from_secs(45),
            cycles_enabled: false,
            large_snapshots_enabled: false,
        };
        let (sender, receiver) = socketpair(
            AddressFamily::Unix,
            SockType::SeqPacket,
            None,
            SockFlag::SOCK_CLOEXEC,
        )?;
        set_ipc_timeout(&receiver, Duration::from_secs(1))?;
        let mut oversized = vec![0u8; 128];
        oversized[..4].copy_from_slice(&[BEGIN, VERSION, 0, 7]);
        send(sender.as_raw_fd(), &oversized, MsgFlags::MSG_NOSIGNAL)?;
        assert_eq!(
            handle_connection(&agent, &receiver, runtime.handle()),
            RESPONSE_REJECTED
        );
        send(
            sender.as_raw_fd(),
            &[BEGIN, VERSION, 0, 7],
            MsgFlags::MSG_NOSIGNAL,
        )?;
        assert_eq!(
            handle_connection(&agent, &receiver, runtime.handle()),
            RESPONSE_REJECTED
        );
        agent.cycles_enabled = true;
        let error = handle(&agent, &receiver, runtime.handle(), &[BEGIN, 2, 0, 7])
            .err()
            .context("v2 must be disabled")?;
        assert!(error.to_string().contains("large snapshots are disabled"));
        send(sender.as_raw_fd(), &[7, 0, 7], MsgFlags::MSG_NOSIGNAL)?;
        assert_eq!(
            handle_connection(&agent, &receiver, runtime.handle()),
            RESPONSE_REJECTED
        );
        Ok(())
    }

    #[tokio::test]
    async fn v2_changes_snapshot_frames_not_removal_semantics() -> Result<()> {
        let mut cycle = fixture();
        cycle.version = 2;
        assert_eq!(decode_begin(&[BEGIN, 2, 0, 7])?, (7, 2));
        let initial = cycle.snapshot(BEGIN, 0).await?;
        assert_eq!(initial.len(), 2);
        assert_eq!(&initial[0][..5], &[0, 2, BEGIN, 0, 0]);
        let reply = cycle.execute(&[REMOVE, 2, 1, 203, 0, 113, 17]).await?.0;
        assert_eq!(reply, vec![vec![0, 2, REMOVE, 1, 1]]);
        assert_eq!(cycle.console.writes, 1);
        assert!(cycle.execute(&[END, 1, 2]).await.is_err());
        let (final_frames, done) = cycle.execute(&[END, 2, 2]).await?;
        assert!(done);
        assert_eq!(final_frames.len(), 2);
        Ok(())
    }

    #[tokio::test]
    async fn shared_python_rust_wire_vectors() -> Result<()> {
        let vectors: serde_json::Value =
            serde_json::from_str(include_str!("../../tests/fixtures/agent-cycle-v1.json"))?;
        for vector in vectors
            .as_array()
            .context("wire vectors must be an array")?
        {
            let unhex = |field: &str| -> Result<Vec<u8>> {
                let value = vector[field].as_str().context("missing hex field")?;
                value
                    .as_bytes()
                    .chunks(2)
                    .map(|pair| Ok(u8::from_str_radix(std::str::from_utf8(pair)?, 16)?))
                    .collect()
            };
            let request = unhex("request")?;
            let expected = unhex("response")?;
            let mut cycle = fixture();
            cycle.sequence = request[2];
            let response = if request[0] == BEGIN {
                assert_eq!(decode_begin(&request)?, (7, VERSION));
                cycle.snapshot(BEGIN, 0).await?
            } else {
                if expected[0] == 2 {
                    cycle.commands = MAX_COMMANDS - 1;
                }
                cycle.execute(&request).await?.0
            };
            assert_eq!(response, vec![expected]);
        }
        Ok(())
    }

    #[tokio::test]
    async fn many_interfaces_defer_before_first_write() -> Result<()> {
        let mut cycle = fixture();
        cycle.allowed = (0..64).map(|index| format!("outside{index}")).collect();
        cycle.console.interfaces = cycle.allowed.clone();
        assert_eq!(
            cycle
                .execute(&[REMOVE, VERSION, 1, 203, 0, 113, 17])
                .await?
                .0,
            vec![vec![2, VERSION, REMOVE, 1]]
        );
        assert_eq!(cycle.console.writes, 0);
        assert_eq!(cycle.commands, 2); // Initial snapshot and target read only.
        assert!(cycle.execute(&[END, VERSION, 2]).await?.1);
        Ok(())
    }

    #[tokio::test]
    async fn priority_budget_preserves_final_observation() -> Result<()> {
        for time_limited in [false, true] {
            let mut cycle = fixture();
            if time_limited {
                cycle.started = Instant::now() - Duration::from_secs(95);
            } else {
                cycle.commands = MAX_COMMANDS - 1;
            }
            let before = cycle.commands;
            assert_eq!(
                cycle.execute(&[SNAPSHOT, VERSION, 1]).await?.0,
                vec![vec![2, VERSION, SNAPSHOT, 1]]
            );
            assert_eq!(cycle.commands, before);
            assert_eq!(cycle.console.writes, 0);
            assert!(cycle.execute(&[END, VERSION, 2]).await?.1);
        }
        Ok(())
    }

    #[tokio::test]
    async fn removal_count_limit_is_independent_of_command_count() -> Result<()> {
        let mut cycle = fixture();
        cycle.console.interfaces.clear();
        for seq in 1..=MAX_REMOVALS {
            assert_eq!(
                cycle
                    .execute(&[REMOVE, VERSION, seq, 203, 0, 113, 17])
                    .await?
                    .0,
                vec![vec![0, VERSION, REMOVE, seq, 0]]
            );
        }
        assert!(
            cycle
                .execute(&[REMOVE, VERSION, MAX_REMOVALS + 1, 203, 0, 113, 17])
                .await
                .is_err()
        );
        assert_eq!(cycle.console.writes, 0);
        Ok(())
    }

    #[tokio::test]
    async fn timeout_after_write_never_returns_success() {
        let mut cycle = fixture();
        cycle.console.slow_verify = true;
        let result = timeout(
            Duration::from_millis(5),
            cycle.execute(&[REMOVE, VERSION, 1, 203, 0, 113, 17]),
        )
        .await;
        assert!(result.is_err());
        assert_eq!(cycle.console.writes, 1);
    }

    #[tokio::test]
    async fn sequential_removal_priority_and_final_snapshot() -> Result<()> {
        let mut cycle = fixture();
        let (reply, _) = cycle
            .execute(&[REMOVE, VERSION, 1, 203, 0, 113, 17])
            .await?;
        assert_eq!(reply, vec![vec![0, VERSION, REMOVE, 1, 1]]);
        assert_eq!(cycle.console.writes, 1);
        let (reply, _) = cycle.execute(&[SNAPSHOT, VERSION, 2]).await?;
        assert_eq!(reply, vec![vec![0, VERSION, SNAPSHOT, 2, 0, 0, 0]]);
        assert!(cycle.execute(&[SNAPSHOT, VERSION, 3]).await.is_err());
        assert_eq!(cycle.console.writes, 1);
        Ok(())
    }

    #[tokio::test]
    async fn budgets_defer_without_writes_and_reserve_final_snapshot() -> Result<()> {
        let mut cycle = fixture();
        cycle.commands = MAX_COMMANDS - 3;
        assert_eq!(
            cycle
                .execute(&[REMOVE, VERSION, 1, 203, 0, 113, 17])
                .await?
                .0,
            vec![vec![2, VERSION, REMOVE, 1]]
        );
        assert_eq!(cycle.console.writes, 0);
        assert!(cycle.execute(&[END, VERSION, 2]).await?.1);
        let mut cycle = fixture();
        cycle.started = Instant::now() - Duration::from_secs(65);
        assert_eq!(
            cycle
                .execute(&[REMOVE, VERSION, 1, 203, 0, 113, 17])
                .await?
                .0,
            vec![vec![2, VERSION, REMOVE, 1]]
        );
        assert_eq!(cycle.console.writes, 0);
        Ok(())
    }

    #[tokio::test]
    async fn unknown_interface_and_unverified_write_fail_closed() -> Result<()> {
        let mut cycle = fixture();
        cycle.console.interfaces.insert("unlisted".into());
        assert!(
            cycle
                .execute(&[REMOVE, VERSION, 1, 203, 0, 113, 17])
                .await
                .is_err()
        );
        assert_eq!(cycle.console.writes, 0);
        // Production target parsing rejects unknown interfaces before any write.
        let mut cycle = fixture();
        cycle.console.fail_verify = true;
        assert!(
            cycle
                .execute(&[REMOVE, VERSION, 1, 203, 0, 113, 17])
                .await
                .is_err()
        );
        assert_eq!(cycle.console.writes, 1);
        Ok(())
    }
}
