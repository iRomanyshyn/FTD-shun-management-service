//! Bounded connection workers and inventory-owned, fail-closed device guards.

use std::collections::BTreeMap;
use std::net::Ipv4Addr;
use std::sync::atomic::{AtomicU8, Ordering};
use std::sync::mpsc::{self, SyncSender, TrySendError};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;

use anyhow::{Context, Result, bail};

pub(super) const MAX_WORKERS: usize = 10;

pub(super) fn worker_count(value: Option<&str>) -> Result<usize> {
    let value = value.unwrap_or("1");
    let count = value
        .parse::<usize>()
        .context("agent concurrency must be an integer")?;
    if !(1..=MAX_WORKERS).contains(&count) || count.to_string() != value {
        bail!("FTD_SHUN_AGENT_MAX_CONCURRENT_DEVICES must be a canonical integer between 1 and 10");
    }
    Ok(count)
}

pub(super) struct DeviceGuards {
    locks: BTreeMap<u16, Arc<Mutex<()>>>,
}

impl DeviceGuards {
    pub(super) fn new(devices: impl IntoIterator<Item = (u16, Ipv4Addr)>) -> Self {
        let mut endpoints = BTreeMap::new();
        let locks = devices
            .into_iter()
            .map(|(id, address)| {
                let lock = endpoints
                    .entry(address)
                    .or_insert_with(|| Arc::new(Mutex::new(())));
                (id, Arc::clone(lock))
            })
            .collect();
        Self { locks }
    }

    pub(super) fn run<T>(&self, device: u16, handler: impl FnOnce() -> T) -> Option<T> {
        let lock = self.locks.get(&device)?;
        // Never queue behind the same device or treat a panicked handler as idle.
        let _guard = lock.try_lock().ok()?;
        Some(handler())
    }
}

pub(super) struct Pool<T> {
    slots: Vec<Slot<T>>,
    _workers: Vec<JoinHandle<()>>,
}

const IDLE: u8 = 0;
const BUSY: u8 = 1;
const STOPPED: u8 = 2;

struct Slot<T> {
    sender: SyncSender<T>,
    state: Arc<AtomicU8>,
}

