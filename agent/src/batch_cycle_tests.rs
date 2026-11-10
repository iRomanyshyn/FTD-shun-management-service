//! Synthetic console coverage; never reaches a live device.

use super::*;

#[derive(Default)]
struct Fake {
    rows: BTreeMap<Ipv4Addr, String>,
    calls: Vec<&'static str>,
    fail_ack: bool,
    fail_verification: bool,
}

impl Fake {
    fn output(&self) -> String {
        self.rows.values().cloned().collect()
    }
}

impl Console for Fake {
    async fn snapshot(&mut self, allowed: &BTreeSet<String>) -> Result<BTreeSet<ObservedShun>> {
        self.calls.push("snapshot");
        parse_show_shun_entries(&self.output(), allowed)
    }
    async fn target(&mut self, _: Ipv4Addr, _: &BTreeSet<String>) -> Result<BTreeSet<String>> {
        bail!("unexpected target operation")
    }
    async fn remove(&mut self, _: Ipv4Addr, _: &str) -> Result<()> {
        bail!("unexpected removal")
    }
    async fn addition_present(&mut self, ip: Ipv4Addr, allowed: &BTreeSet<String>) -> Result<bool> {
        self.calls.push("preflight");
        addition::already_present(
            self.rows.get(&ip).map(String::as_str).unwrap_or(""),
            ip,
            allowed,
        )
    }
    async fn add(&mut self, ip: Ipv4Addr, profile: addition::Profile) -> Result<()> {
        self.calls.push("add");
        self.rows
            .insert(ip, format!("shun (management) {ip} 0.0.0.0 0 0 0\n"));
        if self.fail_ack {
            bail!("synthetic lost acknowledgement after write");
        }
        addition::acknowledgement(
            &format!("Shun {ip} added in context: single_vf\nShun {ip} successful"),
            ip,
            profile,
        )
    }
    async fn verify_adds(
        &mut self,
        targets: &[Ipv4Addr],
        allowed: &BTreeSet<String>,
        profile: addition::Profile,
    ) -> Result<BTreeSet<ObservedShun>> {
        self.calls.push("verify_group");
        if self.fail_verification {
            bail!("synthetic verification failure");
        }
        batch_addition::verify(&self.output(), targets, allowed, profile)
    }
}

fn fixture() -> Cycle<Fake> {
    Cycle {
        console: Fake::default(),
        allowed: BTreeSet::from(["management".into()]),
        started: Instant::now(),
        timeout: Duration::from_secs(45),
        commands: 1,
        removals: 0,
        additions: 0,
        pending_additions: Vec::new(),
        addition_profile: Some(addition::Profile::Fpr1010Management),
        observed_entries: 0,
        priority_used: false,
        sequence: 1,
        version: 4,
    }
}

#[tokio::test]
async fn v7_pending_end_is_terminal_without_verification_or_an_extra_cisco_command() -> Result<()> {
    let vectors: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/fixtures/pending-end-v7.json"))?;
    assert_eq!(decode_begin(&unhex(&vectors["begin"])?)?, (7, 7));
    let mut cycle = fixture();
    cycle.version = 7;
    assert_eq!(cycle.max_duration().as_secs(), vectors["duration_seconds"]);
    assert_eq!(cycle.max_mutations(), 64);
    assert_eq!(cycle.max_commands(), 256);
    assert_eq!(
        cycle.execute(&unhex(&vectors["stage_first"])?).await?.0[0],
        unhex(&vectors["ack_first"])?
    );
    cycle.console.rows.insert(
        target(253),
        "shun (management) 198.51.100.253 0.0.0.0 0 0 0\n".into(),
    );
    assert_eq!(
        cycle
            .execute(&[batch_addition::STAGE, 7, 2, 198, 51, 100, 253])
            .await?
            .0[0],
        [0, 7, batch_addition::STAGE, 2, 0]
    );
    assert_eq!(
        cycle.execute(&unhex(&vectors["stage_second"])?).await?.0[0],
        unhex(&vectors["ack_second"])?
    );
    let calls = cycle.console.calls.clone();
    let commands = cycle.commands;
    let (frames, done) = cycle.execute(&unhex(&vectors["end_pending"])?).await?;
    assert!(done);
    assert_eq!(frames, vec![unhex(&vectors["receipt"])?]);
    assert_eq!(cycle.console.calls, calls);
    assert_eq!(cycle.commands, commands);
    // Retain unconfirmed scope until resource drop; no verification occurred.
    assert_eq!(cycle.pending_additions, [target(251), target(252)]);
    assert!(!calls.contains(&"verify_group"));
    assert_eq!(
        after_cleanup(sessions::BEGIN, 7, 4, Ok(()))?
            .context("terminal")?
            .to_vec(),
        unhex(&vectors["settled"])?
    );
    assert!(after_cleanup(sessions::BEGIN, 7, 4, Err(anyhow::anyhow!("lost cleanup"))).is_err());
    Ok(())
}

