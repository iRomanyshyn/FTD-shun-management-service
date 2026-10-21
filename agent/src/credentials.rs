//! Operator-owned credentials; never decoded from the API/agent wire protocol.

use super::*;

const SECRET_ROOT: &str = "/run/secrets/ftd";
const MAX_MAPPING_BYTES: u64 = 256 * 1024;

#[derive(Clone)]
pub(super) struct Credential {
    pub(super) username: String,
    pub(super) password_file: PathBuf,
}

#[derive(Clone)]
pub(super) enum Credentials {
    Shared(Credential),
    PerDevice(BTreeMap<u16, Credential>),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Entry {
    device_id: u16,
    username: String,
    password_secret: String,
}

impl Credentials {
    pub(super) fn mode(&self) -> &'static str {
        match self {
            Self::Shared(_) => "shared",
            Self::PerDevice(_) => "per-device",
        }
    }

    pub(super) fn from_environment(devices: &BTreeSet<u16>) -> Result<Self> {
        let mode = match env::var("FTD_SHUN_SSH_CREDENTIALS_MODE") {
            Ok(value) => value,
            Err(env::VarError::NotPresent) => "shared".into(),
            Err(_) => bail!("FTD_SHUN_SSH_CREDENTIALS_MODE is invalid"),
        };
        match mode.as_str() {
            "shared" => Ok(Self::Shared(Credential {
                username: required_env("FTD_SHUN_SSH_USERNAME")?,
                password_file: required_env_path("FTD_SHUN_SSH_PASSWORD_FILE")?,
            })),
            "per-device" => {
                use std::io::Read;
                let path = required_env_path("FTD_SHUN_SSH_CREDENTIALS_FILE")?;
                // Bound allocation even if an operator supplies a large mapping.
                let mut raw = Vec::new();
                fs::File::open(path)
                    .context("could not open agent credential mapping")?
                    .take(MAX_MAPPING_BYTES + 1)
                    .read_to_end(&mut raw)
                    .context("could not read agent credential mapping")?;
                Self::from_json(&raw, devices)
            }
            _ => bail!("FTD_SHUN_SSH_CREDENTIALS_MODE must be shared or per-device"),
        }
    }

    fn from_json(raw: &[u8], devices: &BTreeSet<u16>) -> Result<Self> {
        if raw.len() as u64 > MAX_MAPPING_BYTES {
            bail!("agent credential mapping exceeds 256 KiB");
        }
        // Do not echo untrusted field names/values from a credential document.
        let entries: Vec<Entry> = serde_json::from_slice(raw)
            .map_err(|_| anyhow::anyhow!("agent credential mapping is not a strict JSON array"))?;
        let mut credentials = BTreeMap::new();
        let mut secrets = BTreeSet::new();
        for entry in entries {
            if entry.device_id == 0 || !devices.contains(&entry.device_id) {
                bail!("agent credential mapping has an unknown device ID");
            }
            if entry.username.is_empty()
                || entry.username.len() > 64
                || !entry.username.bytes().all(|byte| {
                    byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-' | b'.' | b'@')
                })
            {
                bail!("agent credential mapping has an invalid SSH login");
            }
            if !safe_secret_name(&entry.password_secret) {
                bail!("agent credential mapping has an invalid password-secret name");
            }
            if !secrets.insert(entry.password_secret.clone()) {
                bail!("each device requires its own password-secret reference");
            }
            if credentials
                .insert(
                    entry.device_id,
                    Credential {
                        username: entry.username,
                        password_file: Path::new(SECRET_ROOT).join(entry.password_secret),
                    },
                )
                .is_some()
            {
                bail!("agent credential mapping has duplicate device IDs");
            }
        }
        if credentials.keys().copied().collect::<BTreeSet<_>>() != *devices {
            bail!("every configured device requires explicit SSH credentials");
        }
        Ok(Self::PerDevice(credentials))
    }

    pub(super) fn for_device(&self, device_id: u16) -> Result<&Credential> {
        match self {
            Self::Shared(credential) => Ok(credential),
            Self::PerDevice(credentials) => credentials
                .get(&device_id)
                .context("no SSH credentials for the selected device"),
        }
    }
}

