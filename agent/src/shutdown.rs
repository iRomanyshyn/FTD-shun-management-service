//! Process-local stop request; never cancellation or device-result authority.

use std::os::fd::AsFd;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use anyhow::{Result, bail};
use nix::errno::Errno;
use nix::poll::{PollFd, PollFlags, poll};

#[derive(Clone, Default)]
pub(super) struct Shutdown(Arc<AtomicBool>);

impl Shutdown {
    pub(super) fn request(&self) {
        self.0.store(true, Ordering::Release);
    }

    pub(super) fn requested(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }

    pub(super) fn wait_readable(&self, listener: &impl AsFd) -> Result<bool> {
        while !self.requested() {
            let mut descriptors = [PollFd::new(listener.as_fd(), PollFlags::POLLIN)];
            match poll(&mut descriptors, 100u16) {
                Ok(_) => {
                    if self.requested() {
                        return Ok(false);
                    }
                    let events = descriptors[0].revents().unwrap_or(PollFlags::POLLERR);
                    if events
                        .intersects(PollFlags::POLLERR | PollFlags::POLLHUP | PollFlags::POLLNVAL)
                    {
                        bail!("agent listener polling failed");
                    }
                    if events.contains(PollFlags::POLLIN) {
                        return Ok(true);
                    }
                }
                Err(Errno::EINTR) => continue,
                Err(error) => return Err(error.into()),
            }
        }
        Ok(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use nix::sys::socket::{AddressFamily, MsgFlags, SockFlag, SockType, send, socketpair};
    use std::os::fd::AsRawFd;
    use std::time::{Duration, Instant};

    #[test]
    fn stop_wakes_an_idle_wait_and_stays_requested() -> Result<()> {
        let (reader, _writer) = socketpair(
            AddressFamily::Unix,
            SockType::SeqPacket,
            None,
            SockFlag::SOCK_CLOEXEC,
        )?;
        let stop = Shutdown::default();
        let other = stop.clone();
        let started = Instant::now();
        let waiter = std::thread::spawn(move || other.wait_readable(&reader));
        stop.request();
        stop.request();
        assert!(
            !waiter
                .join()
                .map_err(|_| anyhow::anyhow!("waiter panicked"))??
        );
        assert!(stop.requested() && started.elapsed() < Duration::from_secs(2));
        Ok(())
    }

    #[test]
    fn readable_is_not_admission_after_stop_and_poll_errors_fail_closed() -> Result<()> {
        let (reader, writer) = socketpair(
            AddressFamily::Unix,
            SockType::SeqPacket,
            None,
            SockFlag::SOCK_CLOEXEC,
        )?;
        let stop = Shutdown::default();
        send(writer.as_raw_fd(), &[1], MsgFlags::MSG_NOSIGNAL)?;
        assert!(stop.wait_readable(&reader)?);
        stop.request();
        assert!(!stop.wait_readable(&reader)?);
        drop(writer);
        assert!(Shutdown::default().wait_readable(&reader).is_err());
        Ok(())
    }
}