#[tokio::test]
async fn v7_never_lets_plain_end_snapshot_or_remove_overtake_pending_acknowledgements() -> Result<()>
{
    let mut cycle = fixture();
    cycle.version = 7;
    cycle
        .execute(&[batch_addition::STAGE, 7, 1, 198, 51, 100, 251])
        .await?;
    let calls = cycle.console.calls.clone();
    for packet in [
        vec![END, 7, 2],
        vec![SNAPSHOT, 7, 2],
        vec![REMOVE, 7, 2, 198, 51, 100, 251],
    ] {
        assert!(cycle.execute(&packet).await.is_err());
        assert_eq!(cycle.sequence, 2);
        assert_eq!(cycle.console.calls, calls);
    }
    for version in 1..=6 {
        assert!(decode_step(&[batch_addition::END_PENDING, version, 2], 2, version).is_err());
    }
    assert!(
        snapshot::encode_versioned(BTreeSet::new(), batch_addition::END_PENDING, 2, 7).is_err()
    );
    Ok(())
}

#[test]
fn v7_pending_header_rejects_empty_duplicate_oversized_or_foreign_scope() {
    for targets in [
        vec![],
        vec![target(251), target(251)],
        vec![target(251); 17],
    ] {
        assert!(batch_addition::pending_end(&targets, 2, 7).is_err());
    }
    for (version, sequence) in [(6, 2), (8, 2), (7, 0), (7, 131)] {
        assert!(batch_addition::pending_end(&[target(251)], sequence, version).is_err());
    }
}

#[test]
fn configured_agent_refuses_v7_before_inventory_or_ssh_and_mutation_lookup_never_becomes_safe()
-> Result<()> {
    use nix::sys::socket::socketpair;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let (_peer, connection) = socketpair(
        AddressFamily::Unix,
        SockType::SeqPacket,
        None,
        SockFlag::SOCK_CLOEXEC,
    )?;
    let vectors: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/fixtures/pending-end-v7.json"))?;
    let mut agent = Agent {
        sessions: Arc::new(sessions::Sessions::default()),
        devices: BTreeMap::new(),
        credentials: credentials::Credentials::PerDevice(BTreeMap::new()),
        operation_timeout: Duration::from_secs(45),
        cycles_enabled: true,
        large_snapshots_enabled: true,
        additions_enabled: true,
        batch_additions_enabled: true,
        batch_session_version: 5,
        max_concurrent_devices: 1,
    };
    for configured in [5, 6] {
        agent.batch_session_version = configured;
        let error = handle(
            &agent,
            &connection,
            runtime.handle(),
            &unhex(&vectors["begin"])?,
        )
        .err()
        .context("v7 must not enter configured execution")?;
        assert!(
            error
                .to_string()
                .contains("session version is not explicitly enabled")
        );
    }
    let key = sessions::decode(&unhex(&vectors["begin"])?, sessions::BEGIN)?;
    agent.sessions.reserve(key)?;
    assert_eq!(agent.sessions.lookup(key)?[0], 2);
    agent.sessions.complete(key)?; // No prepare_read_only for a mutation session.
    assert_eq!(agent.sessions.lookup(key)?[0], 1);
    assert!(
        finish_result(
            sessions::BEGIN,
            7,
            Err(anyhow::anyhow!("lost pending end")),
            Ok(()),
            Some((END, 4)),
            2
        )
        .is_err()
    );
    Ok(())
}