impl<T: Send + 'static> Pool<T> {
    pub(super) fn new(count: usize, handler: impl Fn(T) + Send + Sync + 'static) -> Result<Self> {
        if !(1..=MAX_WORKERS).contains(&count) {
            bail!("invalid bounded connection worker count");
        }
        let handler = Arc::new(handler);
        let mut workers = Vec::with_capacity(count);
        let mut slots = Vec::with_capacity(count);
        for index in 0..count {
            let (sender, receiver) = mpsc::sync_channel::<T>(1);
            let state = Arc::new(AtomicU8::new(IDLE));
            slots.push(Slot {
                sender,
                state: Arc::clone(&state),
            });
            let handler = Arc::clone(&handler);
            workers.push(std::thread::Builder::new().name(format!("ftd-connection-{index}")).spawn(move || {
                loop {
                    let Ok(work) = receiver.recv() else { return };
                    if std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| handler(work))).is_err() {
                        state.store(STOPPED, Ordering::Release);
                        eprintln!("{{\"event\":\"agent.worker.failed\",\"reason\":\"handler panicked; worker not replaced\"}}");
                        return;
                    }
                    state.store(IDLE, Ordering::Release);
                }
            }).context("could not start bounded connection worker")?);
        }
        Ok(Self {
            slots,
            _workers: workers,
        })
    }

    pub(super) fn submit(&self, mut work: T) -> std::result::Result<(), TrySendError<T>> {
        let mut stopped = 0;
        for slot in &self.slots {
            if slot
                .state
                .compare_exchange(IDLE, BUSY, Ordering::AcqRel, Ordering::Acquire)
                .is_err()
            {
                stopped += usize::from(slot.state.load(Ordering::Acquire) == STOPPED);
                continue;
            }
            match slot.sender.try_send(work) {
                Ok(()) => return Ok(()),
                Err(TrySendError::Disconnected(item)) => {
                    slot.state.store(STOPPED, Ordering::Release);
                    stopped += 1;
                    work = item;
                }
                Err(TrySendError::Full(item)) => work = item,
            }
        }
        // At most one assigned/running connection per slot, never a backlog behind a busy worker.
        Err(if stopped == self.slots.len() {
            TrySendError::Disconnected(work)
        } else {
            TrySendError::Full(work)
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Barrier;
    use std::time::{Duration, Instant};

    fn submit_when_idle<T: Send + 'static>(pool: &Pool<T>, mut item: T) -> Result<()> {
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            match pool.submit(item) {
                Ok(()) => return Ok(()),
                Err(TrySendError::Full(value)) if Instant::now() < deadline => {
                    item = value;
                    std::thread::yield_now();
                }
                Err(_) => bail!("synthetic pool did not become idle"),
            }
        }
    }

    #[test]
    fn configuration_is_bounded_canonical_and_default_serial() -> Result<()> {
        assert_eq!(worker_count(None)?, 1);
        for count in 1..=MAX_WORKERS {
            assert_eq!(worker_count(Some(&count.to_string()))?, count);
        }
        for value in [
            "",
            "0",
            "11",
            "-1",
            "+2",
            "01",
            "4 ",
            " 4",
            "4\n",
            "true",
            "999999999999999999999",
        ] {
            assert!(worker_count(Some(value)).is_err());
        }
        assert!(Pool::<usize>::new(0, |_| {}).is_err());
        assert!(Pool::<usize>::new(11, |_| {}).is_err());
        Ok(())
    }

    #[test]
    fn guards_reject_unknown_busy_and_alias_ids_but_allow_other_devices() -> Result<()> {
        let guards = DeviceGuards::new([
            (1, Ipv4Addr::new(192, 0, 2, 1)),
            (2, Ipv4Addr::new(192, 0, 2, 2)),
            (3, Ipv4Addr::new(192, 0, 2, 1)),
        ]);
        assert_eq!(guards.run(99, || true), None);
        let result = guards.run(1, || {
            assert_eq!(guards.run(1, || true), None);
            assert_eq!(guards.run(3, || true), None);
            assert_eq!(guards.run(2, || true), Some(true));
        });
        assert!(result.is_some());
        assert_eq!(guards.run(3, || true), Some(true));
        Ok(())
    }

    #[test]
    fn panic_does_not_release_device_as_safe_or_poison_other_devices() {
        let guards = DeviceGuards::new([
            (1, Ipv4Addr::new(192, 0, 2, 1)),
            (2, Ipv4Addr::new(192, 0, 2, 2)),
        ]);
        let _ = std::panic::catch_unwind(|| {
            guards.run(1, || std::panic::resume_unwind(Box::new("synthetic")))
        });
        assert_eq!(guards.run(1, || true), None);
        assert_eq!(guards.run(2, || true), Some(true));
    }

    #[test]
    fn pool_bounds_active_handlers_without_backlog_or_threads_per_request() -> Result<()> {
        let count = 4;
        let barrier = Arc::new(Barrier::new(count + 1));
        let release = Arc::new(Barrier::new(count + 1));
        let started = Arc::clone(&barrier);
        let finish = Arc::clone(&release);
        let (done, received) = mpsc::channel();
        let pool = Pool::new(count, move |item: usize| {
            if item < count {
                started.wait();
                finish.wait();
            }
            let _ = done.send(item);
        })?;
        for item in 0..count {
            pool.submit(item)?;
        }
        barrier.wait();
        assert!(matches!(pool.submit(999), Err(TrySendError::Full(999))));
        release.wait();
        for _ in 0..count {
            received.recv_timeout(Duration::from_secs(2))?;
        }
        drop(pool);
        Ok(())
    }

    #[test]
    fn slow_device_does_not_delay_other_device_and_duplicate_rejects() -> Result<()> {
        let guards = Arc::new(DeviceGuards::new([
            (1, Ipv4Addr::new(192, 0, 2, 1)),
            (2, Ipv4Addr::new(192, 0, 2, 2)),
        ]));
        let (started, ready) = mpsc::channel();
        let (release, wait) = mpsc::channel();
        let wait = Arc::new(Mutex::new(wait));
        let (done, received) = mpsc::channel();
        let pool = Pool::new(2, move |device| {
            let result = guards.run(device, || {
                if device == 1 {
                    let _ = started.send(());
                    if let Ok(wait) = wait.lock() {
                        let _ = wait.recv();
                    }
                }
                true
            });
            let _ = done.send((device, result));
        })?;
        pool.submit(1)?;
        ready.recv_timeout(Duration::from_secs(2))?;
        pool.submit(1)?;
        assert_eq!(received.recv_timeout(Duration::from_secs(2))?, (1, None));
        submit_when_idle(&pool, 2)?;
        assert_eq!(
            received.recv_timeout(Duration::from_secs(2))?,
            (2, Some(true))
        );
        release.send(())?;
        assert_eq!(
            received.recv_timeout(Duration::from_secs(2))?,
            (1, Some(true))
        );
        Ok(())
    }

    #[test]
    fn panicked_worker_is_stopped_not_automatically_replaced() -> Result<()> {
        let pool = Pool::new(1, |_: usize| {
            std::panic::resume_unwind(Box::new("synthetic"))
        })?;
        pool.submit(1)?;
        let deadline = Instant::now() + Duration::from_secs(2);
        while pool.slots[0].state.load(Ordering::Acquire) != STOPPED {
            if Instant::now() >= deadline {
                bail!("synthetic worker did not stop");
            }
            std::thread::yield_now();
        }
        assert!(matches!(pool.submit(2), Err(TrySendError::Disconnected(2))));
        assert_eq!(pool._workers.len(), 1);
        Ok(())
    }

    #[tokio::test]
    async fn fixed_workers_share_live_tokio_timers_without_blocking_the_driver() -> Result<()> {
        let runtime = tokio::runtime::Handle::current();
        let (done, received) = mpsc::channel();
        let pool = Pool::new(2, move |item: usize| {
            let _context = runtime.enter();
            let result = runtime.block_on(tokio::time::timeout(Duration::from_secs(1), async {
                tokio::time::sleep(Duration::from_millis(5)).await;
                item
            }));
            let _ = done.send(result);
        })?;
        pool.submit(1)?;
        pool.submit(2)?;
        let mut items = tokio::task::spawn_blocking(move || -> Result<Vec<usize>> {
            Ok(vec![
                received.recv_timeout(Duration::from_secs(2))??,
                received.recv_timeout(Duration::from_secs(2))??,
            ])
        })
        .await??;
        items.sort();
        assert_eq!(items, [1, 2]);
        Ok(())
    }
}
