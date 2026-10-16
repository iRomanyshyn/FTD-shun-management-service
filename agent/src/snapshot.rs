//! Bounded v2 typed snapshot frames; never partial CLI output.

use super::*;
use sha2::{Digest, Sha256};
use std::time::Instant;

pub(super) const VERSION: u8 = 2;
pub(super) const CHUNK_BYTES: usize = 32768;
pub(super) const MAX_BYTES: usize = 2 * 1024 * 1024;
pub(super) const MAX_ENTRIES: usize = 20000;
pub(super) const MAX_OUTPUT_BYTES: usize = 4 * 1024 * 1024;

pub(super) fn encode(
    entries: BTreeSet<ObservedShun>,
    opcode: u8,
    sequence: u8,
) -> Result<Vec<Vec<u8>>> {
    if !matches!(opcode, 7 | 0x10 | 0x11 | 0x13)
        || entries.len() > MAX_ENTRIES
        || (matches!(opcode, 7 | 0x10) && sequence != 0)
        || (matches!(opcode, 0x11 | 0x13) && !(1..=18).contains(&sequence))
    {
        bail!("invalid large snapshot operation or entry count");
    }
    let count = entries.len() as u32;
    let mut data = Vec::new();
    for entry in entries {
        if !is_safe_interface(&entry.interface)
            || data.len().saturating_add(5 + entry.interface.len()) > MAX_BYTES
        {
            bail!("invalid large snapshot interface or byte count");
        }
        data.extend(entry.target.octets());
        data.push(entry.interface.len() as u8);
        data.extend(entry.interface.as_bytes());
    }
    let prefix = [0, VERSION, opcode, sequence];
    let mut manifest = prefix.to_vec();
    manifest.push(0);
    manifest.extend(count.to_be_bytes());
    manifest.extend((data.len() as u32).to_be_bytes());
    manifest.extend((data.len().div_ceil(CHUNK_BYTES) as u16).to_be_bytes());
    let mut frames = vec![manifest];
    for (index, chunk) in data.chunks(CHUNK_BYTES).enumerate() {
        let mut frame = prefix.to_vec();
        frame.push(1);
        frame.extend((index as u16).to_be_bytes());
        frame.extend(chunk);
        frames.push(frame);
    }
    let mut end = prefix.to_vec();
    end.push(2);
    end.extend(Sha256::digest(&data));
    frames.push(end);
    Ok(frames)
}