#[tokio::test]
async fn v6_runs_four_bounded_groups_on_one_console_and_retains_exact_limits() -> Result<()> {
    let vectors: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/fixtures/batch-addition-v6.json"))?;
    assert_eq!(decode_begin(&unhex(&vectors["begin"])?)?, (7, 6));
    assert_eq!(
        decode_step(&unhex(&vectors["last_end"])?, 130, 6)?,
        Step::End
    );
    let mut cycle = fixture();
    cycle.version = 6;
    assert_eq!(cycle.max_duration(), Duration::from_secs(240));
    assert_eq!(cycle.max_duration().as_secs(), vectors["duration_seconds"]);
    assert_eq!(cycle.max_commands(), 256);
    assert_eq!(cycle.max_mutations(), 64);
    for n in 1..=64 {
        let seq = cycle.sequence;
        let mut packet = stage(seq, n);
        packet[1] = 6;
        assert_eq!(
            cycle.execute(&packet).await?.0[0],
            [5, 6, batch_addition::STAGE, seq]
        );
        if n % 16 == 0 {
            let final_group = n == 64;
            let opcode = if final_group {
                batch_addition::VERIFY_END
            } else {
                batch_addition::VERIFY
            };
            let seq = cycle.sequence;
            let (frames, done) = cycle.execute(&[opcode, 6, seq]).await?;
            assert_eq!(done, final_group);
            assert_eq!(&frames[0][..5], &[0, 6, opcode, seq, 16]);
            assert!(cycle.pending_additions.is_empty());
        }
    }
    assert_eq!(cycle.observed_entries, 64);
    assert_eq!(cycle.commands, 133); // initial + 64 immediate preflights/ADDs + four reads
    assert_eq!(
        cycle
            .console
            .calls
            .iter()
            .filter(|call| **call == "preflight")
            .count(),
        64
    );
    assert_eq!(
        cycle
            .console
            .calls
            .iter()
            .filter(|call| **call == "verify_group")
            .count(),
        4
    );
    assert_eq!(
        after_cleanup(sessions::BEGIN, 6, 68, Ok(()))?,
        Some([0, 6, sessions::BEGIN, 68])
    );
    let mut extra = stage(cycle.sequence, 65);
    extra[1] = 6;
    assert!(cycle.execute(&extra).await.is_err());
    assert_eq!(cycle.console.rows.len(), 64);
    assert_eq!(decode_step(&[END, 6, 130], 130, 6)?, Step::End);
    assert!(decode_step(&[END, 6, 131], 131, 6).is_err());
    assert!(decode_step(&[END, 8, 1], 1, 8).is_err());
    assert!(decode_step(&[END, 5, 35], 35, 5).is_err());
    Ok(())
}

#[tokio::test]
async fn v6_reserves_time_commands_and_full_verification_capacity_before_writing() -> Result<()> {
    for budget in ["time", "commands", "pending"] {
        let mut cycle = fixture();
        cycle.version = 6;
        if budget == "time" {
            cycle.started = Instant::now() - Duration::from_secs(200);
        }
        if budget == "commands" {
            cycle.commands = 253;
        }
        if budget == "pending" {
            cycle.pending_additions = (1..=16).map(target).collect();
        }
        let mut packet = stage(1, 251);
        packet[1] = 6;
        assert_eq!(
            cycle.execute(&packet).await?.0[0],
            [2, 6, batch_addition::STAGE, 1]
        );
        assert!(cycle.console.calls.is_empty());
    }
    let mut cycle = fixture();
    cycle.version = 6;
    cycle.started = Instant::now() - Duration::from_secs(160);
    let mut packet = stage(1, 251);
    packet[1] = 6;
    assert_eq!(
        cycle.execute(&packet).await?.0[0],
        [5, 6, batch_addition::STAGE, 1]
    );
    cycle.console.fail_verification = true;
    assert!(
        cycle
            .execute(&[batch_addition::VERIFY_END, 6, 2])
            .await
            .is_err()
    );
    assert_eq!(cycle.pending_additions, vec![target(251)]);
    Ok(())
}

#[test]
fn v5_local_processing_wait_never_extends_transfer_or_session_bounds() -> Result<()> {
    use nix::sys::socket::{getsockopt, socketpair};
    let (_client, server) = socketpair(
        AddressFamily::Unix,
        SockType::SeqPacket,
        None,
        SockFlag::SOCK_CLOEXEC,
    )?;
    for (version, remaining, expected) in [(4, 90, 10), (5, 90, 30), (5, 7, 7)] {
        set_cycle_ipc_timeout(&server, Duration::from_secs(remaining), version)?;
        assert_eq!(
            getsockopt(&server, ReceiveTimeout)?,
            TimeVal::new(expected, 0)
        );
        assert_eq!(
            getsockopt(&server, SendTimeout)?,
            TimeVal::new(remaining.min(10) as i64, 0)
        );
    }
    Ok(())
}

