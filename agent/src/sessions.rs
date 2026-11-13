//! Bounded completion evidence; optional agent-private persistence for pending v7.

use std::collections::{BTreeMap, VecDeque};
use std::sync::Mutex;

use anyhow::{Context, Result, bail};

pub(super) const BEGIN: u8 = 0x18;
pub(super) const LOOKUP: u8 = 0x19;
pub(super) const LOOKUP_PENDING: u8 = 0x1e;
pub(super) const CAPACITY: usize = 4096;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub(super) struct Key {
    pub version: u8,
    pub device: u16,
    pub id: [u8; 16],
}

pub(super) fn decode(packet: &[u8], operation: u8) -> Result<Key> {
    if !matches!(operation, BEGIN | LOOKUP | LOOKUP_PENDING)
        || packet.len() != 20
        || packet[0] != operation
        || !matches!(packet[1], 1..=7)
        || (operation == LOOKUP_PENDING && packet[1] != 7)
    {
        bail!("invalid bound session packet");
    }
    let device = u16::from_be_bytes([packet[2], packet[3]]);
    let id = packet[4..].try_into()?;
    if device == 0 || id == [0; 16] {
        bail!("invalid bound session identity");
    }
    Ok(Key {
        version: packet[1],
        device,
        id,
    })
}

#[derive(Clone)]
enum State {
    Active {
        prepared: bool,
        pending: Option<Vec<u8>>,
    },
    Complete {
        read_only: bool,
        pending: Option<Vec<u8>>,
    },
}

#[derive(Default)]
struct Journal {
    entries: BTreeMap<Key, State>,
    completed: VecDeque<Key>,
    disk: Option<super::pending_journal::PendingJournal>,
}

impl Journal {
    fn pending_records(&self, exclude: Option<Key>) -> super::pending_journal::Records {
        self.completed
            .iter()
            .filter(|key| Some(**key) != exclude)
            .filter_map(|key| match self.entries.get(key) {
                Some(State::Complete {
                    read_only: false,
                    pending: Some(packet),
                }) => Some((*key, packet.clone())),
                _ => None,
            })
            .collect()
    }
}

#[derive(Default)]
pub(super) struct Sessions(Mutex<Journal>);

impl Sessions {
    pub(super) fn persistent(directory: &std::path::Path) -> Result<Self> {
        let (disk, records) = super::pending_journal::PendingJournal::load(directory)?;
        let mut journal = Journal {
            disk: Some(disk),
            ..Journal::default()
        };
        for (key, packet) in records {
            journal.completed.push_back(key);
            journal.entries.insert(
                key,
                State::Complete {
                    read_only: false,
                    pending: Some(packet),
                },
            );
        }
        Ok(Self(Mutex::new(journal)))
    }

