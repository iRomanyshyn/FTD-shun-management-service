//! Agent-private completion evidence, not command authority or a write-ahead log.

use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::net::Ipv4Addr;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::path::{Component, Path, PathBuf};

use anyhow::{Context, Result, bail};
use sha2::{Digest, Sha256};

use super::sessions::{CAPACITY, Key};

const MAGIC: &[u8; 8] = b"FTDPEND1";
const DATA: &str = "pending-completions.bin";
const TEMP: &str = "pending-completions.next";
const MAX_BYTES: usize = 10 + CAPACITY * (20 + 69) + 32;
pub(super) type Records = Vec<(Key, Vec<u8>)>;

pub(super) fn configured(
    value: Option<std::ffi::OsString>,
    version: u8,
) -> Result<Option<PathBuf>> {
    let Some(value) = value else { return Ok(None) };
    let path = PathBuf::from(value);
    if version != 7
        || !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, Component::ParentDir))
    {
        bail!(
            "pending journal requires deferred version 7 and an absolute directory without parent traversal"
        );
    }
    Ok(Some(path))
}

fn owner() -> u32 {
    // libc call has no pointers or preconditions; no credentials are changed.
    unsafe { nix::libc::geteuid() }
}

fn private(metadata: &fs::Metadata, directory: bool) -> Result<()> {
    if metadata.uid() != owner()
        || metadata.permissions().mode() & 0o7777 != if directory { 0o700 } else { 0o600 }
        || if directory {
            !metadata.is_dir()
        } else {
            !metadata.is_file() || metadata.nlink() != 1
        }
    {
        bail!("pending journal requires an owner-only directory and private regular files");
    }
    Ok(())
}

fn open(path: &Path, directory: bool) -> Result<File> {
    if directory && fs::canonicalize(path)? != path {
        bail!("pending journal directory must not traverse symlinks");
    }
    let mut options = OpenOptions::new();
    options.read(true).custom_flags(
        nix::libc::O_NOFOLLOW
            | nix::libc::O_NONBLOCK
            | if directory { nix::libc::O_DIRECTORY } else { 0 },
    );
    let file = options
        .open(path)
        .context("could not open private pending journal")?;
    private(&file.metadata()?, directory)?;
    Ok(file)
}

fn read(directory: &Path) -> Result<Records> {
    let file = match open(&directory.join(DATA), false) {
        Ok(file) => file,
        Err(error)
            if error
                .downcast_ref::<std::io::Error>()
                .is_some_and(|error| error.kind() == std::io::ErrorKind::NotFound) =>
        {
            return Ok(Vec::new());
        }
        Err(error) => return Err(error),
    };
    let mut bytes = Vec::new();
    file.take((MAX_BYTES + 1) as u64).read_to_end(&mut bytes)?;
    decode(&bytes)
}

/// Read-only preflight: does not create locks, remove scratch files or repair data.
pub(super) fn check(directory: &Path) -> Result<()> {
    let _directory = open(directory, true)?;
    read(directory)?;
    Ok(())
}

pub(super) struct PendingJournal {
    directory: PathBuf,
    directory_fd: File,
    _lock: File,
}

impl Drop for PendingJournal {
    fn drop(&mut self) {
        // Explicit unlock also releases fork-inherited descriptions before exec.
        // Closing only our descriptor could leave a transient inherited owner.
        let _ = File::unlock(&self._lock);
    }
}