#[tokio::test]
async fn sixteen_v5_additions_share_terminal_full_read_without_extra_end() -> Result<()> {
    let mut cycle = fixture();
    cycle.version = 5;
    for seq in 1..=16 {
        let mut packet = stage(seq, seq);
        packet[1] = 5;
        assert_eq!(
            cycle.execute(&packet).await?.0,
            vec![vec![5, 5, batch_addition::STAGE, seq]]
        );
    }
    let (frames, done) = cycle.execute(&[batch_addition::VERIFY_END, 5, 17]).await?;
    assert!(done);
    assert_eq!(&frames[0][..5], &[0, 5, batch_addition::VERIFY_END, 17, 16]);
    assert!(cycle.pending_additions.is_empty());
    assert_eq!(cycle.commands, 34); // initial + 16 preflights + 16 ADDs + final verification
    assert_eq!(
        cycle
            .console
            .calls
            .iter()
            .filter(|call| **call == "verify_group")
            .count(),
        1
    );
    assert!(!cycle.console.calls.contains(&"snapshot"));
    assert_eq!(
        after_cleanup(sessions::BEGIN, 5, 17, Ok(()))?,
        Some([0, 5, sessions::BEGIN, 17])
    );
    Ok(())
}

#[tokio::test]
async fn v5_shared_vectors_reserve_a_shorter_bounded_stage_and_retain_failed_evidence() -> Result<()>
{
    let vectors: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/fixtures/batch-addition-v5.json"))?;
    assert_eq!(decode_begin(&unhex(&vectors["begin"])?)?, (7, 5));
    assert!(decode_step(&[batch_addition::VERIFY_END, 4, 2], 2, 4).is_err());
    assert!(decode_step(&[batch_addition::VERIFY_END, 5, 2, 0], 2, 5).is_err());
    for failure in [false, true] {
        let mut cycle = fixture();
        cycle.version = 5;
        cycle.started = Instant::now() - Duration::from_secs(70);
        assert_eq!(cycle.stage_timeout(), Duration::from_secs(30));
        assert_eq!(
            cycle.execute(&unhex(&vectors["stage"])?).await?.0,
            vec![unhex(&vectors["pending"])?]
        );
        cycle.console.fail_verification = failure;
        let outcome = cycle.execute(&unhex(&vectors["final"])?).await;
        if failure {
            assert!(outcome.is_err());
            assert_eq!(cycle.pending_additions, vec![target(251)]);
        } else {
            let (frames, done) = outcome?;
            assert!(done);
            assert_eq!(frames[0], unhex(&vectors["receipt"])?);
            assert_eq!(
                after_cleanup(sessions::BEGIN, 5, 2, Ok(()))?,
                Some([0, 5, sessions::BEGIN, 2])
            );
            assert!(
                after_cleanup(
                    sessions::BEGIN,
                    5,
                    2,
                    Err(anyhow::anyhow!("failed disconnect"))
                )
                .is_err()
            );
        }
    }
    let mut cycle = fixture();
    cycle.version = 5;
    assert!(
        cycle
            .execute(&[batch_addition::VERIFY_END, 5, 1])
            .await
            .is_err()
    );
    assert!(cycle.console.calls.is_empty());
    Ok(())
}

fn target(n: u8) -> Ipv4Addr {
    Ipv4Addr::new(198, 51, 100, n)
}
fn stage(sequence: u8, n: u8) -> [u8; 7] {
    [batch_addition::STAGE, 4, sequence, 198, 51, 100, n]
}
fn verify(sequence: u8) -> [u8; 3] {
    [batch_addition::VERIFY, 4, sequence]
}
fn unhex(value: &serde_json::Value) -> Result<Vec<u8>> {
    value
        .as_str()
        .context("hex")?
        .as_bytes()
        .chunks(2)
        .map(|pair| Ok(u8::from_str_radix(std::str::from_utf8(pair)?, 16)?))
        .collect()
}