pub(super) fn send_frames(
    connection: &OwnedFd,
    frames: &[Vec<u8>],
    deadline: Instant,
) -> Result<()> {
    let deadline = deadline.min(Instant::now() + Duration::from_secs(10));
    for frame in frames {
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .context("snapshot transfer deadline expired")?;
        cycle::set_ipc_timeout(connection, remaining)?;
        if send(connection.as_raw_fd(), frame, MsgFlags::MSG_NOSIGNAL)? != frame.len() {
            bail!("incomplete snapshot packet send");
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entries(count: u32, interface: &str) -> BTreeSet<ObservedShun> {
        (0..count)
            .map(|index| ObservedShun {
                target: Ipv4Addr::from(0xc6120000 + index),
                interface: interface.into(),
            })
            .collect()
    }

    #[test]
    fn shared_python_rust_vectors() -> Result<()> {
        let vectors: serde_json::Value =
            serde_json::from_str(include_str!("../../tests/fixtures/snapshot-v2.json"))?;
        for vector in vectors.as_array().context("expected vectors")? {
            let opcode = vector["opcode"].as_u64().context("opcode")? as u8;
            let sequence = vector["sequence"].as_u64().context("sequence")? as u8;
            let entries = match opcode {
                0x10 => BTreeSet::from([ObservedShun {
                    target: Ipv4Addr::new(198, 51, 100, 251),
                    interface: "management".into(),
                }]),
                0x11 => BTreeSet::from([
                    ObservedShun {
                        target: Ipv4Addr::new(198, 51, 100, 250),
                        interface: "management".into(),
                    },
                    ObservedShun {
                        target: Ipv4Addr::new(203, 0, 113, 17),
                        interface: "outside".into(),
                    },
                ]),
                _ => BTreeSet::new(),
            };
            let expected: Result<Vec<Vec<u8>>> = vector["frames"]
                .as_array()
                .context("frames")?
                .iter()
                .map(|frame| {
                    frame
                        .as_str()
                        .context("frame hex")?
                        .as_bytes()
                        .chunks(2)
                        .map(|pair| Ok(u8::from_str_radix(std::str::from_utf8(pair)?, 16)?))
                        .collect()
                })
                .collect();
            assert_eq!(encode(entries, opcode, sequence)?, expected?);
        }
        Ok(())
    }

    #[test]
    fn full_populations_remain_in_bounded_packets() -> Result<()> {
        for (count, name) in [(7307, "management".to_owned()), (20000, "a".repeat(64))] {
            let frames = encode(entries(count, &name), 7, 0)?;
            assert!(frames.len() <= 66);
            assert!(frames.iter().all(|frame| frame.len() <= CHUNK_BYTES + 7));
            assert_eq!(&frames[0][5..9], &count.to_be_bytes());
            let payload: Vec<u8> = frames[1..frames.len() - 1]
                .iter()
                .flat_map(|frame| frame[7..].iter().copied())
                .collect();
            assert_eq!(payload.len(), count as usize * (5 + name.len()));
            assert_eq!(
                &frames[frames.len() - 1][5..],
                Sha256::digest(&payload).as_slice()
            );
        }
        assert!(encode(entries(MAX_ENTRIES as u32 + 1, "management"), 7, 0).is_err());
        assert!(encode(entries(1, "$unsafe"), 7, 0).is_err());
        Ok(())
    }

    #[test]
    fn slow_peer_send_has_one_absolute_deadline() -> Result<()> {
        use nix::sys::socket::socketpair;
        let (sender, _receiver) = socketpair(
            AddressFamily::Unix,
            SockType::SeqPacket,
            None,
            SockFlag::SOCK_CLOEXEC,
        )?;
        let frames = encode(entries(20000, &"a".repeat(64)), 7, 0)?;
        let started = Instant::now();
        assert!(send_frames(&sender, &frames, started + Duration::from_millis(30)).is_err());
        assert!(started.elapsed() < Duration::from_secs(1));
        Ok(())
    }

    #[test]
    fn real_seqpacket_stream_preserves_all_frames() -> Result<()> {
        use nix::sys::socket::socketpair;
        let (sender, receiver) = socketpair(
            AddressFamily::Unix,
            SockType::SeqPacket,
            None,
            SockFlag::SOCK_CLOEXEC,
        )?;
        let frames = encode(entries(20000, "management"), 7, 0)?;
        let expected = frames.clone();
        let worker = std::thread::spawn(move || -> Result<()> {
            cycle::set_ipc_timeout(&receiver, Duration::from_secs(3))?;
            for frame in expected {
                let mut buffer = vec![0u8; MAX_AGENT_RESPONSE_BYTES];
                let length = recv(receiver.as_raw_fd(), &mut buffer, MsgFlags::MSG_TRUNC)?;
                assert_eq!(length, frame.len());
                assert_eq!(&buffer[..length], frame.as_slice());
            }
            Ok(())
        });
        send_frames(&sender, &frames, Instant::now() + Duration::from_secs(3))?;
        worker
            .join()
            .map_err(|_| anyhow::anyhow!("snapshot receiver panicked"))??;
        Ok(())
    }

    #[test]
    fn console_buffers_and_parser_are_independently_bounded() -> Result<()> {
        for limit in [MAX_CISCO_OUTPUT_BYTES, MAX_OUTPUT_BYTES] {
            let mut output = Vec::new();
            for _ in 0..limit / CHUNK_BYTES {
                append_ftd_output(&mut output, &vec![b'x'; CHUNK_BYTES], limit)?;
            }
            assert_eq!(output.len(), limit);
            assert!(append_ftd_output(&mut output, b"x", limit).is_err());
            assert_eq!(output.len(), limit);
        }
        let allowed = BTreeSet::from(["management".to_owned()]);
        let output: String = (0..7307)
            .map(|index| {
                format!(
                    "shun (management) {} 0.0.0.0 0 0 0\r\n",
                    Ipv4Addr::from(0xc6120000u32 + index)
                )
            })
            .collect();
        assert!(output.len() > MAX_CISCO_OUTPUT_BYTES && output.len() < MAX_OUTPUT_BYTES);
        assert_eq!(parse_show_shun_entries(&output, &allowed)?.len(), 7307);
        let over: String = (0..=MAX_ENTRIES)
            .map(|index| {
                format!(
                    "shun (management) {} 0.0.0.0 0 0 0\n",
                    Ipv4Addr::from(0xc6120000u32 + index as u32)
                )
            })
            .collect();
        assert!(parse_show_shun_entries(&over, &allowed).is_err());
        Ok(())
    }
}
