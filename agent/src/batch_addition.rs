//! Acknowledged writes are pending until one complete, strict group observation.

use super::*;

pub(super) const VERSION: u8 = 4;
pub(super) const STAGE: u8 = 0x1a;
pub(super) const VERIFY: u8 = 0x1b;
pub(super) const MAX_PENDING: usize = 8;
pub(super) const MAX_SEQUENCE: u8 = 34;

pub(super) fn verify(
    output: &str,
    targets: &[Ipv4Addr],
    allowed: &BTreeSet<String>,
    profile: addition::Profile,
) -> Result<BTreeSet<ObservedShun>> {
    if output.len() > snapshot::MAX_OUTPUT_BYTES
        || !output
            .bytes()
            .all(|byte| byte.is_ascii_graphic() || matches!(byte, b' ' | b'\t' | b'\r' | b'\n'))
    {
        bail!("batch verification output exceeds its bound or contains unsupported characters");
    }
    if targets.is_empty()
        || targets.len() > MAX_PENDING
        || targets.iter().collect::<BTreeSet<_>>().len() != targets.len()
    {
        bail!("invalid pending addition scope");
    }
    profile.validate(allowed)?;
    // Parse the WHOLE bounded output first; unrelated malformed lines are fatal.
    // Preserve raw qualifiers: ObservedShun intentionally contains only IP/interface.
    let entries = parse_show_shun_entries(output, allowed)?;
    let targets: BTreeSet<_> = targets.iter().copied().collect();
    let mut verified = BTreeSet::new();
    for line in output.lines().filter(|line| !line.trim().is_empty()) {
        let fields: Vec<_> = line.split_ascii_whitespace().collect();
        let ip: Ipv4Addr = fields.get(2).context("missing source address")?.parse()?;
        if targets.contains(&ip) {
            addition::verify_creation(line, ip, allowed, profile)?;
            if !verified.insert(ip) {
                bail!("batch verification observed duplicate target scope");
            }
        }
    }
    if verified != targets {
        bail!("batch verification did not observe every pending target");
    }
    Ok(entries)
}

pub(super) fn receipt(targets: &[Ipv4Addr], profile: addition::Profile, sequence: u8) -> Vec<u8> {
    let mut packet = vec![0, VERSION, VERIFY, sequence, targets.len() as u8];
    for target in targets {
        packet.extend(target.octets());
        packet.push(profile.interface().len() as u8);
        packet.extend(profile.interface().as_bytes());
    }
    packet
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn whole_snapshot_verifies_only_exact_pending_source_only_rows() -> Result<()> {
        let profile = addition::Profile::Fpr1010Management;
        let allowed = BTreeSet::from(["management".into(), "outside".into()]);
        let first = Ipv4Addr::new(198, 51, 100, 251);
        let second = Ipv4Addr::new(198, 51, 100, 252);
        let row = |ip| format!("shun (management) {ip} 0.0.0.0 0 0 0\n");
        let valid = format!(
            "{}{}shun (outside) 192.0.2.9 192.0.2.10 123 443 6\n",
            row(first),
            row(second)
        );
        assert_eq!(
            verify(&valid, &[first, second], &allowed, profile)?.len(),
            3
        );
        for output in [
            row(first),
            format!("{valid}{}", row(first)),
            valid.replace("(management)", "(outside)"),
            valid.replace("0.0.0.0 0 0 0", "192.0.2.1 0 0 0"),
            valid.replace("0.0.0.0 0 0 0", "0.0.0.0 123 443 6"),
            format!("{valid}unexpected output\n"),
            format!("{valid}shun (unknown) 192.0.2.20 0.0.0.0 0 0 0\n"),
        ] {
            assert!(verify(&output, &[first, second], &allowed, profile).is_err());
        }
        for targets in [vec![], vec![first, first], vec![first; MAX_PENDING + 1]] {
            assert!(verify(&valid, &targets, &allowed, profile).is_err());
        }
        Ok(())
    }

    #[test]
    fn large_full_output_does_not_use_small_target_output_limit() -> Result<()> {
        let mut output = String::from("shun (management) 198.51.100.251 0.0.0.0 0 0 0\n");
        for n in 0..3000u32 {
            output.push_str(&format!(
                "shun (management) {} 0.0.0.0 0 0 0\n",
                Ipv4Addr::from(0xc6120000 + n)
            ));
        }
        assert!(output.len() > MAX_CISCO_OUTPUT_BYTES);
        assert_eq!(
            verify(
                &output,
                &[Ipv4Addr::new(198, 51, 100, 251)],
                &BTreeSet::from(["management".into()]),
                addition::Profile::Fpr1010Management
            )?
            .len(),
            3001
        );
        Ok(())
    }
}
