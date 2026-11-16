//! Canonical deployment-owned IPv4 protection. No CIDR expansion or CLI input.
use super::*;

pub(super) const VARIABLE: &str = "FTD_SHUN_ENV_PROTECTED_NETWORKS";

#[derive(Clone, Default)]
pub(super) struct Protection(Vec<(u32, u32)>);

impl Protection {
    pub(super) fn parse(value: &str) -> Result<Self> {
        if value.trim().is_empty() {
            return Ok(Self::default());
        }
        let parts: Vec<_> = value.split(',').collect();
        if parts.len() > 64 {
            bail!("{VARIABLE}: at most 64 IPv4 addresses or networks are allowed");
        }
        let mut ranges = Vec::new();
        for part in parts {
            let value = part.trim();
            let (address, prefix) = match value.split_once('/') {
                Some((address, bits)) => {
                    let prefix: u32 = bits.parse().context("invalid protected IPv4 prefix")?;
                    if prefix > 32 || prefix.to_string() != bits {
                        bail!("{VARIABLE}: noncanonical IPv4 prefix");
                    }
                    (address, prefix)
                }
                None => (value, 32),
            };
            let ip: Ipv4Addr = address.parse().context("invalid protected IPv4 address")?;
            let mask = u32::MAX.checked_shl(32 - prefix).unwrap_or(0);
            let network = u32::from(ip);
            if ip.to_string() != address || network & mask != network {
                bail!("{VARIABLE}: use exact IPv4 addresses or canonical IPv4 networks");
            }
            ranges.push((network, mask));
        }
        Ok(Self(ranges))
    }

    pub(super) fn from_environment() -> Result<Self> {
        match env::var(VARIABLE) {
            Ok(value) => Self::parse(&value),
            Err(env::VarError::NotPresent) => Ok(Self::default()),
            Err(error) => Err(error).context("invalid environment protection encoding"),
        }
    }

    pub(super) fn require_add(&self, ip: Ipv4Addr) -> Result<()> {
        if self
            .0
            .iter()
            .any(|(network, mask)| u32::from(ip) & mask == *network)
        {
            bail!(
                "ADD excluded by {VARIABLE}; change deployment .env protection to permit this address"
            );
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn protected_cidrs_and_exact_addresses_never_allow_add() -> Result<()> {
        let policy = Protection::parse("10.0.0.0/8,192.168.0.0/16,198.51.100.251")?;
        for target in [
            "10.0.0.0",
            "10.255.255.255",
            "192.168.1.1",
            "198.51.100.251",
        ] {
            assert!(policy.require_add(target.parse()?).is_err());
        }
        for target in ["11.0.0.0", "192.169.0.0", "198.51.100.250"] {
            policy.require_add(target.parse()?)?;
        }
        assert!(
            Protection::parse("0.0.0.0/0")?
                .require_add(Ipv4Addr::BROADCAST)
                .is_err()
        );
        Protection::parse("")?.require_add(Ipv4Addr::LOCALHOST)?;
        Ok(())
    }

    #[test]
    fn malformed_configuration_is_rejected() {
        for text in [
            "10.0.0.1/8",
            "10/8",
            "::1",
            "10.0.0.0/08",
            "10.0.0.0/33",
            "10.0.0.0/8,",
            "010.0.0.1",
        ] {
            assert!(Protection::parse(text).is_err(), "{text}");
        }
        assert!(Protection::parse(&vec!["10.0.0.0/8"; 65].join(",")).is_err());
    }
}