#[tokio::test]
async fn shared_wire_vectors_prove_pending_is_not_terminal_success() -> Result<()> {
    let vectors: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/fixtures/batch-addition-v4.json"))?;
    assert_eq!(decode_begin(&unhex(&vectors["begin"])?)?, (7, 4));
    let mut cycle = fixture();
    assert_eq!(
        cycle.execute(&unhex(&vectors["stage"])?).await?,
        (vec![unhex(&vectors["pending"])?], false)
    );
    assert_eq!(cycle.pending_additions, vec![target(251)]);
    assert_eq!(cycle.console.calls, vec!["preflight", "add"]);
    let (frames, done) = cycle.execute(&unhex(&vectors["verify"])?).await?;
    assert!(!done);
    assert_eq!(frames[0], unhex(&vectors["receipt"])?);
    assert_eq!(frames[1][..5], [0, 4, batch_addition::VERIFY, 2, 0]);
    assert_eq!(
        frames.last().context("completion")?[..5],
        [0, 4, batch_addition::VERIFY, 2, 2]
    );
    assert!(cycle.pending_additions.is_empty());
    assert!(cycle.execute(&unhex(&vectors["end"])?).await?.1);
    assert_eq!(
        after_cleanup(sessions::BEGIN, 4, 3, Ok(()))?,
        Some(
            unhex(&vectors["settled"])?
                .try_into()
                .map_err(|_| anyhow::anyhow!("invalid settled fixture length"))?
        )
    );
    assert_eq!(cycle.commands, 5); // initial + preflight + ADD + group + END
    Ok(())
}

#[tokio::test]
async fn eight_additions_share_one_full_verification_and_intermediate_group_may_flush() -> Result<()>
{
    let mut cycle = fixture();
    for n in 1..=8 {
        assert_eq!(
            cycle.execute(&stage(n, n)).await?.0,
            vec![vec![5, 4, batch_addition::STAGE, n]]
        );
    }
    assert_eq!(cycle.console.calls.len(), 16);
    assert_eq!(cycle.pending_additions.len(), 8);
    assert_eq!(
        cycle.execute(&stage(9, 9)).await?.0,
        vec![vec![2, 4, batch_addition::STAGE, 9]]
    );
    assert_eq!(cycle.console.calls.len(), 16); // no ninth command
    assert!(cycle.execute(&verify(10)).await.is_ok());
    assert_eq!(
        cycle
            .console
            .calls
            .iter()
            .filter(|call| **call == "verify_group")
            .count(),
        1
    );
    assert_eq!(cycle.observed_entries, 8);
    assert_eq!(cycle.commands, 18); // initial + 16 CLI + shared verification
    cycle.execute(&[SNAPSHOT, 4, 11]).await?;
    cycle.execute(&stage(12, 12)).await?;
    cycle.execute(&verify(13)).await?; // one-address partial group
    assert!(cycle.execute(&[END, 4, 14]).await?.1);
    Ok(())
}

#[tokio::test]
async fn pending_scope_cannot_be_closed_read_removed_or_duplicated() -> Result<()> {
    for packet in [
        vec![END, 4, 2],
        vec![SNAPSHOT, 4, 2],
        vec![REMOVE, 4, 2, 198, 51, 100, 252],
        stage(2, 251).to_vec(),
    ] {
        let mut cycle = fixture();
        cycle.execute(&stage(1, 251)).await?;
        assert!(cycle.execute(&packet).await.is_err());
        assert_eq!(cycle.pending_additions, vec![target(251)]);
        assert_eq!(cycle.console.calls, vec!["preflight", "add"]);
    }
    let mut cycle = fixture();
    assert!(cycle.execute(&verify(1)).await.is_err());
    assert!(cycle.console.calls.is_empty());
    Ok(())
}

#[tokio::test]
async fn failed_ack_or_full_read_never_returns_creation_or_read_only_release() -> Result<()> {
    for ack in [false, true] {
        let mut cycle = fixture();
        cycle.console.fail_ack = ack;
        cycle.console.fail_verification = !ack;
        let result = cycle.execute(&stage(1, 251)).await;
        if ack {
            assert!(result.is_err());
        } else {
            result?;
            assert!(cycle.execute(&verify(2)).await.is_err());
            assert_eq!(cycle.pending_additions, vec![target(251)]);
        }
        assert!(
            finish_result(
                sessions::BEGIN,
                4,
                Err(anyhow::anyhow!("failure")),
                Ok(()),
                Some((END, 3)),
                cycle.additions
            )
            .is_err()
        );
    }
    Ok(())
}

