//! Versioned checkpoint protocol. No text/route/interface crosses this boundary.

use super::*;
use nix::sys::socket::setsockopt;
use nix::sys::socket::sockopt::{ReceiveTimeout, SendTimeout};
use nix::sys::time::TimeVal;
use std::time::Instant;

const VERSION: u8 = 1;
const BEGIN: u8 = 0x10;
pub(super) const BEGIN_SETTLED: u8 = 0x16;
pub(super) const BEGIN_RECOVERABLE: u8 = 0x17;
const SNAPSHOT: u8 = 0x11;
const REMOVE: u8 = 0x12;
const END: u8 = 0x13;
const ADD: u8 = 0x14;
const MAX_REMOVALS: u8 = 16;
const MAX_COMMANDS: usize = 64;
const MAX_DURATION: Duration = Duration::from_secs(120);
const IPC_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_STEP_DURATION: Duration = Duration::from_secs(45);

#[derive(Debug, PartialEq)]
enum Step {
    Snapshot,
    Remove(Ipv4Addr),
    Add(Ipv4Addr),
    StageAdd(Ipv4Addr),
    VerifyAdds,
    VerifyEnd,
    EndPending,
    End,
}

pub(super) fn max_sequence(version: u8) -> u8 {
    if matches!(
        version,
        batch_addition::MULTI_GROUP_VERSION | batch_addition::PENDING_END_VERSION
    ) {
        130
    } else if batch_addition::supported(version) {
        batch_addition::MAX_SEQUENCE
    } else {
        18
    }
}

pub(super) fn max_duration(version: u8) -> Duration {
    if matches!(
        version,
        batch_addition::MULTI_GROUP_VERSION | batch_addition::PENDING_END_VERSION
    ) {
        Duration::from_secs(240)
    } else {
        MAX_DURATION
    }
}

pub(super) fn decode_begin(packet: &[u8]) -> Result<(u16, u8)> {
    if packet.first() == Some(&sessions::BEGIN) {
        let key = sessions::decode(packet, sessions::BEGIN)?;
        return Ok((key.device, key.version));
    }
    if packet.len() != 4
        || !matches!(packet[0], BEGIN | BEGIN_SETTLED | BEGIN_RECOVERABLE)
        || !matches!(packet[1], VERSION | snapshot::VERSION | addition::VERSION)
    {
        bail!("invalid cycle begin frame");
    }
    let device = u16::from_be_bytes([packet[2], packet[3]]);
    if device == 0 {
        bail!("invalid cycle device");
    }
    Ok((device, packet[1]))
}

fn after_cleanup(
    begin: u8,
    version: u8,
    sequence: u8,
    cleanup: Result<()>,
) -> Result<Option<[u8; 4]>> {
    if !matches!(
        begin,
        BEGIN | BEGIN_SETTLED | BEGIN_RECOVERABLE | sessions::BEGIN
    ) || !matches!(version, 1..=7)
        || (batch_addition::supported(version) && begin != sessions::BEGIN)
        || !(1..=max_sequence(version)).contains(&sequence)
    {
        bail!("invalid local settlement binding");
    }
    if matches!(begin, BEGIN_SETTLED | BEGIN_RECOVERABLE | sessions::BEGIN) {
        cleanup?;
        Ok(Some([0, version, begin, sequence]))
    } else {
        Ok(None) // Legacy cleanup failure never acquires new receipt semantics.
    }
}

pub(super) fn finish_result(
    begin: u8,
    version: u8,
    result: Result<u8>,
    cleanup: Result<()>,
    failed_read: Option<(u8, u8)>,
    mutation_steps: u8,
) -> Result<Option<[u8; 4]>> {
    if matches!(begin, BEGIN_RECOVERABLE | sessions::BEGIN)
        && matches!(version, 1..=7)
        && (!batch_addition::supported(version) || begin == sessions::BEGIN)
        && result.is_err()
        && cleanup.is_ok()
        && mutation_steps == 0
        && let Some((opcode, sequence)) = failed_read
        && ((opcode == begin && sequence == 0)
            || (matches!(opcode, SNAPSHOT | END)
                && (1..=max_sequence(version)).contains(&sequence)))
    {
        // Not emitted here: ConnectionCompletion still waits for the
        // console/resource drop, guard release and worker-IDLE boundary.
        return Ok(Some([4, version, opcode, sequence]));
    }
    result.and_then(|sequence| after_cleanup(begin, version, sequence, cleanup))
}