fn safe_secret_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 128
        && name.as_bytes()[0].is_ascii_alphanumeric()
        && name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-' | b'.'))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mapping() -> serde_json::Value {
        serde_json::json!([
            {"device_id": 1, "username": "basic-branch-a", "password_secret": "branch-a"},
            {"device_id": 2, "username": "basic-branch-b", "password_secret": "branch-b"}
        ])
    }

    fn parse(value: &serde_json::Value) -> Result<Credentials> {
        Credentials::from_json(&serde_json::to_vec(value)?, &BTreeSet::from([1, 2]))
    }

    #[test]
    fn exact_device_lookup_has_no_shared_or_neighbor_fallback() -> Result<()> {
        let credentials = parse(&mapping())?;
        for (id, login, name) in [
            (1, "basic-branch-a", "branch-a"),
            (2, "basic-branch-b", "branch-b"),
        ] {
            let credential = credentials.for_device(id)?;
            assert_eq!(credential.username, login);
            assert_eq!(credential.password_file, Path::new(SECRET_ROOT).join(name));
        }
        assert!(credentials.for_device(3).is_err());
        assert!(credentials.for_device(0).is_err());
        // Only stable IDs bind credentials; JSON row order is not identity.
        let mut reordered = mapping();
        reordered.as_array_mut().context("array")?.reverse();
        assert_eq!(parse(&reordered)?.for_device(1)?.username, "basic-branch-a");
        Ok(())
    }

    #[test]
    fn complete_mapping_rejects_missing_duplicate_and_unknown_devices() -> Result<()> {
        for id in [0, 1, 3] {
            let mut value = mapping();
            value[1]["device_id"] = id.into();
            assert!(parse(&value).is_err());
        }
        assert!(parse(&serde_json::json!([mapping()[0].clone()])).is_err());
        assert!(parse(&serde_json::json!([])).is_err());
        assert!(
            Credentials::from_json(&serde_json::to_vec(&mapping())?, &BTreeSet::from([1])).is_err()
        );
        Ok(())
    }

    #[test]
    fn logins_and_secret_references_are_bounded_literal_data() -> Result<()> {
        for login in [
            "",
            "has space",
            "line\nfeed",
            "nonasciié",
            "x;command",
            &"a".repeat(65),
        ] {
            let mut value = mapping();
            value[0]["username"] = login.into();
            assert!(parse(&value).is_err());
        }
        for name in [
            "",
            ".",
            "..",
            "../other",
            "/etc/passwd",
            "a/b",
            "a\\b",
            ".hidden",
            "secret\n",
            "é",
            &"a".repeat(129),
        ] {
            let mut value = mapping();
            value[0]["password_secret"] = name.into();
            assert!(parse(&value).is_err());
        }
        let mut value = mapping();
        value[1]["password_secret"] = value[0]["password_secret"].clone();
        assert!(parse(&value).is_err());
        value = mapping();
        value[0]["username"] = "basic.user@example".into();
        value[0]["password_secret"] = "branch-01.password_v2".into();
        assert!(parse(&value).is_ok());
        Ok(())
    }

    #[test]
    fn strict_json_errors_never_echo_credential_document_values() -> Result<()> {
        for raw in [
            br#"[{"device_id":1,"username":"x","password_secret":"a","sensitive-value":"x"}]"#.as_slice(),
            br#"[{"device_id":1,"device_id":2,"username":"sensitive-value","password_secret":"a"}]"#,
            br#"[{"device_id":true,"username":"sensitive-value","password_secret":"a"}]"#,
            br#"{"password":"sensitive-value"}"#,
            br#"[{"device_id":1,"username":"sensitive-value"}]"#,
        ] {
            let error = Credentials::from_json(raw, &BTreeSet::from([1])).err().context("must reject")?;
            assert!(!format!("{error:#}").contains("sensitive-value"));
        }
        assert!(
            Credentials::from_json(
                &vec![b' '; MAX_MAPPING_BYTES as usize + 1],
                &BTreeSet::from([1])
            )
            .is_err()
        );
        Ok(())
    }

    #[test]
    fn selected_missing_secret_is_an_error_not_other_devices_password() -> Result<()> {
        use std::os::unix::fs::{DirBuilderExt, symlink};
        let dir = env::temp_dir().join(format!(
            "ftd-credential-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)?
                .as_nanos()
        ));
        fs::DirBuilder::new().mode(0o700).create(&dir)?;
        let result = (|| -> Result<()> {
            let Credentials::PerDevice(mut entries) = parse(&mapping())? else {
                bail!("wrong mode");
            };
            let missing = dir.join("missing");
            let present = dir.join("present");
            entries.get_mut(&1).context("device 1")?.password_file = missing;
            entries.get_mut(&2).context("device 2")?.password_file = present.clone();
            let credentials = Credentials::PerDevice(entries);
            fs::write(&present, "synthetic-only")?;
            assert!(load_ssh_password(&credentials.for_device(1)?.password_file).is_err());
            assert_eq!(
                *load_ssh_password(&credentials.for_device(2)?.password_file)?,
                "synthetic-only"
            );
            let link = dir.join("symlink");
            symlink(&present, &link)?;
            assert!(load_ssh_password(&link).is_err());
            assert!(load_ssh_password(&dir).is_err());
            fs::write(&present, "")?;
            assert!(load_ssh_password(&present).is_err());
            fs::write(&present, vec![b'x'; 16 * 1024 + 1])?;
            assert!(load_ssh_password(&present).is_err());
            fs::write(&present, [0xff])?;
            assert!(load_ssh_password(&present).is_err());
            fs::write(&present, " spaced password \n")?;
            assert_eq!(*load_ssh_password(&present)?, " spaced password \n");
            Ok(())
        })();
        fs::remove_dir_all(&dir)?;
        result?;
        Ok(())
    }
}