impl PendingJournal {
    pub(super) fn load(directory: &Path) -> Result<(Self, Records)> {
        let directory_fd = open(directory, true)?;
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(nix::libc::O_NOFOLLOW | nix::libc::O_NONBLOCK)
            .open(directory.join("pending-completions.lock"))?;
        private(&lock.metadata()?, false)?;
        lock.try_lock()
            .context("pending journal is already owned by another agent")?;
        let records = read(directory)?;
        // Only an uncommitted, strictly private scratch file may be discarded.
        // The committed journal is never repaired, truncated or silently reset.
        match fs::symlink_metadata(directory.join(TEMP)) {
            Ok(metadata) => {
                private(&metadata, false)?;
                fs::remove_file(directory.join(TEMP))?;
                directory_fd.sync_all()?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        Ok((
            Self {
                directory: directory.to_owned(),
                directory_fd,
                _lock: lock,
            },
            records,
        ))
    }

    pub(super) fn replace(&self, records: &Records) -> Result<()> {
        let bytes = encode(records)?;
        let path = self.directory.join(TEMP);
        let result = (|| -> Result<()> {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .custom_flags(nix::libc::O_NOFOLLOW | nix::libc::O_NONBLOCK)
                .open(&path)?;
            file.write_all(&bytes)?;
            file.sync_all()?;
            fs::rename(&path, self.directory.join(DATA))?;
            self.directory_fd.sync_all()?;
            Ok(())
        })();
        // A failed commit is never retried here and never publishes memory.
        // Leave its scratch/evidence for strict startup validation.
        result.context("pending journal persistence failed; completion was not published")
    }
}

fn valid(key: Key, packet: &[u8]) -> Result<()> {
    if key.version != 7
        || key.device == 0
        || key.id == [0; 16]
        || packet.len() < 9
        || packet[..3] != [6, 7, super::batch_addition::END_PENDING]
        || packet.len() != 5 + usize::from(packet[4]) * 4
    {
        bail!("invalid persisted pending completion");
    }
    let targets: Vec<_> = packet[5..]
        .as_chunks::<4>()
        .0
        .iter()
        .map(|ip| Ipv4Addr::new(ip[0], ip[1], ip[2], ip[3]))
        .collect();
    if super::batch_addition::pending_end(&targets, packet[3], 7)? != packet {
        bail!("noncanonical persisted pending completion");
    }
    Ok(())
}

fn encode(records: &Records) -> Result<Vec<u8>> {
    if records.len() > CAPACITY {
        bail!("pending journal exceeds capacity");
    }
    let mut keys = std::collections::BTreeSet::new();
    let mut bytes = MAGIC.to_vec();
    bytes.extend((records.len() as u16).to_be_bytes());
    for (key, packet) in records {
        valid(*key, packet)?;
        if !keys.insert(*key) {
            bail!("duplicate persisted session identity");
        }
        bytes.push(key.version);
        bytes.extend(key.device.to_be_bytes());
        bytes.extend(key.id);
        bytes.push(packet.len() as u8);
        bytes.extend(packet);
    }
    let digest = Sha256::digest(&bytes);
    bytes.extend(digest);
    Ok(bytes)
}

fn decode(bytes: &[u8]) -> Result<Records> {
    if bytes.len() < 42 || bytes.len() > MAX_BYTES || &bytes[..8] != MAGIC {
        bail!("invalid pending journal format or size");
    }
    let (payload, digest) = bytes.split_at(bytes.len() - 32);
    if Sha256::digest(payload).as_slice() != digest {
        bail!("pending journal checksum mismatch");
    }
    let count = usize::from(u16::from_be_bytes([bytes[8], bytes[9]]));
    if count > CAPACITY {
        bail!("pending journal exceeds capacity");
    }
    let mut rest = &payload[10..];
    let mut records = Vec::with_capacity(count);
    for _ in 0..count {
        if rest.len() < 20 {
            bail!("truncated pending journal entry");
        }
        let key = Key {
            version: rest[0],
            device: u16::from_be_bytes([rest[1], rest[2]]),
            id: rest[3..19].try_into()?,
        };
        let length = usize::from(rest[19]);
        rest = &rest[20..];
        if rest.len() < length {
            bail!("truncated pending journal receipt");
        }
        records.push((key, rest[..length].to_vec()));
        rest = &rest[length..];
    }
    if !rest.is_empty() || encode(&records)? != bytes {
        bail!("noncanonical pending journal data");
    }
    Ok(records)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sessions::Sessions;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT: AtomicU64 = AtomicU64::new(1);

    struct Directory(PathBuf);
    impl Directory {
        fn new() -> Result<Self> {
            let path = std::env::temp_dir().join(format!(
                "ftd-pending-journal-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir(&path)?;
            fs::set_permissions(&path, fs::Permissions::from_mode(0o700))?;
            Ok(Self(path))
        }
    }
    impl Drop for Directory {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    fn key(number: u128) -> Key {
        Key {
            version: 7,
            device: 1,
            id: number.to_be_bytes(),
        }
    }
    fn packet() -> Result<Vec<u8>> {
        crate::batch_addition::pending_end(
            &["198.51.100.178".parse()?, "198.51.100.179".parse()?],
            4,
            7,
        )
    }
    fn complete(sessions: &Sessions, key: Key) -> Result<()> {
        sessions.reserve(key)?;
        sessions.prepare_pending(
            key,
            4,
            &["198.51.100.178".parse()?, "198.51.100.179".parse()?],
        )?;
        sessions.complete(key)
    }

    #[test]
    fn only_postamble_completed_pending_receipts_survive_restart() -> Result<()> {
        let directory = Directory::new()?;
        let sessions = Sessions::persistent(&directory.0)?;
        complete(&sessions, key(1))?;
        sessions.reserve(key(2))?;
        sessions.prepare_pending(key(2), 4, &["198.51.100.180".parse()?])?;
        sessions.reserve(key(3))?;
        sessions.prepare_read_only(key(3))?;
        sessions.complete(key(3))?;
        sessions.reserve(key(4))?;
        sessions.complete(key(4))?;
        let expected = sessions.lookup_pending(key(1))?;
        drop(sessions);
        let restarted = Sessions::persistent(&directory.0)?;
        assert_eq!(restarted.lookup_pending(key(1))?, expected);
        assert_eq!(restarted.lookup(key(1))?[0], 1); // Never read-only proof.
        for number in 2..=4 {
            assert_eq!(restarted.lookup_pending(key(number))?[0], 1);
        }
        assert_eq!(restarted.lookup(key(3))?[0], 1);
        assert!(restarted.reserve(key(1)).is_err()); // Cannot replay retained BEGIN.
        assert_eq!(read(&directory.0)?.len(), 1);
        Ok(())
    }

    #[test]
    fn process_lock_refuses_second_writer_and_preflight_never_writes() -> Result<()> {
        let directory = Directory::new()?;
        check(&directory.0)?;
        assert_eq!(fs::read_dir(&directory.0)?.count(), 0);
        let sessions = Sessions::persistent(&directory.0)?;
        assert!(Sessions::persistent(&directory.0).is_err());
        complete(&sessions, key(1))?;
        let original = fs::read(directory.0.join(DATA))?;
        check(&directory.0)?;
        assert_eq!(fs::read(directory.0.join(DATA))?, original);
        drop(sessions);
        assert!(Sessions::persistent(&directory.0).is_ok());
        Ok(())
    }

    #[test]
    fn persistence_failure_never_publishes_prepared_memory_or_overwrites_evidence() -> Result<()> {
        let directory = Directory::new()?;
        let sessions = Sessions::persistent(&directory.0)?;
        complete(&sessions, key(1))?;
        let original = fs::read(directory.0.join(DATA))?;
        fs::write(directory.0.join(TEMP), b"synthetic interrupted write")?;
        fs::set_permissions(directory.0.join(TEMP), fs::Permissions::from_mode(0o600))?;
        assert!(complete(&sessions, key(2)).is_err());
        assert_eq!(sessions.lookup_pending(key(2))?[0], 2);
        assert_eq!(fs::read(directory.0.join(DATA))?, original);
        drop(sessions);
        let restarted = Sessions::persistent(&directory.0)?;
        assert_eq!(restarted.lookup_pending(key(1))?[0], 0);
        assert_eq!(restarted.lookup_pending(key(2))?[0], 1);
        assert!(!directory.0.join(TEMP).exists());
        Ok(())
    }

    #[test]
    fn eviction_is_durable_before_identity_can_be_reused() -> Result<()> {
        let directory = Directory::new()?;
        let (disk, _) = PendingJournal::load(&directory.0)?;
        let records = (1..=CAPACITY)
            .map(|number| Ok((key(number as u128), packet()?)))
            .collect::<Result<Records>>()?;
        disk.replace(&records)?;
        drop(disk);
        let sessions = Sessions::persistent(&directory.0)?;
        sessions.reserve(key((CAPACITY + 1) as u128))?;
        let retained = read(&directory.0)?;
        assert_eq!(retained.len(), CAPACITY - 1);
        assert_eq!(retained[0].0, key(2));
        drop(sessions);
        let restarted = Sessions::persistent(&directory.0)?;
        assert_eq!(restarted.lookup_pending(key(1))?[0], 1);
        assert_eq!(restarted.lookup_pending(key(2))?[0], 0);
        restarted.reserve(key(1))?;
        Ok(())
    }

    #[test]
    fn failed_eviction_preserves_original_identity_and_refuses_new_session() -> Result<()> {
        let directory = Directory::new()?;
        let (disk, _) = PendingJournal::load(&directory.0)?;
        disk.replace(
            &(1..=CAPACITY)
                .map(|number| Ok((key(number as u128), packet()?)))
                .collect::<Result<Records>>()?,
        )?;
        drop(disk);
        let sessions = Sessions::persistent(&directory.0)?;
        fs::write(directory.0.join(TEMP), b"existing scratch")?;
        assert!(sessions.reserve(key((CAPACITY + 1) as u128)).is_err());
        assert_eq!(sessions.lookup_pending(key(1))?[0], 0);
        assert_eq!(sessions.lookup_pending(key((CAPACITY + 1) as u128))?[0], 1);
        assert_eq!(read(&directory.0)?.len(), CAPACITY);
        Ok(())
    }

    #[test]
    fn strict_format_rejects_damage_duplicate_identity_and_invalid_terminal_scope() -> Result<()> {
        let records = vec![(key(1), packet()?)];
        let bytes = encode(&records)?;
        assert_eq!(decode(&bytes)?, records);
        for index in [0, 8, 10, 29, 30, bytes.len() - 1] {
            let mut corrupt = bytes.clone();
            corrupt[index] ^= 1;
            assert!(decode(&corrupt).is_err());
        }
        for length in [0, 8, 10, 30, bytes.len() - 1] {
            assert!(decode(&bytes[..length]).is_err());
        }
        assert!(decode(&vec![0; MAX_BYTES + 1]).is_err());
        assert!(encode(&vec![records[0].clone(); CAPACITY + 1]).is_err());
        assert!(encode(&vec![records[0].clone(), records[0].clone()]).is_err());
        for number in [0, 1, 2, 3, 4] {
            let mut malformed = packet()?;
            malformed[number] = 0;
            assert!(encode(&vec![(key(1), malformed)]).is_err());
        }
        let mut wrong = key(1);
        wrong.version = 6;
        assert!(encode(&vec![(wrong, packet()?)]).is_err());
        assert!(encode(&vec![(key(0), packet()?)]).is_err());
        Ok(())
    }

    #[test]
    fn corrupt_committed_file_is_never_reset_even_with_valid_scratch() -> Result<()> {
        let directory = Directory::new()?;
        let (disk, _) = PendingJournal::load(&directory.0)?;
        disk.replace(&vec![(key(1), packet()?)])?;
        drop(disk);
        let invalid = b"corrupt retained evidence";
        fs::write(directory.0.join(DATA), invalid)?;
        fs::write(directory.0.join(TEMP), encode(&vec![(key(2), packet()?)])?)?;
        assert!(check(&directory.0).is_err());
        assert!(Sessions::persistent(&directory.0).is_err());
        assert_eq!(fs::read(directory.0.join(DATA))?, invalid);
        assert!(directory.0.join(TEMP).exists());
        Ok(())
    }

    #[test]
    fn refuses_symlinks_hardlinks_and_broad_permissions() -> Result<()> {
        use std::os::unix::fs::symlink;
        let directory = Directory::new()?;
        let external = Directory::new()?;
        symlink(&directory.0, external.0.join("alias"))?;
        assert!(check(&external.0.join("alias")).is_err());
        fs::set_permissions(&directory.0, fs::Permissions::from_mode(0o770))?;
        assert!(check(&directory.0).is_err());
        fs::set_permissions(&directory.0, fs::Permissions::from_mode(0o700))?;
        symlink(external.0.join("target"), directory.0.join(DATA))?;
        assert!(check(&directory.0).is_err());
        fs::remove_file(directory.0.join(DATA))?;
        let (disk, _) = PendingJournal::load(&directory.0)?;
        disk.replace(&vec![(key(1), packet()?)])?;
        drop(disk);
        fs::hard_link(directory.0.join(DATA), external.0.join("linked"))?;
        assert!(check(&directory.0).is_err());
        fs::remove_file(external.0.join("linked"))?;
        fs::set_permissions(directory.0.join(DATA), fs::Permissions::from_mode(0o640))?;
        assert!(check(&directory.0).is_err());
        Ok(())
    }

    #[test]
    fn missing_directory_and_wrong_profiles_are_not_initialized() -> Result<()> {
        let directory = Directory::new()?;
        assert!(check(&directory.0.join("missing")).is_err());
        assert!(!directory.0.join("missing").exists());
        assert!(configured(Some(directory.0.clone().into_os_string()), 6).is_err());
        for path in ["", "relative", "/tmp/../private"] {
            assert!(configured(Some(path.into()), 7).is_err());
        }
        assert_eq!(configured(None, 6)?, None);
        assert_eq!(
            configured(Some(directory.0.clone().into_os_string()), 7)?,
            Some(directory.0.clone())
        );
        Ok(())
    }

    #[test]
    #[ignore = "subprocess fixture invoked only by process_restart_retains_exact_receipt"]
    fn subprocess_write() -> Result<()> {
        let path =
            std::env::var_os("FTD_TEST_PENDING_JOURNAL").context("missing child directory")?;
        let sessions = Sessions::persistent(Path::new(&path))?;
        if let Some(raw) = std::env::var_os("FTD_TEST_PENDING_SCOPE") {
            #[derive(serde::Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Scope {
                device: u16,
                id: [u8; 16],
                sequence: u8,
                targets: Vec<Ipv4Addr>,
            }
            let scope: Scope = serde_json::from_str(raw.to_str().context("non-UTF8 test scope")?)?;
            let identity = Key {
                version: 7,
                device: scope.device,
                id: scope.id,
            };
            sessions.reserve(identity)?;
            sessions.prepare_pending(identity, scope.sequence, &scope.targets)?;
            sessions.complete(identity)?;
        } else {
            complete(&sessions, key(42))?;
        }
        // Simulate immediate process exit: no destructor or graceful shutdown.
        std::process::exit(0);
    }

    #[test]
    fn process_restart_retains_exact_receipt() -> Result<()> {
        let directory = Directory::new()?;
        let status = std::process::Command::new(std::env::current_exe()?)
            .args([
                "--exact",
                "pending_journal::tests::subprocess_write",
                "--ignored",
            ])
            .env("FTD_TEST_PENDING_JOURNAL", &directory.0)
            .status()?;
        assert!(status.success());
        let sessions = Sessions::persistent(&directory.0)?;
        let reply = sessions.lookup_pending(key(42))?;
        assert_eq!(reply[0], 0);
        assert_eq!(&reply[21..], packet()?.as_slice());
        assert_eq!(sessions.lookup_pending(key(43))?[0], 1);
        Ok(())
    }
}