fn decode_step(packet: &[u8], expected: u8, version: u8) -> Result<Step> {
    if !matches!(version, 1..=7)
        || packet.len() < 3
        || packet[1] != version
        || packet[2] != expected
        || !(1..=max_sequence(version)).contains(&expected)
    {
        bail!("invalid cycle version or sequence");
    }
    match (packet[0], packet.len()) {
        (SNAPSHOT, 3) => Ok(Step::Snapshot),
        (END, 3) => Ok(Step::End),
        (batch_addition::END_PENDING, 3) if version == batch_addition::PENDING_END_VERSION => {
            Ok(Step::EndPending)
        }
        (REMOVE, 7) => Ok(Step::Remove(Ipv4Addr::new(
            packet[3], packet[4], packet[5], packet[6],
        ))),
        (ADD, 7) if version == addition::VERSION => Ok(Step::Add(Ipv4Addr::new(
            packet[3], packet[4], packet[5], packet[6],
        ))),
        (batch_addition::STAGE, 7) if batch_addition::supported(version) => Ok(Step::StageAdd(
            Ipv4Addr::new(packet[3], packet[4], packet[5], packet[6]),
        )),
        (batch_addition::VERIFY, 3) if batch_addition::supported(version) => Ok(Step::VerifyAdds),
        (batch_addition::VERIFY_END, 3) if version >= batch_addition::SHARED_END_VERSION => {
            Ok(Step::VerifyEnd)
        }
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
    async fn addition_present(&mut self, _: Ipv4Addr, _: &BTreeSet<String>) -> Result<bool> {
        bail!("console addition preflight is unavailable")
    }
    async fn add(&mut self, _: Ipv4Addr, _: addition::Profile) -> Result<()> {
        bail!("console addition is unavailable")
    }
    async fn verify_add(
        &mut self,
        _: Ipv4Addr,
        _: &BTreeSet<String>,
        _: addition::Profile,
    ) -> Result<()> {
        bail!("console addition verification is unavailable")
    }
    async fn verify_adds(
        &mut self,
        _: &[Ipv4Addr],
        _: &BTreeSet<String>,
        _: addition::Profile,
    ) -> Result<BTreeSet<ObservedShun>> {
        bail!("console batch verification is unavailable")
    }
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
    async fn addition_present(&mut self, ip: Ipv4Addr, allowed: &BTreeSet<String>) -> Result<bool> {
        let output = self.show_shun(ip).await?;
        addition::already_present(&output, ip, allowed)
    }
    async fn add(&mut self, ip: Ipv4Addr, profile: addition::Profile) -> Result<()> {
        let output = self.run(CiscoOperation::AddShun(ip)).await?;
        addition::acknowledgement(&output, ip, profile)
    }
    async fn verify_add(
        &mut self,
        ip: Ipv4Addr,
        allowed: &BTreeSet<String>,
        profile: addition::Profile,
    ) -> Result<()> {
        addition::verify_creation(&self.show_shun(ip).await?, ip, allowed, profile)
    }
    async fn verify_adds(
        &mut self,
        targets: &[Ipv4Addr],
        allowed: &BTreeSet<String>,
        profile: addition::Profile,
    ) -> Result<BTreeSet<ObservedShun>> {
        batch_addition::verify(
            &self.run(CiscoOperation::ListShuns).await?,
            targets,
            allowed,
            profile,
        )
    }
}

struct Cycle<C> {
    console: C,
    allowed: BTreeSet<String>,
    started: Instant,
    timeout: Duration,
    commands: usize,
    removals: u8,
    additions: u8,
    pending_additions: Vec<Ipv4Addr>,
    addition_profile: Option<addition::Profile>,
    observed_entries: usize,
    priority_used: bool,
    sequence: u8,
    version: u8,
}

impl<C: Console> Cycle<C> {
    fn remaining(&self) -> Duration {
        self.max_duration().saturating_sub(self.started.elapsed())
    }

    fn max_duration(&self) -> Duration {
        max_duration(self.version)
    }

    fn max_mutations(&self) -> u8 {
        if matches!(
            self.version,
            batch_addition::MULTI_GROUP_VERSION | batch_addition::PENDING_END_VERSION
        ) {
            64
        } else {
            MAX_REMOVALS
        }
    }

    fn max_commands(&self) -> usize {
        if matches!(
            self.version,
            batch_addition::MULTI_GROUP_VERSION | batch_addition::PENDING_END_VERSION
        ) {
            256
        } else {
            MAX_COMMANDS
        }
    }

    fn stage_timeout(&self) -> Duration {
        if self.version >= batch_addition::SHARED_END_VERSION {
            self.timeout.min(FTD_INTERACTION_TIMEOUT * 2)
        } else {
            self.timeout
        }
    }

    async fn snapshot(&mut self, opcode: u8, sequence: u8) -> Result<Vec<Vec<u8>>> {
        if self.commands >= self.max_commands() {
            bail!("cycle snapshot command budget exhausted");
        }
        self.commands += 1;
        let entries = self.console.snapshot(&self.allowed).await?;
        self.observed_entries = entries.len();
        if self.version >= snapshot::VERSION {
            return snapshot::encode_versioned(entries, opcode, sequence, self.version);
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
        if !self.pending_additions.is_empty()
            && !matches!(
                step,
                Step::StageAdd(_) | Step::VerifyAdds | Step::VerifyEnd | Step::EndPending
            )
        {
            bail!("pending additions require explicit group verification before other operations");
        }
        let seq = self.sequence;
        self.sequence += 1;
        match step {
            Step::Snapshot => {
                if self.priority_used {
                    bail!("cycle priority snapshot budget exhausted");
                }
                self.priority_used = true;
                if self.commands + 2 > self.max_commands()
                    || self.remaining() < FTD_INTERACTION_TIMEOUT * 2
                {
                    return Ok((vec![vec![2, self.version, SNAPSHOT, seq]], false));
                }
                Ok((self.snapshot(SNAPSHOT, seq).await?, false))
            }
            Step::End => Ok((self.snapshot(END, seq).await?, true)),
            Step::EndPending => Ok((
                vec![batch_addition::pending_end(
                    &self.pending_additions,
                    seq,
                    self.version,
                )?],
                true,
            )),
            Step::Remove(ip) => {
                if self.removals + self.additions >= self.max_mutations() {
                    bail!("cycle combined mutation count exceeded");
                }
                self.removals += 1;
                let deferred = vec![vec![2, self.version, REMOVE, seq]];
                // Reserve a complete operation plus the final full observation.
                if self.remaining() < self.timeout + FTD_INTERACTION_TIMEOUT
                    || self.commands + 4 > self.max_commands()
                {
                    return Ok((deferred, false));
                }
                self.commands += 1;
                let interfaces = self.console.target(ip, &self.allowed).await?;
                if interfaces.is_empty() {
                    return Ok((vec![vec![0, self.version, REMOVE, seq, 0]], false));
                }
                // Reserve ALL interface writes, target verification, and END.
                if self.commands + interfaces.len() + 2 > self.max_commands() {
                    return Ok((deferred, false));
                }
                if interfaces.iter().any(|interface| {
                    !self.allowed.contains(interface) || !is_safe_interface(interface)
                }) {
                    bail!("cycle target interface is not allowlisted");
                }
                let removed = interfaces.len();
                for interface in interfaces {
                    self.commands += 1;
                    self.console.remove(ip, &interface).await?;
                }
                self.commands += 1;
                if !self.console.target(ip, &self.allowed).await?.is_empty() {
                    bail!("cycle removal could not verify absence");
                }
                self.observed_entries = self.observed_entries.saturating_sub(removed);
                Ok((vec![vec![0, self.version, REMOVE, seq, 1]], false))
            }
            Step::Add(ip) => {
                let profile = self
                    .addition_profile
                    .context("device has no addition profile")?;
                profile.validate(&self.allowed)?;
                if self.removals + self.additions >= self.max_mutations() {
                    bail!("cycle combined mutation count exceeded");
                }
                self.additions += 1;
                if self.remaining() < self.timeout + FTD_INTERACTION_TIMEOUT
                    || self.commands + 4 > self.max_commands()
                {
                    return Ok((vec![vec![2, self.version, ADD, seq]], false));
                }
                self.commands += 1;
                if self.console.addition_present(ip, &self.allowed).await? {
                    return Ok((vec![vec![0, self.version, ADD, seq, 0]], false));
                }
                if self.observed_entries >= snapshot::MAX_ENTRIES {
                    bail!("addition would exceed the complete snapshot entry budget");
                }
                self.commands += 1;
                self.console.add(ip, profile).await?;
                self.commands += 1;
                self.console.verify_add(ip, &self.allowed, profile).await?;
                self.observed_entries += 1;
                let name = profile.interface().as_bytes();
                let mut response = vec![0, self.version, ADD, seq, 1, name.len() as u8];
                response.extend(name);
                Ok((vec![response], false))
            }
            Step::StageAdd(ip) => {
                let profile = self
                    .addition_profile
                    .context("device has no addition profile")?;
                profile.validate(&self.allowed)?;
                if self.removals + self.additions >= self.max_mutations() {
                    bail!("cycle combined mutation count exceeded");
                }
                if self.pending_additions.contains(&ip) {
                    bail!("addition is already awaiting group verification");
                }
                self.additions += 1;
                // V5 bounds staging to two prompt interactions and combines
                // final verification/END. V4 retains its original reserve.
                if self.pending_additions.len() >= batch_addition::capacity(self.version)
                    || self.remaining() < self.stage_timeout() + FTD_INTERACTION_TIMEOUT
                    || self.commands + 4 > self.max_commands()
                {
                    return Ok((
                        vec![vec![2, self.version, batch_addition::STAGE, seq]],
                        false,
                    ));
                }
                self.commands += 1;
                if self.console.addition_present(ip, &self.allowed).await? {
                    return Ok((
                        vec![vec![0, self.version, batch_addition::STAGE, seq, 0]],
                        false,
                    ));
                }
                if self.observed_entries + self.pending_additions.len() >= snapshot::MAX_ENTRIES {
                    bail!("addition would exceed the complete snapshot entry budget");
                }
                self.commands += 1;
                self.console.add(ip, profile).await?;
                self.pending_additions.push(ip);
                // Status 05 is deliberately NOT a successful AdditionResult.
                Ok((
                    vec![vec![5, self.version, batch_addition::STAGE, seq]],
                    false,
                ))
            }
            Step::VerifyAdds | Step::VerifyEnd => {
                let final_group = step == Step::VerifyEnd;
                let opcode = if final_group {
                    batch_addition::VERIFY_END
                } else {
                    batch_addition::VERIFY
                };
                let profile = self
                    .addition_profile
                    .context("device has no addition profile")?;
                if self.pending_additions.is_empty()
                    || self.commands + if final_group { 1 } else { 2 } > self.max_commands()
                {
                    bail!("invalid pending verification or insufficient verification/END budget");
                }
                self.commands += 1;
                let entries = self
                    .console
                    .verify_adds(&self.pending_additions, &self.allowed, profile)
                    .await?;
                let mut frames = vec![batch_addition::receipt(
                    &self.pending_additions,
                    profile,
                    seq,
                    self.version,
                    opcode,
                )];
                let count = entries.len();
                frames.extend(snapshot::encode_versioned(
                    entries,
                    opcode,
                    seq,
                    self.version,
                )?);
                // Only completed verification may discard the pending scope.
                // Lost IPC afterwards still produces no client success or retry.
                self.observed_entries = count;
                self.pending_additions.clear();
                Ok((frames, final_group))
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

fn set_cycle_ipc_timeout(connection: &OwnedFd, duration: Duration, version: u8) -> Result<()> {
    set_ipc_timeout(connection, duration)?;
    if version >= batch_addition::SHARED_END_VERSION {
        // Durable group settlement can exceed the legacy idle wait. Transfer
        // limits and the absolute session deadline do not grow with this wait.
        let duration = duration
            .max(Duration::from_millis(1))
            .min(Duration::from_secs(30));
        setsockopt(
            connection,
            ReceiveTimeout,
            &TimeVal::new(duration.as_secs() as i64, duration.subsec_micros().into()),
        )?;
    }
    Ok(())
}

pub(super) fn handle(
    agent: &Agent,
    connection: &OwnedFd,
    runtime: &Handle,
    packet: &[u8],
) -> Result<Option<[u8; 4]>> {
    let started = Instant::now();
    let (device_id, version) = decode_begin(packet)?;
    if !agent.cycles_enabled {
        bail!("session cycles are disabled pending laboratory validation");
    }
    if version >= snapshot::VERSION && !agent.large_snapshots_enabled {
        bail!("large snapshots are disabled pending laboratory validation");
    }
    if batch_addition::supported(version) && !agent.batch_additions_enabled {
        bail!("batch additions are disabled pending worker integration and validation");
    }
    if version >= batch_addition::MULTI_GROUP_VERSION && agent.batch_session_version != version {
        bail!("multi-group session version is not explicitly enabled");
    }
    let device = agent
        .devices
        .get(&device_id)
        .filter(|device| device.enabled)
        .context("unknown or disabled cycle device")?;
    if version == addition::VERSION || batch_addition::supported(version) {
        if !agent.additions_enabled {
            bail!("additions are disabled pending laboratory validation");
        }
        device
            .addition_profile
            .context("device has no addition profile")?
            .validate(&device.allowed_interfaces)?;
    }
    let step_timeout = agent.operation_timeout.min(MAX_STEP_DURATION);
    let session_id = if packet[0] == sessions::BEGIN {
        Some(format!(
            "{:032x}",
            u128::from_be_bytes(sessions::decode(packet, sessions::BEGIN)?.id)
        ))
    } else {
        None
    };
    // No Cycle/Console command executor exists until this future succeeds.
    // timeout drops the opening future before a failure record can escape.
    let opening_started = Instant::now();
    let opened = runtime
        // Local root checks/result persistence can leave SSH silent longer
        // than a single CLI call. The transport idle timer must not pre-empt
        // this visit's unchanged hard wall-clock/IPC/step deadlines.
        .block_on(timeout(
            step_timeout,
            agent.connect_device_with_idle(device_id, max_duration(version)),
        ))
        .context("SSH session opening timed out")
        .and_then(|result| result);
    let opening_ms = opening_started.elapsed().as_millis();
    let mut session = match opened {
        Ok(session) => session,
        Err(error) if matches!(packet[0], BEGIN_RECOVERABLE | sessions::BEGIN) => {
            eprintln!(
                "{}",
                serde_json::json!({
                    "event":"agent.cycle.open_failed", "device_id":device_id,
                    "protocol_version":version, "commands":0,
                    "session_id":session_id, "opening_ms":opening_ms,
                    "elapsed_ms":started.elapsed().as_millis(), "reason":error.to_string(),
                })
            );
            // Emitted only by ConnectionCompletion after guards/worker settle.
            if packet[0] == sessions::BEGIN {
                agent
                    .sessions
                    .prepare_read_only(sessions::decode(packet, sessions::BEGIN)?)?;
            }
            return Ok(Some([3, version, packet[0], 0]));
        }
        Err(error) => return Err(error),
    };
    session.large_snapshots = version >= snapshot::VERSION;
    let mut cycle = Cycle {
        console: session,
        allowed: device.allowed_interfaces.clone(),
        started,
        timeout: step_timeout,
        commands: 0,
        removals: 0,
        additions: 0,
        pending_additions: Vec::new(),
        addition_profile: if version == addition::VERSION || batch_addition::supported(version) {
            device.addition_profile
        } else {
            None
        },
        observed_entries: 0,
        priority_used: false,
        sequence: 1,
        version,
    };
    let mut failed_read = Some((packet[0], 0));
    let mut pending_terminal = None;
    let result = (|| -> Result<u8> {
        let initial = runtime.block_on(timeout(
            cycle
                .remaining()
                .min(step_timeout.saturating_sub(started.elapsed())),
            cycle.snapshot(packet[0], 0),
        ))??;
        snapshot::send_frames(connection, &initial, started + step_timeout)?;
        loop {
            failed_read = None; // An IPC/invalid-frame failure is not read proof.
            if cycle.remaining().is_zero() {
                bail!("cycle session deadline exceeded");
            }
            set_cycle_ipc_timeout(connection, cycle.remaining(), version)?;
            let mut packet = [0u8; MAX_REQUEST_BYTES];
            let size = recv(connection.as_raw_fd(), &mut packet, MsgFlags::MSG_TRUNC)?;
            if size == 0 || size > packet.len() {
                bail!("cycle request closed or oversized");
            }
            if matches!(
                decode_step(&packet[..size], cycle.sequence, version),
                Ok(Step::Snapshot | Step::End)
            ) {
                failed_read = Some((packet[0], packet[2]));
            }
            let operation_timeout = if version >= batch_addition::SHARED_END_VERSION
                && packet[0] == batch_addition::STAGE
            {
                cycle.stage_timeout()
            } else {
                step_timeout
            };
            let deadline = Instant::now() + cycle.remaining().min(operation_timeout);
            let execution = runtime
                .block_on(timeout(
                    cycle.remaining().min(operation_timeout),
                    cycle.execute(&packet[..size]),
                ))
                .context("cycle step timed out")
                .and_then(|result| result);
            if (version == addition::VERSION || batch_addition::supported(version))
                && size == 7
                && matches!(packet[0], ADD | batch_addition::STAGE)
            {
                let event = match &execution {
                    Ok((frames, _)) if frames[0][0] == 2 => "agent.add_shun.deferred",
                    Ok((frames, _)) if frames[0][0] == 5 => "agent.add_shun.awaiting_verification",
                    Ok((frames, _)) if frames[0][4] == 0 => "agent.add_shun.noop",
                    Ok(_) => "agent.add_shun.verified",
                    Err(_) => "agent.add_shun.failed",
                };
                eprintln!(
                    "{}",
                    serde_json::json!({
                        "event":event,"device_id":device_id,"sequence":packet[2],
                        "target_ip":Ipv4Addr::new(packet[3],packet[4],packet[5],packet[6]).to_string(),
                        "reason":execution.as_ref().err().map(|error| error.to_string()),
                    })
                );
            }
            let (response, done) = execution?;
            if done && packet[0] == batch_addition::END_PENDING {
                // Retain the exact executed scope even if its local send fails.
                // Publication still requires successful disconnect AND postamble.
                pending_terminal = Some((packet[2], cycle.pending_additions.clone()));
            }
            snapshot::send_frames(connection, &response, deadline)?;
            if done {
                return Ok(packet[2]);
            }
        }
    })();
    // No uncertain CLI exit command: disconnect the transport on failure.
    let cleanup = runtime.block_on(async {
        timeout(
            Duration::from_secs(2),
            cycle
                .console
                .handle
                .disconnect(Disconnect::ByApplication, "", "en"),
        )
        .await
    });
    let cleanup = cleanup
        .context("settled cycle disconnect timed out")
        .and_then(|result| result.map_err(Into::into));
    if packet[0] == sessions::BEGIN && cleanup.is_ok() && cycle.removals + cycle.additions == 0 {
        agent
            .sessions
            .prepare_read_only(sessions::decode(packet, sessions::BEGIN)?)?;
    }
    if packet[0] == sessions::BEGIN
        && cleanup.is_ok()
        && let Some((sequence, targets)) = pending_terminal
    {
        agent.sessions.prepare_pending(
            sessions::decode(packet, sessions::BEGIN)?,
            sequence,
            &targets,
        )?;
    }
    let reason = result
        .as_ref()
        .err()
        .or_else(|| cleanup.as_ref().err())
        .map(|error| error.to_string());
    let result = finish_result(
        packet[0],
        version,
        result,
        cleanup,
        failed_read,
        cycle.removals + cycle.additions,
    );
    let read_failed_settled = matches!(&result, Ok(Some([4, ..])));
    eprintln!(
        "{}",
        serde_json::json!({
            "event": if result.is_ok() && !read_failed_settled { "agent.cycle.completed" } else { "agent.cycle.failed" },
            "protocol_version": version,
            "session_id": session_id,
            "opening_ms": opening_ms,
            "cli_phases": cycle.console.timing.report(),
            "device_id": device_id, "commands": cycle.commands, "removal_steps": cycle.removals,
            "elapsed_ms": started.elapsed().as_millis(),
            "addition_steps": cycle.additions,
            "pending_additions": cycle.pending_additions.len(),
            "mutation_steps": cycle.removals + cycle.additions,
            "reason": reason,
            "read_failure_settled": read_failed_settled,
        })
    );
    result
}

#[cfg(test)]
#[path = "batch_cycle_tests.rs"]
mod batch_tests;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn read_failure_vectors_require_read_only_session_and_successful_cleanup() -> Result<()> {
        let vectors: serde_json::Value =
            serde_json::from_str(include_str!("../../tests/fixtures/agent-read-failure.json"))?;
        for vector in vectors.as_array().context("vectors")? {
            let version = vector["version"].as_u64().context("version")? as u8;
            for (name, opcode, sequence) in [
                ("initial_failed", BEGIN_RECOVERABLE, 0),
                ("snapshot_failed", SNAPSHOT, 1),
                ("end_failed", END, 2),
            ] {
                let failed = || Err(anyhow::anyhow!("synthetic read failure"));
                let record = finish_result(
                    BEGIN_RECOVERABLE,
                    version,
                    failed(),
                    Ok(()),
                    Some((opcode, sequence)),
                    0,
                )?
                .context("terminal read failure")?;
                let hex: String = record.iter().map(|byte| format!("{byte:02x}")).collect();
                assert_eq!(hex, vector[name]);
                for mutations in [1, 16] {
                    assert!(
                        finish_result(
                            BEGIN_RECOVERABLE,
                            version,
                            failed(),
                            Ok(()),
                            Some((opcode, sequence)),
                            mutations
                        )
                        .is_err()
                    );
                }
                assert!(
                    finish_result(
                        BEGIN_RECOVERABLE,
                        version,
                        failed(),
                        Err(anyhow::anyhow!("cleanup failed")),
                        Some((opcode, sequence)),
                        0
                    )
                    .is_err()
                );
                for begin in [BEGIN, BEGIN_SETTLED] {
                    assert!(
                        finish_result(
                            begin,
                            version,
                            failed(),
                            Ok(()),
                            Some((opcode, sequence)),
                            0
                        )
                        .is_err()
                    );
                }
                assert!(
                    finish_result(BEGIN_RECOVERABLE, version, failed(), Ok(()), None, 0).is_err()
                );
            }
        }
        for binding in [
            (BEGIN_RECOVERABLE, 1),
            (BEGIN_SETTLED, 0),
            (REMOVE, 1),
            (ADD, 1),
            (SNAPSHOT, 0),
            (END, 19),
        ] {
            assert!(
                finish_result(
                    BEGIN_RECOVERABLE,
                    3,
                    Err(anyhow::anyhow!("bad read")),
                    Ok(()),
                    Some(binding),
                    0
                )
                .is_err()
            );
        }
        for version in [0, 4] {
            assert!(
                finish_result(
                    BEGIN_RECOVERABLE,
                    version,
                    Err(anyhow::anyhow!("bad version")),
                    Ok(()),
                    Some((END, 1)),
                    0
                )
                .is_err()
            );
        }
        assert_eq!(
            finish_result(BEGIN_RECOVERABLE, 3, Ok(1), Ok(()), Some((END, 1)), 0)?,
            Some([0, 3, BEGIN_RECOVERABLE, 1])
        );
        Ok(())
    }

    #[tokio::test]
    async fn read_errors_and_timeouts_never_mutate_but_prior_noop_and_deferral_still_disqualify()
    -> Result<()> {
        for opcode in [BEGIN_RECOVERABLE, SNAPSHOT, END] {
            let mut cycle = fixture();
            cycle.console.fail_snapshot = true;
            let result = if opcode == BEGIN_RECOVERABLE {
                cycle.snapshot(opcode, 0).await.map(|_| 0)
            } else {
                cycle.execute(&[opcode, VERSION, 1]).await.map(|_| 1)
            };
            assert!(result.is_err());
            assert_eq!(cycle.console.writes, 0);
            assert!(
                finish_result(
                    BEGIN_RECOVERABLE,
                    VERSION,
                    result,
                    Ok(()),
                    Some((opcode, if opcode == BEGIN_RECOVERABLE { 0 } else { 1 })),
                    cycle.removals + cycle.additions
                )?
                .is_some()
            );
        }
        for opcode in [ADD, REMOVE] {
            for defer in [false, true] {
                let mut cycle = fixture();
                cycle.version = addition::VERSION;
                cycle.addition_profile = Some(addition::Profile::Fpr1010Management);
                cycle.allowed.insert("management".into());
                cycle.console.interfaces.clear();
                if opcode == ADD && !defer {
                    cycle.console.interfaces.insert("management".into());
                }
                if defer {
                    cycle.commands = MAX_COMMANDS - 2;
                }
                let (response, _) = cycle
                    .execute(&[opcode, addition::VERSION, 1, 198, 51, 100, 250])
                    .await?;
                assert_eq!(response[0][0], if defer { 2 } else { 0 });
                assert_eq!(cycle.console.writes, 0);
                assert_eq!(cycle.removals + cycle.additions, 1);
                cycle.console.fail_snapshot = true;
                assert!(
                    finish_result(
                        BEGIN_RECOVERABLE,
                        addition::VERSION,
                        cycle.snapshot(END, 2).await.map(|_| 2),
                        Ok(()),
                        Some((END, 2)),
                        cycle.removals + cycle.additions
                    )
                    .is_err()
                );
            }
        }
        let mut cycle = fixture();
        cycle.console.slow_snapshot = true;
        let failure = timeout(
            Duration::from_millis(1),
            cycle.snapshot(BEGIN_RECOVERABLE, 0),
        )
        .await;
        assert!(failure.is_err());
        assert_eq!(cycle.console.writes, 0);
        Ok(())
    }

    #[tokio::test]
    async fn recoverable_opening_shares_exact_vectors_and_strict_cleanup() -> Result<()> {
        let vectors: serde_json::Value =
            serde_json::from_str(include_str!("../../tests/fixtures/agent-opening.json"))?;
        let hex = |bytes: &[u8]| {
            bytes
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect::<String>()
        };
        for vector in vectors.as_array().context("vectors")? {
            let version = vector["version"].as_u64().context("version")? as u8;
            assert_eq!(hex(&[BEGIN_RECOVERABLE, version, 0, 7]), vector["begin"]);
            assert_eq!(
                decode_begin(&[BEGIN_RECOVERABLE, version, 0, 7])?,
                (7, version)
            );
            assert_eq!(
                hex(&[3, version, BEGIN_RECOVERABLE, 0]),
                vector["open_failed"]
            );
            let mut cycle = fixture();
            cycle.version = version;
            let frames = cycle.snapshot(BEGIN_RECOVERABLE, 0).await?;
            assert_eq!(
                serde_json::to_value(frames.iter().map(|frame| hex(frame)).collect::<Vec<_>>())?,
                vector["initial"]
            );
            let record =
                after_cleanup(BEGIN_RECOVERABLE, version, 1, Ok(()))?.context("receipt")?;
            assert_eq!(hex(&record), vector["settled"]);
            assert!(
                after_cleanup(
                    BEGIN_RECOVERABLE,
                    version,
                    1,
                    Err(anyhow::anyhow!("cleanup failed"))
                )
                .is_err()
            );
        }
        for packet in [
            vec![BEGIN_RECOVERABLE],
            vec![BEGIN_RECOVERABLE, 0, 0, 7],
            vec![BEGIN_RECOVERABLE, 4, 0, 7],
            vec![BEGIN_RECOVERABLE, 1, 0, 0],
            vec![BEGIN_RECOVERABLE, 1, 0, 7, 0],
        ] {
            assert!(decode_begin(&packet).is_err());
        }
        Ok(())
    }

    #[tokio::test]
    async fn settled_cycles_share_fixed_vectors_and_legacy_end_budgets() -> Result<()> {
        let vectors: serde_json::Value =
            serde_json::from_str(include_str!("../../tests/fixtures/agent-settlement.json"))?;
        let hex = |bytes: &[u8]| {
            bytes
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect::<String>()
        };
        for vector in vectors.as_array().context("vectors")? {
            let version = vector["version"].as_u64().context("version")? as u8;
            let mut cycle = fixture();
            cycle.version = version;
            cycle.commands = 0;
            assert_eq!(hex(&[BEGIN_SETTLED, version, 0, 7]), vector["begin"]);
            assert_eq!(decode_begin(&[BEGIN_SETTLED, version, 0, 7])?, (7, version));
            let initial = cycle.snapshot(BEGIN_SETTLED, 0).await?;
            let initial = initial.iter().map(|frame| hex(frame)).collect::<Vec<_>>();
            assert_eq!(serde_json::to_value(initial)?, vector["initial"]);
            let end = [END, version, 1];
            assert_eq!(hex(&end), vector["end"]);
            let (frames, done) = cycle.execute(&end).await?;
            assert!(done);
            assert_eq!(
                serde_json::to_value(frames.iter().map(|frame| hex(frame)).collect::<Vec<_>>())?,
                vector["final"]
            );
            let record = after_cleanup(BEGIN_SETTLED, version, 1, Ok(()))?.context("receipt")?;
            assert_eq!(hex(&record), vector["settled"]);
            assert!(after_cleanup(BEGIN, version, 1, Ok(()))?.is_none());
            assert_eq!(cycle.commands, 2);
            assert_eq!(cycle.removals + cycle.additions, 0);
        }
        Ok(())
    }

    #[test]
    fn settlement_never_ignores_failed_cleanup_or_invalid_binding() -> Result<()> {
        assert!(
            after_cleanup(
                BEGIN_SETTLED,
                3,
                1,
                Err(anyhow::anyhow!("synthetic disconnect failure"))
            )
            .is_err()
        );
        assert!(
            after_cleanup(BEGIN, 3, 1, Err(anyhow::anyhow!("legacy cleanup failure")))?.is_none()
        );
        for packet in [
            vec![BEGIN_SETTLED],
            vec![BEGIN_SETTLED, 1, 0],
            vec![BEGIN_SETTLED, 1, 0, 0],
            vec![BEGIN_SETTLED, 4, 0, 7],
            vec![BEGIN_SETTLED, 1, 0, 7, 0],
        ] {
            assert!(decode_begin(&packet).is_err());
        }
        for (version, sequence) in [(0, 1), (4, 1), (1, 0), (3, 19)] {
            assert!(after_cleanup(BEGIN_SETTLED, version, sequence, Ok(())).is_err());
        }
        assert!(after_cleanup(0x15, 1, 1, Ok(())).is_err());
        Ok(())
    }

    #[derive(Default)]
    struct FakeConsole {
        interfaces: BTreeSet<String>,
        writes: usize,
        fail_verify: bool,
        slow_verify: bool,
        add_calls: usize,
        add_reads: usize,
        last_add: Option<Ipv4Addr>,
        ack_override: Option<String>,
        verify_override: Option<String>,
        preflight_override: Option<String>,
        fail_snapshot: bool,
        slow_snapshot: bool,
    }

    impl Console for FakeConsole {
        async fn snapshot(&mut self, _: &BTreeSet<String>) -> Result<BTreeSet<ObservedShun>> {
            if self.fail_snapshot {
                bail!("synthetic snapshot failure");
            }
            if self.slow_snapshot {
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
            if let Some(ip) = self.last_add {
                return Ok(self
                    .interfaces
                    .iter()
                    .map(|interface| ObservedShun {
                        target: ip,
                        interface: interface.clone(),
                    })
                    .collect());
            }
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
        async fn addition_present(
            &mut self,
            ip: Ipv4Addr,
            allowed: &BTreeSet<String>,
        ) -> Result<bool> {
            self.add_reads += 1;
            let output = self.preflight_override.clone().unwrap_or_else(|| {
                self.interfaces
                    .iter()
                    .map(|name| format!("shun ({name}) {ip} 0.0.0.0 0 0 0\n"))
                    .collect()
            });
            addition::already_present(&output, ip, allowed)
        }
        async fn add(&mut self, ip: Ipv4Addr, profile: addition::Profile) -> Result<()> {
            self.writes += 1;
            self.add_calls += 1;
            self.last_add = Some(ip);
            self.interfaces.insert("management".into());
            let output = self.ack_override.clone().unwrap_or_else(|| {
                format!("Shun {ip} added in context: single_vf\nShun {ip} successful")
            });
            addition::acknowledgement(&output, ip, profile)
        }
        async fn verify_add(
            &mut self,
            ip: Ipv4Addr,
            allowed: &BTreeSet<String>,
            profile: addition::Profile,
        ) -> Result<()> {
            self.add_reads += 1;
            if self.slow_verify {
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
            let output = self.verify_override.clone().unwrap_or_else(|| {
                if self.fail_verify {
                    String::new()
                } else {
                    format!("shun (management) {ip} 0.0.0.0 0 0 0")
                }
            });
            addition::verify_creation(&output, ip, allowed, profile)
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
            additions: 0,
            pending_additions: Vec::new(),
            addition_profile: None,
            observed_entries: 0,
            priority_used: false,
            sequence: 1,
            version: VERSION,
        }
    }

    fn addition_fixture() -> Cycle<FakeConsole> {
        let mut cycle = fixture();
        cycle.version = addition::VERSION;
        cycle.addition_profile = Some(addition::Profile::Fpr1010Management);
        cycle.allowed = BTreeSet::from(["management".into()]);
        cycle.console.interfaces.clear();
        cycle
    }

    #[tokio::test]
    async fn shared_v3_vectors_and_verified_add_noop_remove() -> Result<()> {
        let vectors: serde_json::Value =
            serde_json::from_str(include_str!("../../tests/fixtures/agent-addition-v3.json"))?;
        let unhex = |value: &serde_json::Value| -> Result<Vec<u8>> {
            value
                .as_str()
                .context("hex field")?
                .as_bytes()
                .chunks(2)
                .map(|pair| Ok(u8::from_str_radix(std::str::from_utf8(pair)?, 16)?))
                .collect()
        };
        let entries = BTreeSet::from([ObservedShun {
            target: Ipv4Addr::new(198, 51, 100, 251),
            interface: "management".into(),
        }]);
        let expected: Result<Vec<_>> = vectors["snapshot"]["frames"]
            .as_array()
            .context("frames")?
            .iter()
            .map(unhex)
            .collect();
        assert_eq!(snapshot::encode_versioned(entries, BEGIN, 0, 3)?, expected?);
        assert_eq!(
            decode_begin(&unhex(&vectors["snapshot"]["request"])?)?,
            (7, 3)
        );
        for vector in vectors["add"].as_array().context("add vectors")? {
            let mut cycle = addition_fixture();
            let request = unhex(&vector["request"])?;
            cycle.sequence = request[2];
            if vector["result"] == "noop" {
                cycle.console.interfaces.insert("management".into());
            }
            if vector["result"] == "deferred" {
                cycle.commands = MAX_COMMANDS - 3;
            }
            assert_eq!(
                cycle.execute(&request).await?.0,
                vec![unhex(&vector["response"])?]
            );
            assert_eq!(
                cycle.console.add_calls,
                usize::from(vector["result"] == "created")
            );
        }
        let mut cycle = addition_fixture();
        let target = [198, 51, 100, 251];
        let request = |op, seq| {
            let mut frame = vec![op, 3, seq];
            frame.extend(target);
            frame
        };
        assert_eq!(cycle.execute(&request(ADD, 1)).await?.0[0][4], 1);
        assert_eq!(
            cycle.execute(&request(ADD, 2)).await?.0,
            vec![vec![0, 3, ADD, 2, 0]]
        );
        assert_eq!(cycle.console.add_calls, 1);
        assert_eq!(cycle.observed_entries, 1);
        assert_eq!(
            cycle.execute(&request(REMOVE, 3)).await?.0,
            vec![vec![0, 3, REMOVE, 3, 1]]
        );
        assert_eq!(cycle.observed_entries, 0);
        assert_eq!(cycle.console.writes, 2);
        assert!(cycle.execute(&[END, 3, 4]).await?.1);
        Ok(())
    }

    #[tokio::test]
    async fn add_reserves_budget_and_combines_noop_attempts_with_removals() -> Result<()> {
        for timed_out in [false, true] {
            let mut cycle = addition_fixture();
            if timed_out {
                cycle.started = Instant::now() - Duration::from_secs(61);
            } else {
                cycle.commands = 61;
            }
            assert_eq!(
                cycle.execute(&[ADD, 3, 1, 198, 51, 100, 251]).await?.0,
                vec![vec![2, 3, ADD, 1]]
            );
            assert_eq!(cycle.console.add_reads, 0);
            assert_eq!(cycle.console.writes, 0);
        }
        let mut cycle = addition_fixture();
        cycle.commands = 60;
        cycle.execute(&[ADD, 3, 1, 198, 51, 100, 251]).await?;
        assert_eq!(cycle.commands, 63);
        assert_eq!(
            cycle.execute(&[SNAPSHOT, 3, 2]).await?.0,
            vec![vec![2, 3, SNAPSHOT, 2]]
        );
        cycle.execute(&[END, 3, 3]).await?;
        assert_eq!(cycle.commands, 64);
        let mut cycle = addition_fixture();
        cycle.console.preflight_override =
            Some("shun (management) 198.51.100.251 0.0.0.0 0 0 0".into());
        for seq in 1..=16 {
            let op = if seq % 2 == 0 { REMOVE } else { ADD };
            cycle.execute(&[op, 3, seq, 198, 51, 100, 251]).await?;
        }
        assert_eq!((cycle.additions, cycle.removals), (8, 8));
        assert!(
            cycle
                .execute(&[ADD, 3, 17, 198, 51, 100, 251])
                .await
                .is_err()
        );
        assert_eq!(cycle.console.writes, 0);
        Ok(())
    }

    #[tokio::test]
    async fn add_scope_capacity_and_uncertain_results_never_become_success() -> Result<()> {
        for missing_profile in [false, true] {
            let mut cycle = addition_fixture();
            if missing_profile {
                cycle.addition_profile = None;
            } else {
                cycle.allowed.clear();
            }
            assert!(
                cycle
                    .execute(&[ADD, 3, 1, 198, 51, 100, 251])
                    .await
                    .is_err()
            );
            assert_eq!(cycle.console.add_reads, 0);
        }
        let mut cycle = addition_fixture();
        cycle.observed_entries = snapshot::MAX_ENTRIES;
        assert!(
            cycle
                .execute(&[ADD, 3, 1, 198, 51, 100, 251])
                .await
                .is_err()
        );
        assert_eq!(cycle.console.writes, 0);
        cycle.console.interfaces.insert("management".into());
        assert_eq!(
            cycle.execute(&[ADD, 3, 2, 198, 51, 100, 251]).await?.0,
            vec![vec![0, 3, ADD, 2, 0]]
        );
        for bad_ack in [false, true] {
            let mut cycle = addition_fixture();
            if bad_ack {
                cycle.console.ack_override = Some("unexpected success".into());
            } else {
                cycle.console.verify_override =
                    Some("shun (management) 198.51.100.251 0.0.0.0 0 443 6".into());
            }
            assert!(
                cycle
                    .execute(&[ADD, 3, 1, 198, 51, 100, 251])
                    .await
                    .is_err()
            );
            assert_eq!(cycle.console.add_calls, 1);
            assert_eq!(cycle.observed_entries, 0);
        }
        let mut cycle = addition_fixture();
        cycle.console.preflight_override = Some("\u{a0}".into());
        assert!(
            cycle
                .execute(&[ADD, 3, 1, 198, 51, 100, 251])
                .await
                .is_err()
        );
        assert_eq!(cycle.console.writes, 0);
        let mut cycle = addition_fixture();
        cycle.console.slow_verify = true;
        assert!(
            timeout(
                Duration::from_millis(20),
                cycle.execute(&[ADD, 3, 1, 198, 51, 100, 251])
            )
            .await
            .is_err()
        );
        assert_eq!(cycle.console.add_calls, 1);
        assert_eq!(cycle.observed_entries, 0);
        Ok(())
    }

    #[test]
    fn addition_gate_and_profile_reject_before_ssh() -> Result<()> {
        use nix::sys::socket::socketpair;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let mut agent = Agent {
            sessions: Arc::new(sessions::Sessions::default()),
            devices: BTreeMap::from([(
                1,
                Device {
                    management_ip: Ipv4Addr::LOCALHOST,
                    pinned_host_key: PublicKey::from_openssh(
                        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                    )?,
                    allowed_interfaces: BTreeSet::from(["management".into()]),
                    enabled: true,
                    addition_profile: None,
                },
            )]),
            credentials: credentials::Credentials::PerDevice(BTreeMap::new()),
            operation_timeout: Duration::from_secs(5),
            cycles_enabled: true,
            large_snapshots_enabled: true,
            additions_enabled: false,
            batch_additions_enabled: false,
            batch_session_version: 5,
            max_concurrent_devices: 1,
        };
        let (_sender, receiver) = socketpair(
            AddressFamily::Unix,
            SockType::SeqPacket,
            None,
            SockFlag::SOCK_CLOEXEC,
        )?;
        for enabled in [false, true] {
            agent.additions_enabled = enabled;
            for begin in [BEGIN, BEGIN_SETTLED] {
                let error = handle(&agent, &receiver, runtime.handle(), &[BEGIN, 3, 0, 1])
                    .err()
                    .context("ADD without gates/profile must be rejected")?
                    .to_string();
                assert!(error.contains(if enabled {
                    "no addition profile"
                } else {
                    "additions are disabled"
                }));
                let strict_error = handle(&agent, &receiver, runtime.handle(), &[begin, 3, 0, 1])
                    .err()
                    .context("strict ADD without gates/profile")?
                    .to_string();
                assert_eq!(strict_error, error);
            }
        }
        for (cycles, large, expected) in [
            (false, true, "session cycles"),
            (true, false, "large snapshots"),
        ] {
            agent.cycles_enabled = cycles;
            agent.large_snapshots_enabled = large;
            for begin in [BEGIN, BEGIN_SETTLED] {
                assert!(
                    handle(&agent, &receiver, runtime.handle(), &[begin, 3, 0, 1])
                        .err()
                        .context("disabled cycle capability must be rejected")?
                        .to_string()
                        .contains(expected)
                );
            }
        }
        assert!(serde_json::from_str::<addition::Profile>("\"unknown\"").is_err());
        assert!(serde_json::from_str::<addition::Profile>("false").is_err());
        Ok(())
    }

    #[test]
    fn frames_are_exact_versioned_and_ordered() -> Result<()> {
        assert_eq!(decode_begin(&[BEGIN, VERSION, 0, 7])?, (7, VERSION));
        for packet in [
            vec![],
            vec![BEGIN, VERSION, 0, 0],
            vec![BEGIN, 4, 0, 1],
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
    fn addition_requires_explicit_v3_and_remains_outside_legacy_rpc() -> Result<()> {
        assert_eq!(decode_begin(&[BEGIN, 3, 0, 1])?, (1, 3));
        for version in [VERSION, snapshot::VERSION] {
            let packet = [0x14, version, 1, 198, 51, 100, 251];
            assert!(decode_step(&packet, 1, version).is_err());
            assert!(decode_request(&packet).is_err());
        }
        assert!(decode_request(&[ADD, 3, 1, 198, 51, 100, 251]).is_err());
        Ok(())
    }

    #[test]
    fn oversize_seqpacket_and_disabled_cycle_are_rejected_before_ssh() -> Result<()> {
        use nix::sys::socket::socketpair;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let mut agent = Agent {
            sessions: Arc::new(sessions::Sessions::default()),
            devices: BTreeMap::new(),
            credentials: credentials::Credentials::PerDevice(BTreeMap::new()),
            operation_timeout: Duration::from_secs(45),
            cycles_enabled: false,
            large_snapshots_enabled: false,
            additions_enabled: false,
            batch_additions_enabled: false,
            batch_session_version: 5,
            max_concurrent_devices: 1,
        };
        let (sender, receiver) = socketpair(
            AddressFamily::Unix,
            SockType::SeqPacket,
            None,
            SockFlag::SOCK_CLOEXEC,
        )?;
        let guards = dispatch::DeviceGuards::new([]);
        set_ipc_timeout(&receiver, Duration::from_secs(1))?;
        let mut oversized = vec![0u8; 128];
        oversized[..4].copy_from_slice(&[BEGIN, VERSION, 0, 7]);
        send(sender.as_raw_fd(), &oversized, MsgFlags::MSG_NOSIGNAL)?;
        assert_eq!(
            handle_connection(&agent, &receiver, runtime.handle(), &guards),
            Reply::Packet(RESPONSE_REJECTED.to_vec())
        );
        send(
            sender.as_raw_fd(),
            &[BEGIN, VERSION, 0, 7],
            MsgFlags::MSG_NOSIGNAL,
        )?;
        assert_eq!(
            handle_connection(&agent, &receiver, runtime.handle(), &guards),
            Reply::Packet(RESPONSE_REJECTED.to_vec())
        );
        agent.cycles_enabled = true;
        let error = handle(&agent, &receiver, runtime.handle(), &[BEGIN, 2, 0, 7])
            .err()
            .context("v2 must be disabled")?;
        assert!(error.to_string().contains("large snapshots are disabled"));
        send(sender.as_raw_fd(), &[7, 0, 7], MsgFlags::MSG_NOSIGNAL)?;
        assert_eq!(
            handle_connection(&agent, &receiver, runtime.handle(), &guards),
            Reply::Packet(RESPONSE_REJECTED.to_vec())
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
