//! Narrow creation profile and strict ADD evidence. No client-supplied CLI/scope.

use super::*;

pub(super) const VERSION: u8 = 3;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
pub(super) enum Profile {
    #[serde(rename = "fpr1010-766-single-vf-management-v1")]
    Fpr1010Management,
}

impl Profile {
    pub(super) fn interface(self) -> &'static str {
        match self {
            Self::Fpr1010Management => "management",
        }
    }

    fn context(self) -> &'static str {
        match self {
            Self::Fpr1010Management => "single_vf",
        }
    }

    pub(super) fn validate(self, allowed: &BTreeSet<String>) -> Result<()> {
        if !allowed.contains(self.interface()) {
            bail!("addition profile interface must be explicitly allowlisted");
        }
        Ok(())
    }
}

pub(super) fn validate_text(output: &str) -> Result<()> {
    if output.len() > MAX_CISCO_OUTPUT_BYTES
        || !output
            .bytes()
            .all(|byte| byte.is_ascii_graphic() || matches!(byte, b' ' | b'\t' | b'\r' | b'\n'))
    {
        bail!("addition evidence is oversized or contains unsupported characters");
    }
    Ok(())
}

pub(super) fn acknowledgement(output: &str, target: Ipv4Addr, profile: Profile) -> Result<()> {
    validate_text(output)?;
    let lines: Vec<_> = output
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .collect();
    let expected = [
        format!("Shun {target} added in context: {}", profile.context()),
        format!("Shun {target} successful"),
    ];
    if lines != expected {
        bail!("addition acknowledgement does not match the configured profile");
    }
    Ok(())
}

pub(super) fn already_present(
    output: &str,
    target: Ipv4Addr,
    allowed: &BTreeSet<String>,
) -> Result<bool> {
    validate_text(output)?;
    Ok(!parse_show_shun(output, target, allowed)?.is_empty())
}

pub(super) fn verify_creation(
    output: &str,
    target: Ipv4Addr,
    allowed: &BTreeSet<String>,
    profile: Profile,
) -> Result<()> {
    profile.validate(allowed)?;
    validate_text(output)?;
    let interfaces = parse_show_shun(output, target, allowed)?;
    if interfaces != BTreeSet::from([profile.interface().to_owned()]) {
        bail!("addition verification did not observe exactly the expected scope");
    }
    let expected = format!("shun ({}) {target} 0.0.0.0 0 0 0", profile.interface());
    if output.split_ascii_whitespace().collect::<Vec<_>>()
        != expected.split_ascii_whitespace().collect::<Vec<_>>()
    {
        bail!("addition verification did not match source-only shun fields");
    }
    Ok(())
}
