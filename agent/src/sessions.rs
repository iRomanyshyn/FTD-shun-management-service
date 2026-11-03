//! Bounded, process-local completion evidence; never durable mutation authority.

use std::collections::{BTreeMap, VecDeque};
use std::sync::Mutex;

use anyhow::{Context, Result, bail};

pub(super) const BEGIN: u8 = 0x18;
pub(super) const LOOKUP: u8 = 0x19;
const CAPACITY: usize = 4096;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub(super) struct Key {
    pub version: u8,
    pub device: u16,
    pub id: [u8; 16],
}

pub(super) fn decode(packet: &[u8], operation: u8) -> Result<Key> {
    if !matches!(operation, BEGIN | LOOKUP)
        || packet.len() != 20
        || packet[0] != operation
        || !matches!(packet[1], 1..=5)
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

#[derive(Clone, Copy)]
enum State {
    Active { prepared: bool },
    Complete { read_only: bool },
}

#[derive(Default)]
struct Journal {
    entries: BTreeMap<Key, State>,
    completed: VecDeque<Key>,
}

#[derive(Default)]
pub(super) struct Sessions(Mutex<Journal>);

impl Sessions {
    pub(super) fn reserve(&self, key: Key) -> Result<()> {
        let mut journal = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("session journal unavailable"))?;
        if journal.entries.contains_key(&key) {
            bail!("session identity already retained");
        }
        if journal.entries.len() == CAPACITY {
            let oldest = journal
                .completed
                .pop_front()
                .context("session journal has no completed capacity")?;
            journal.entries.remove(&oldest);
        }
        journal
            .entries
            .insert(key, State::Active { prepared: false });
        Ok(())
    }

    pub(super) fn prepare_read_only(&self, key: Key) -> Result<()> {
        let mut journal = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("session journal unavailable"))?;
        match journal.entries.get_mut(&key) {
            Some(State::Active { prepared }) => {
                *prepared = true;
                Ok(())
            }
            _ => bail!("session is not active"),
        }
    }

    pub(super) fn complete(&self, key: Key) -> Result<()> {
        let mut journal = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("session journal unavailable"))?;
        match journal.entries.get(&key).copied() {
            Some(State::Active { prepared }) => {
                journal.entries.insert(
                    key,
                    State::Complete {
                        read_only: prepared,
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
            Some(State::Complete { read_only: true }) => 0,
            Some(State::Active { .. }) => 2,
            _ => 1,
        };
        let mut packet = vec![status, key.version, LOOKUP];
        packet.extend(key.device.to_be_bytes());
        packet.extend(key.id);
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