#[tokio::test]
async fn noop_capacity_time_command_and_attempt_budgets_precede_writes() -> Result<()> {
    let mut cycle = fixture();
    cycle.console.rows.insert(
        target(251),
        "shun (management) 198.51.100.251 0.0.0.0 0 0 0\n".into(),
    );
    assert_eq!(
        cycle.execute(&stage(1, 251)).await?.0,
        vec![vec![0, 4, batch_addition::STAGE, 1, 0]]
    );
    assert!(cycle.pending_additions.is_empty());
    assert_eq!(cycle.console.calls, vec!["preflight"]);
    for exhausted in ["time", "commands", "entries", "attempts"] {
        let mut cycle = fixture();
        match exhausted {
            "time" => cycle.started = Instant::now() - Duration::from_secs(61),
            "commands" => cycle.commands = MAX_COMMANDS - 3,
            "entries" => cycle.observed_entries = snapshot::MAX_ENTRIES,
            _ => cycle.additions = MAX_REMOVALS,
        }
        let result = cycle.execute(&stage(1, 251)).await;
        if matches!(exhausted, "time" | "commands") {
            assert_eq!(result?.0, vec![vec![2, 4, batch_addition::STAGE, 1]]);
        } else {
            assert!(result.is_err());
        }
        assert!(!cycle.console.calls.contains(&"add"));
    }
    Ok(())
}

#[test]
fn extension_is_exact_and_old_frames_stay_old() -> Result<()> {
    assert!(decode_step(&stage(1, 251), 1, 3).is_err());
    assert!(decode_step(&[ADD, 4, 1, 198, 51, 100, 251], 1, 4).is_err());
    for mut packet in [stage(1, 251).to_vec(), verify(1).to_vec()] {
        packet.push(0);
        assert!(decode_step(&packet, 1, 4).is_err());
    }
    assert!(decode_step(&verify(2), 1, 4).is_err());
    assert!(decode_step(&[END, 4, 35], 35, 4).is_err());
    assert!(decode_step(&[END, 3, 19], 19, 3).is_err());
    assert_eq!(decode_step(&[END, 4, 34], 34, 4)?, Step::End);
    assert!(after_cleanup(sessions::BEGIN, 4, 34, Ok(()))?.is_some());
    assert!(after_cleanup(sessions::BEGIN, 4, 35, Ok(())).is_err());
    Ok(())
}

#[test]
fn batch_mode_is_rejected_before_inventory_lookup_or_ssh_when_gated() -> Result<()> {
    use nix::sys::socket::socketpair;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let mut agent = Agent {
        sessions: Arc::new(sessions::Sessions::default()),
        devices: BTreeMap::new(),
        credentials: credentials::Credentials::PerDevice(BTreeMap::new()),
        operation_timeout: Duration::from_secs(45),
        cycles_enabled: true,
        large_snapshots_enabled: true,
        additions_enabled: true,
        batch_additions_enabled: false,
        batch_session_version: 5,
        max_concurrent_devices: 1,
    };
    let (_client, server) = socketpair(
        AddressFamily::Unix,
        SockType::SeqPacket,
        None,
        SockFlag::SOCK_CLOEXEC,
    )?;
    let vectors: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/fixtures/batch-addition-v4.json"))?;
    let error = handle(
        &agent,
        &server,
        runtime.handle(),
        &unhex(&vectors["begin"])?,
    )
    .err()
    .context("disabled batch mode was unexpectedly accepted")?;
    assert!(error.to_string().contains("batch additions are disabled"));
    agent.batch_additions_enabled = true;
    let mut extended = unhex(&vectors["begin"])?;
    extended[1] = 6;
    let error = handle(&agent, &server, runtime.handle(), &extended)
        .err()
        .context("v6 must be explicitly selected")?;
    assert!(
        error
            .to_string()
            .contains("multi-group session version is not explicitly enabled")
    );
    assert!(
        finish_result(
            sessions::BEGIN,
            4,
            Err(anyhow::anyhow!("read failed")),
            Ok(()),
            Some((END, 1)),
            0
        )?
        .is_some()
    );
    assert!(
        finish_result(
            sessions::BEGIN,
            4,
            Err(anyhow::anyhow!("read failed")),
            Ok(()),
            Some((END, 1)),
            1
        )
        .is_err()
    );
    Ok(())
}
