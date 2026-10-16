//! Offline ADD evidence model. No RPC, SSH implementation or command sender.
//!
//! The evidence model is test-only; strict parsers are shared with gated ADD.
//! Acknowledgement alone must never establish a verified creation.

use super::*;

const EXPECTED_INTERFACE: &str = "management";

#[derive(Debug, Eq, PartialEq)]
enum Assessment {
    AlreadyPresent,
    VerifiedCreation { interface: &'static str },
}

fn validate_text(output: &str) -> Result<()> {
    addition::validate_text(output)
}

fn acknowledgement(output: &str, target: Ipv4Addr) -> Result<()> {
    addition::acknowledgement(output, target, addition::Profile::Fpr1010Management)
}

fn verify_creation(output: &str, target: Ipv4Addr, allowed: &BTreeSet<String>) -> Result<()> {
    addition::verify_creation(
        output,
        target,
        allowed,
        addition::Profile::Fpr1010Management,
    )
}

fn assess(
    target: Ipv4Addr,
    allowed: &BTreeSet<String>,
    before: &str,
    ack: Option<&str>,
    after: Option<&str>,
) -> Result<Assessment> {
    validate_text(before)?;
    if !parse_show_shun(before, target, allowed)?.is_empty() {
        if ack.is_some() || after.is_some() {
            bail!("a pre-existing shun must not be written or relabelled as imported");
        }
        return Ok(Assessment::AlreadyPresent);
    }
    acknowledgement(ack.context("addition acknowledgement is missing")?, target)?;
    verify_creation(
        after.context("post-add target verification is missing")?,
        target,
        allowed,
    )?;
    Ok(Assessment::VerifiedCreation {
        interface: EXPECTED_INTERFACE,
    })
}

fn target() -> Ipv4Addr {
    Ipv4Addr::new(198, 51, 100, 251)
}

fn allowed() -> BTreeSet<String> {
    BTreeSet::from(["management".to_owned(), "outside".to_owned()])
}

const ACK: &str = concat!(
    "Shun 198.51.100.251 added in context: single_vf\n",
    "Shun 198.51.100.251 successful\n"
);
const OBSERVED: &str = "shun (management) 198.51.100.251 0.0.0.0 0 0 0\n";

#[test]
fn recorded_duplicate_success_cannot_establish_new_creation_or_ownership() -> Result<()> {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/addition-fpr1010-766-duplicate.json"
    ))?;
    let ip = fixture["target"]
        .as_str()
        .context("fixture target is missing")?
        .parse::<Ipv4Addr>()?;
    let steps = fixture["steps"]
        .as_array()
        .context("fixture steps missing")?;
    assert_eq!(steps.len(), 7);
    let output = |index: usize| -> Result<&str> {
        steps[index]["output"]
            .as_str()
            .context("fixture output missing")
    };
    let show = format!("show shun {ip}");
    let add = format!("shun {ip}");
    let remove = format!("no shun {ip} interface management");
    for (step, expected) in steps
        .iter()
        .zip([&show, &add, &show, &add, &show, &remove, &show])
    {
        assert_eq!(step["command"].as_str(), Some(expected.as_str()));
    }
    assert_eq!(output(0)?, "");
    assert_eq!(output(1)?, output(3)?);
    assert_eq!(output(2)?, output(4)?);
    // The device acknowledges both writes identically. Grammar is not creation
    // evidence: the service must branch to no-op BEFORE sending a duplicate.
    acknowledgement(output(1)?, ip)?;
    acknowledgement(output(3)?, ip)?;
    assert_eq!(
        assess(
            ip,
            &allowed(),
            output(0)?,
            Some(output(1)?),
            Some(output(2)?)
        )?,
        Assessment::VerifiedCreation {
            interface: "management"
        }
    );
    assert_eq!(
        assess(ip, &allowed(), output(2)?, None, None)?,
        Assessment::AlreadyPresent
    );
    assert!(
        assess(
            ip,
            &allowed(),
            output(2)?,
            Some(output(3)?),
            Some(output(4)?)
        )
        .is_err()
    );
    assert_eq!(output(5)?, "");
    assert!(parse_show_shun(output(6)?, ip, &allowed())?.is_empty());
    Ok(())
}

#[test]
fn recorded_creation_requires_both_ack_and_source_only_verification() {
    for (ack, after) in [
        (ACK.to_owned(), OBSERVED.to_owned()),
        (ACK.replace('\n', "\r\n"), OBSERVED.replace('\n', "\r\n")),
        (format!("\n{ACK}\n"), format!("\n{OBSERVED}\n")),
    ] {
        assert_eq!(
            assess(target(), &allowed(), "", Some(&ack), Some(&after)).unwrap(),
            Assessment::VerifiedCreation {
                interface: "management"
            }
        );
    }
}

