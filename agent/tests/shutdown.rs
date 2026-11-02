//! Real signals/local SeqPacket only. No SSH, lab inventory or inherited secrets.

use std::fs;
use std::io::{BufRead, BufReader};
use std::os::fd::{AsRawFd, OwnedFd};
use std::os::unix::fs::{DirBuilderExt, FileTypeExt};
use std::path::PathBuf;
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::thread::JoinHandle;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, bail};
use nix::sys::signal::{Signal, kill};
use nix::sys::socket::sockopt::{PeerCredentials, ReceiveTimeout};
use nix::sys::socket::{
    AddressFamily, MsgFlags, SockFlag, SockType, UnixAddr, connect, getsockopt, recv, send,
    setsockopt, socket, socketpair,
};
use nix::sys::time::TimeVal;
use nix::unistd::Pid;

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Result<Self> {
        let dir = std::env::temp_dir().join(format!(
            "ftd-stop-{}-{}",
            std::process::id(),
            SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos()
        ));
        fs::DirBuilder::new().mode(0o700).create(&dir)?;
        fs::write(
            dir.join("devices.json"),
            serde_json::to_vec(&serde_json::json!([{
                "id":1, "hostname":"synthetic-no-ssh", "management_ip":"192.0.2.1",
                "ssh_host_key":"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                "allowed_interfaces":["management"]
            }]))?,
        )?;
        fs::write(dir.join("password"), "synthetic-secret-never-log")?;
        Ok(Self(dir))
    }

    fn start(&self, capacity: usize) -> Result<Running> {
        let (_peer, local) = socketpair(
            AddressFamily::Unix,
            SockType::SeqPacket,
            None,
            SockFlag::SOCK_CLOEXEC,
        )?;
        let uid = getsockopt(&local, PeerCredentials)?.uid();
        let mut child = Command::new(env!("CARGO_BIN_EXE_ftd-shun-agent"))
            .env_clear()
            .env("FTD_SHUN_DEVICE_INVENTORY", self.0.join("devices.json"))
            .env("FTD_SHUN_SSH_USERNAME", "synthetic-basic")
            .env("FTD_SHUN_SSH_PASSWORD_FILE", self.0.join("password"))
            .env("FTD_SHUN_AGENT_SOCKET", self.0.join("agent.sock"))
            .env("FTD_SHUN_AGENT_PEER_UID", uid.to_string())
            .env(
                "FTD_SHUN_AGENT_MAX_CONCURRENT_DEVICES",
                capacity.to_string(),
            )
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()?;
        let stderr = child.stderr.take().context("stderr pipe")?;
        let (send, events) = mpsc::channel();
        let reader = std::thread::spawn(move || {
            for line in BufReader::new(stderr)
                .lines()
                .map_while(std::result::Result::ok)
            {
                let _ = send.send(line);
            }
        });
        let mut running = Running {
            child,
            events,
            reader: Some(reader),
        };
        running.event("agent.listener.ready")?;
        Ok(running)
    }

    fn connect(&self) -> Result<OwnedFd> {
        let fd = socket(
            AddressFamily::Unix,
            SockType::SeqPacket,
            SockFlag::SOCK_CLOEXEC,
            None,
        )?;
        setsockopt(&fd, ReceiveTimeout, &TimeVal::new(3, 0))?;
        connect(fd.as_raw_fd(), &UnixAddr::new(&self.0.join("agent.sock"))?)?;
        Ok(fd)
    }

    fn health(&self) -> Result<()> {
        let fd = self.connect()?;
        send(fd.as_raw_fd(), &[6, 0, 1], MsgFlags::MSG_NOSIGNAL)?;
        assert_eq!(response(&fd)?, vec![0]);
        // HEALTH has no settlement frame: EOF follows completion/slot release.
        assert!(response(&fd)?.is_empty());
        Ok(())
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

struct Running {
    child: Child,
    events: Receiver<String>,
    reader: Option<JoinHandle<()>>,
}

impl Running {
    fn event(&mut self, expected: &str) -> Result<()> {
        let deadline = Instant::now() + Duration::from_secs(4);
        loop {
            let line = self
                .events
                .recv_timeout(deadline.saturating_duration_since(Instant::now()))?;
            assert!(!line.contains("synthetic-secret-never-log"));
            let value: serde_json::Value = serde_json::from_str(&line)?;
            if value["event"] == expected {
                return Ok(());
            }
        }
    }

    fn signal(&self, signal: Signal) -> Result<()> {
        kill(Pid::from_raw(self.child.id().try_into()?), signal)?;
        Ok(())
    }

    fn exit(&mut self) -> Result<ExitStatus> {
        let deadline = Instant::now() + Duration::from_secs(4);
        loop {
            if let Some(status) = self.child.try_wait()? {
                return Ok(status);
            }
            if Instant::now() >= deadline {
                bail!("synthetic agent did not exit after drain");
            }
            std::thread::sleep(Duration::from_millis(5));
        }
    }
}

impl Drop for Running {
    fn drop(&mut self) {
        if self.child.try_wait().ok().flatten().is_none() {
            let _ = self.child.kill();
        }
        let _ = self.child.wait();
        if let Some(reader) = self.reader.take() {
            let _ = reader.join();
        }
    }
}

fn response(fd: &OwnedFd) -> Result<Vec<u8>> {
    let mut packet = [0; 16];
    let length = recv(fd.as_raw_fd(), &mut packet, MsgFlags::MSG_TRUNC)?;
    assert!(length <= packet.len());
    Ok(packet[..length].to_vec())
}

#[test]
fn idle_term_and_int_exit_cleanly_at_serial_and_parallel_capacity() -> Result<()> {
    for capacity in [1, 4] {
        for signal in [Signal::SIGTERM, Signal::SIGINT] {
            let fixture = Fixture::new()?;
            let mut running = fixture.start(capacity)?;
            fixture.health()?;
            running.signal(signal)?;
            running.event("agent.shutdown.completed")?;
            assert!(running.exit()?.success());
            assert!(fixture.connect().is_err());
        }
    }
    Ok(())
}

#[test]
fn repeated_signals_close_listener_but_drain_all_admitted_requests() -> Result<()> {
    for capacity in [1, 4] {
        let fixture = Fixture::new()?;
        let mut running = fixture.start(capacity)?;
        fixture.health()?;
        running.event("agent.dispatch.admitted")?; // Earlier HEALTH has settled.
        let mut admitted = Vec::new();
        for _ in 0..capacity {
            admitted.push(fixture.connect()?);
            running
                .event("agent.dispatch.admitted")
                .context("original slot must be admitted")?;
        }
        running.signal(Signal::SIGTERM)?;
        running.event("agent.shutdown.draining")?;
        assert!(running.child.try_wait()?.is_none());
        assert!(fixture.connect().is_err());
        running.signal(Signal::SIGINT)?;
        running.signal(Signal::SIGTERM)?;
        for fd in admitted {
            send(fd.as_raw_fd(), &[6, 0, 1], MsgFlags::MSG_NOSIGNAL)
                .context("send admitted HEALTH after repeated signals")?;
            assert_eq!(
                response(&fd).context("read admitted HEALTH after repeated signals")?,
                vec![0]
            ); // Original semantics, no fabricated receipt.
        }
        running.event("agent.shutdown.completed")?;
        assert!(running.exit()?.success());
    }
    Ok(())
}

#[test]
fn serial_successor_waits_in_kernel_instead_of_racing_a_legacy_reply() -> Result<()> {
    use nix::errno::Errno;
    let fixture = Fixture::new()?;
    let mut running = fixture.start(1)?;
    let first = fixture.connect()?;
    running.event("agent.dispatch.admitted")?;
    let queued = fixture.connect()?;
    send(queued.as_raw_fd(), &[6, 0, 1], MsgFlags::MSG_NOSIGNAL)?;
    setsockopt(&queued, ReceiveTimeout, &TimeVal::new(0, 100_000))?;
    let mut packet = [0; 16];
    assert_eq!(
        recv(queued.as_raw_fd(), &mut packet, MsgFlags::MSG_TRUNC),
        Err(Errno::EAGAIN)
    );
    send(first.as_raw_fd(), &[6, 0, 1], MsgFlags::MSG_NOSIGNAL)?;
    assert_eq!(response(&first)?, vec![0]);
    assert!(response(&first)?.is_empty());
    setsockopt(&queued, ReceiveTimeout, &TimeVal::new(3, 0))?;
    assert_eq!(response(&queued)?, vec![0]);
    assert!(response(&queued)?.is_empty());
    running.signal(Signal::SIGTERM)?;
    running.event("agent.shutdown.completed")?;
    assert!(running.exit()?.success());
    Ok(())
}

#[test]
fn restart_uses_existing_checked_stale_socket_cleanup() -> Result<()> {
    let fixture = Fixture::new()?;
    for _ in 0..2 {
        let mut running = fixture.start(1)?;
        fixture.health()?;
        running.signal(Signal::SIGTERM)?;
        running.event("agent.shutdown.completed")?;
        assert!(running.exit()?.success());
        assert!(
            fs::symlink_metadata(fixture.0.join("agent.sock"))?
                .file_type()
                .is_socket()
        );
    }
    Ok(())
}
