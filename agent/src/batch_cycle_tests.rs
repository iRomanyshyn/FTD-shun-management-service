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
        Some(unhex(&vectors["settled"])?.try_into().unwrap())
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
    let agent = Agent {
        sessions: Arc::new(sessions::Sessions::default()),
        devices: BTreeMap::new(),
        credentials: credentials::Credentials::PerDevice(BTreeMap::new()),
        operation_timeout: Duration::from_secs(45),
        cycles_enabled: true,
        large_snapshots_enabled: true,
        additions_enabled: true,
        batch_additions_enabled: false,
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
    .expect_err("disabled batch mode");
    assert!(error.to_string().contains("batch additions are disabled"));
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