#[test]
fn preexisting_target_is_noop_without_write_or_import_ownership() {
    for before in [
        OBSERVED.to_owned(),
        OBSERVED.replace("management", "outside"),
        OBSERVED.replace("0.0.0.0 0 0 0", "192.0.2.1 123 443 6"),
        format!("{OBSERVED}{}", OBSERVED.replace("management", "outside")),
    ] {
        assert_eq!(
            assess(target(), &allowed(), &before, None, None).unwrap(),
            Assessment::AlreadyPresent
        );
        assert!(assess(target(), &allowed(), &before, Some(ACK), Some(OBSERVED)).is_err());
    }
}

#[test]
fn unknown_or_malformed_preflight_never_becomes_absence() {
    for before in [
        "ERROR: not authorized".to_owned(),
        OBSERVED.replace("management", "unapproved"),
        OBSERVED.replace("198.51.100.251", "198.51.100.252"),
        format!("{OBSERVED}{OBSERVED}"),
        "\u{00a0}".to_owned(),
        "\0".to_owned(),
        "\n".repeat(MAX_CISCO_OUTPUT_BYTES + 1),
    ] {
        assert!(assess(target(), &allowed(), &before, Some(ACK), Some(OBSERVED)).is_err());
    }
}

#[test]
fn no_acknowledgement_or_visible_presence_alone_can_verify_creation() {
    for (ack, after) in [(None, None), (Some(ACK), None), (None, Some(OBSERVED))] {
        assert!(assess(target(), &allowed(), "", ack, after).is_err());
    }
}

#[test]
fn acknowledgement_is_exact_order_target_context_and_fixed_wording() {
    let cases = [
        "".to_owned(),
        "Shun 198.51.100.251 successful".to_owned(),
        ACK.replace("198.51.100.251", "198.51.100.252"),
        ACK.replacen("198.51.100.251", "198.51.100.252", 1),
        ACK.replace("single_vf", "other_context"),
        ACK.replace("successful", "unsuccessful"),
        ACK.replace("Shun", "shun"),
        ACK.lines().rev().collect::<Vec<_>>().join("\n"),
        format!("{ACK}{ACK}"),
        format!("Warning: ignored\n{ACK}"),
        format!("{ACK}ERROR: failed\n"),
        format!("shun 198.51.100.251\n{ACK}"),
        format!("{ACK}> "),
        format!("\x1b[0m{ACK}"),
        ACK.replace(' ', "\u{00a0}"),
        format!("{ACK}\0"),
        "x".repeat(MAX_CISCO_OUTPUT_BYTES + 1),
    ];
    for ack in cases {
        assert!(assess(target(), &allowed(), "", Some(&ack), Some(OBSERVED)).is_err());
    }
}

#[test]
fn post_write_verification_cannot_infer_scope_or_ignore_source_only_fields() {
    let cases = [
        "".to_owned(),
        OBSERVED.replace("management", "outside"),
        OBSERVED.replace("management", "unapproved"),
        OBSERVED.replace("198.51.100.251", "198.51.100.252"),
        OBSERVED.replace("0.0.0.0 0 0 0", "192.0.2.1 0 0 0"),
        OBSERVED.replace("0.0.0.0 0 0 0", "0.0.0.0 1 0 0"),
        OBSERVED.replace("0.0.0.0 0 0 0", "0.0.0.0 0 1 0"),
        OBSERVED.replace("0.0.0.0 0 0 0", "0.0.0.0 0 0 6"),
        OBSERVED.replace("0.0.0.0 0 0 0", "0.0.0.0 00 0 0"),
        format!("{OBSERVED}{}", OBSERVED.replace("management", "outside")),
        format!("{OBSERVED}{OBSERVED}"),
        format!("{OBSERVED}Warning: partial output"),
        format!("{OBSERVED}\0"),
        OBSERVED.replace(' ', "\u{00a0}"),
        "\n".repeat(MAX_CISCO_OUTPUT_BYTES + 1),
    ];
    for after in cases {
        assert!(assess(target(), &allowed(), "", Some(ACK), Some(&after)).is_err());
    }
    assert!(
        assess(
            target(),
            &BTreeSet::from(["outside".to_owned()]),
            "",
            Some(ACK),
            Some(OBSERVED),
        )
        .is_err()
    );
}