    pub(super) fn reserve(&self, key: Key) -> Result<()> {
        let mut journal = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("session journal unavailable"))?;
        if journal.entries.contains_key(&key) {
            bail!("session identity already retained");
        }
        if journal.entries.len() == CAPACITY {
            let oldest = *journal
                .completed
                .front()
                .context("session journal has no completed capacity")?;
            if let Some(disk) = &journal.disk
                && matches!(
                    journal.entries.get(&oldest),
                    Some(State::Complete {
                        pending: Some(_),
                        ..
                    })
                )
            {
                disk.replace(&journal.pending_records(Some(oldest)))?;
            }
            journal.completed.pop_front();
            journal.entries.remove(&oldest);
        }
        journal.entries.insert(
            key,
            State::Active {
                prepared: false,
                pending: None,
            },
        );
        Ok(())
    }

    pub(super) fn prepare_read_only(&self, key: Key) -> Result<()> {
        let mut journal = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("session journal unavailable"))?;
        match journal.entries.get_mut(&key) {
            Some(State::Active {
                prepared,
                pending: None,
            }) => {
                *prepared = true;
                Ok(())
            }
            _ => bail!("session is not active"),
        }
    }

    /// Prepare only after END_PENDING executed and transport cleanup succeeded.
    /// Still invisible until the handler, device guard and worker have settled.
    pub(super) fn prepare_pending(
        &self,
        key: Key,
        sequence: u8,
        targets: &[std::net::Ipv4Addr],
    ) -> Result<()> {
        let packet = super::batch_addition::pending_end(targets, sequence, key.version)?;
        let mut journal = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("session journal unavailable"))?;
        match journal.entries.get_mut(&key) {
            Some(State::Active {
                prepared: false,
                pending,
            }) if pending.is_none() => {
                *pending = Some(packet);
                Ok(())
            }
            _ => bail!("pending settlement is not an unprepared active session"),
        }
    }

    pub(super) fn complete(&self, key: Key) -> Result<()> {
        let mut journal = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("session journal unavailable"))?;
        match journal.entries.get(&key).cloned() {
            Some(State::Active { prepared, pending }) => {
                if let (Some(disk), Some(packet)) = (&journal.disk, &pending) {
                    let mut records = journal.pending_records(None);
                    records.push((key, packet.clone()));
                    disk.replace(&records)?;
                }
                journal.entries.insert(
                    key,
                    State::Complete {
                        read_only: prepared,
                        pending,
                    },
                );
                journal.completed.push_back(key);
                Ok(())
            }
            _ => bail!("session completion was not active"),
        }
    }

    pub(super) fn lookup(&self, key: Key) -> Result<Vec<u8>> {
        let journal = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("session journal unavailable"))?;
        let status = match journal.entries.get(&key) {
            Some(State::Complete {
                read_only: true, ..
            }) => 0,
            Some(State::Active { .. }) => 2,
            _ => 1,
        };
        let mut packet = vec![status, key.version, LOOKUP];
        packet.extend(key.device.to_be_bytes());
        packet.extend(key.id);
        Ok(packet)
    }

    pub(super) fn lookup_pending(&self, key: Key) -> Result<Vec<u8>> {
        if key.version != 7 {
            bail!("pending lookup requires version 7");
        }
        let journal = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("session journal unavailable"))?;
        let (status, receipt) = match journal.entries.get(&key) {
            Some(State::Complete {
                read_only: false,
                pending: Some(packet),
            }) => (0, packet.as_slice()),
            Some(State::Active { .. }) => (2, &[][..]),
            _ => (1, &[][..]),
        };
        let mut packet = vec![status, key.version, LOOKUP_PENDING];
        packet.extend(key.device.to_be_bytes());
        packet.extend(key.id);
        packet.extend(receipt);
        Ok(packet)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(number: u128) -> Key {
        Key {
            version: 3,
            device: 7,
            id: number.to_be_bytes(),
        }
    }

    #[test]
    fn pending_lookup_requires_postamble_and_never_becomes_read_only() -> Result<()> {
        let vectors: serde_json::Value =
            serde_json::from_str(include_str!("../../tests/fixtures/pending-lookup-v7.json"))?;
        let hex = |packet: Vec<u8>| -> String {
            packet.iter().map(|byte| format!("{byte:02x}")).collect()
        };
        let first = Key {
            version: 7,
            ..key(1)
        };
        let targets = ["198.51.100.251".parse()?, "198.51.100.252".parse()?];
        let sessions = Sessions::default();
        assert_eq!(hex(sessions.lookup_pending(first)?), vectors["unknown"]);
        assert!(sessions.prepare_pending(first, 4, &targets).is_err());
        sessions.reserve(first)?;
        assert_eq!(hex(sessions.lookup_pending(first)?), vectors["active"]);
        assert!(sessions.prepare_pending(first, 4, &[]).is_err());
        assert!(
            sessions
                .prepare_pending(first, 4, &[targets[0], targets[0]])
                .is_err()
        );
        sessions.prepare_pending(first, 4, &targets)?;
        assert_eq!(hex(sessions.lookup_pending(first)?), vectors["active"]);
        assert!(sessions.prepare_read_only(first).is_err());
        assert!(sessions.prepare_pending(first, 4, &targets).is_err());
        sessions.complete(first)?;
        assert_eq!(hex(sessions.lookup_pending(first)?), vectors["complete"]);
        assert_eq!(sessions.lookup(first)?[0], 1); // Never read-only release proof.
        for foreign in [
            Key { device: 8, ..first },
            Key {
                id: [2; 16],
                ..first
            },
        ] {
            assert_eq!(sessions.lookup_pending(foreign)?[0], 1);
        }
        assert!(
            sessions
                .lookup_pending(Key {
                    version: 6,
                    ..first
                })
                .is_err()
        );
        assert_eq!(Sessions::default().lookup_pending(first)?[0], 1);
        let read = Key {
            id: [3; 16],
            ..first
        };
        sessions.reserve(read)?;
        sessions.prepare_read_only(read)?;
        assert!(sessions.prepare_pending(read, 4, &targets).is_err());
        sessions.complete(read)?;
        assert_eq!(sessions.lookup_pending(read)?[0], 1);
        let failed = Key {
            id: [4; 16],
            ..first
        };
        sessions.reserve(failed)?;
        sessions.complete(failed)?;
        assert_eq!(sessions.lookup_pending(failed)?[0], 1);
        let mut request = vec![LOOKUP_PENDING, 7, 0, 7];
        request.extend(first.id);
        assert_eq!(hex(request.clone()), vectors["lookup"]);
        assert_eq!(decode(&request, LOOKUP_PENDING)?, first);
        for version in [0, 1, 6, 8] {
            request[1] = version;
            assert!(decode(&request, LOOKUP_PENDING).is_err());
        }
        Ok(())
    }

    #[test]
    fn pending_receipts_share_bounded_eviction_without_evicting_active_work() -> Result<()> {
        let sessions = Sessions::default();
        let first = Key {
            version: 7,
            ..key(1)
        };
        sessions.reserve(first)?;
        sessions.prepare_pending(first, 2, &["198.51.100.251".parse()?])?;
        sessions.complete(first)?;
        for number in 2..=CAPACITY {
            sessions.reserve(key(number as u128))?;
        }
        sessions.reserve(key(5000))?;
        assert_eq!(sessions.lookup_pending(first)?[0], 1);
        assert!(sessions.reserve(key(5001)).is_err());
        Ok(())
    }

    #[test]
    fn completion_is_not_visible_before_postamble_and_unknown_is_never_safe() -> Result<()> {
        let sessions = Sessions::default();
        let first = key(1);
        assert_eq!(sessions.lookup(first)?[0], 1);
        sessions.reserve(first)?;
        assert_eq!(sessions.lookup(first)?[0], 2);
        sessions.prepare_read_only(first)?;
        assert_eq!(sessions.lookup(first)?[0], 2);
        sessions.complete(first)?;
        assert_eq!(sessions.lookup(first)?[0], 0);
        assert!(sessions.reserve(first).is_err());
        assert!(sessions.complete(first).is_err());
        assert_eq!(sessions.lookup(Key { device: 8, ..first })?[0], 1);
        assert_eq!(
            sessions.lookup(Key {
                version: 2,
                ..first
            })?[0],
            1
        );
        assert_eq!(Sessions::default().lookup(first)?[0], 1);
        sessions.reserve(key(2))?;
        sessions.complete(key(2))?;
        assert_eq!(sessions.lookup(key(2))?[0], 1);
        Ok(())
    }

    #[test]
    fn capacity_evicts_only_completed_records_and_refuses_all_active() -> Result<()> {
        let sessions = Sessions::default();
        for number in 1..=CAPACITY {
            sessions.reserve(key(number as u128))?;
        }
        assert!(sessions.reserve(key(5000)).is_err());
        sessions.prepare_read_only(key(1))?;
        sessions.complete(key(1))?;
        sessions.reserve(key(5000))?;
        assert_eq!(sessions.lookup(key(1))?[0], 1);
        assert_eq!(sessions.lookup(key(2))?[0], 2);
        assert_eq!(
            sessions
                .0
                .lock()
                .map_err(|_| anyhow::anyhow!("test lock"))?
                .entries
                .len(),
            CAPACITY
        );
        Ok(())
    }

    #[test]
    fn packets_are_exact_and_echo_every_binding_byte() -> Result<()> {
        let first = key(1);
        let mut packet = vec![BEGIN, 3, 0, 7];
        packet.extend(first.id);
        assert_eq!(decode(&packet, BEGIN)?, first);
        for invalid in [
            packet[..19].to_vec(),
            [packet.clone(), vec![0]].concat(),
            vec![BEGIN; 20],
            vec![BEGIN, 3, 0, 7],
            vec![BEGIN, 3, 0, 0],
        ] {
            assert!(decode(&invalid, BEGIN).is_err());
        }
        packet[0] = LOOKUP;
        assert_eq!(decode(&packet, LOOKUP)?, first);
        let mut expected = vec![1, 3, LOOKUP, 0, 7];
        expected.extend(first.id);
        assert_eq!(Sessions::default().lookup(first)?, expected);
        Ok(())
    }

    #[test]
    fn shared_python_vectors_bind_all_versions_and_states() -> Result<()> {
        let vectors: serde_json::Value =
            serde_json::from_str(include_str!("../../tests/fixtures/agent-sessions.json"))?;
        let id = [0x10, 0, 0, 0, 0, 0, 0x40, 0, 0x80, 0, 0, 0, 0, 0, 0, 1];
        let hex = |packet: &[u8]| {
            packet
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect::<String>()
        };
        for vector in vectors.as_array().context("vectors")? {
            let version = vector["version"].as_u64().context("version")? as u8;
            let key = Key {
                version,
                device: 7,
                id,
            };
            for (opcode, field) in [(BEGIN, "begin"), (LOOKUP, "lookup")] {
                let mut packet = vec![opcode, version, 0, 7];
                packet.extend(id);
                assert_eq!(hex(&packet), vector[field]);
                assert_eq!(decode(&packet, opcode)?, key);
            }
            let sessions = Sessions::default();
            assert_eq!(hex(&sessions.lookup(key)?), vector["unknown"]);
            sessions.reserve(key)?;
            sessions.prepare_read_only(key)?;
            assert_eq!(hex(&sessions.lookup(key)?), vector["active"]);
            sessions.complete(key)?;
            assert_eq!(hex(&sessions.lookup(key)?), vector["safe"]);
        }
        Ok(())
    }
}
