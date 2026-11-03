//! Fixed, argument-free CLI diagnostics. Never verification or retry evidence.

use std::future::Future;
use std::time::{Duration, Instant};

use anyhow::Result;
use serde_json::{Value, json};

#[derive(Clone, Copy)]
pub(super) enum Phase {
    FullRead,
    TargetRead,
    Add,
    Remove,
}

impl Phase {
    fn label(self) -> &'static str {
        match self {
            Self::FullRead => "full_read",
            Self::TargetRead => "target_read",
            Self::Add => "add",
            Self::Remove => "remove",
        }
    }
}

#[derive(Default)]
struct Aggregate {
    calls: u64,
    returned: u64,
    errors: u64,
    cancelled: u64,
    elapsed: Duration,
}

#[derive(Default)]
pub(super) struct CliTiming {
    phases: [Aggregate; 4],
}

struct Sample<'a> {
    aggregate: &'a mut Aggregate,
    started: Instant,
    returned: Option<bool>,
}

impl Drop for Sample<'_> {
    fn drop(&mut self) {
        self.aggregate.calls += 1;
        self.aggregate.elapsed += self.started.elapsed();
        match self.returned {
            Some(true) => self.aggregate.returned += 1,
            Some(false) => self.aggregate.errors += 1,
            None => self.aggregate.cancelled += 1,
        }
    }
}

impl CliTiming {
    pub(super) async fn measure<T>(
        &mut self,
        phase: Phase,
        operation: impl Future<Output = Result<T>>,
    ) -> Result<T> {
        let mut sample = Sample {
            aggregate: &mut self.phases[phase as usize],
            started: Instant::now(),
            returned: None,
        };
        let result = operation.await;
        sample.returned = Some(result.is_ok());
        result
    }

    pub(super) fn report(&self) -> Value {
        let mut phases = serde_json::Map::new();
        for phase in [
            Phase::FullRead,
            Phase::TargetRead,
            Phase::Add,
            Phase::Remove,
        ] {
            let aggregate = &self.phases[phase as usize];
            phases.insert(
                phase.label().to_owned(),
                json!({
                    "calls": aggregate.calls,
                    "returned": aggregate.returned,
                    "errors": aggregate.errors,
                    "cancelled": aggregate.cancelled,
                    "seconds": (aggregate.elapsed.as_secs_f64() * 1000.0).round() / 1000.0,
                }),
            );
        }
        Value::Object(phases)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn fixed_phases_preserve_results_without_recording_arguments_or_errors() -> Result<()> {
        let mut timing = CliTiming::default();
        assert_eq!(
            timing.measure(Phase::TargetRead, async { Ok(17) }).await?,
            17
        );
        let error = timing
            .measure::<()>(Phase::Add, async {
                anyhow::bail!("synthetic secret, command, IP and output must not enter timing")
            })
            .await;
        assert!(error.is_err());
        timing.measure(Phase::FullRead, async { Ok(()) }).await?;
        timing.measure(Phase::Remove, async { Ok(()) }).await?;
        let report = timing.report();
        assert_eq!(report.as_object().map(|phases| phases.len()), Some(4));
        for label in ["full_read", "target_read", "add", "remove"] {
            assert_eq!(report[label]["calls"], 1);
            assert_eq!(report[label]["cancelled"], 0);
            assert_eq!(report[label]["returned"], u64::from(label != "add"));
            assert_eq!(report[label]["errors"], u64::from(label == "add"));
        }
        assert!(!report.to_string().contains("synthetic"));
        assert_eq!(CliTiming::default().report()["add"]["calls"], 0);
        Ok(())
    }

    #[tokio::test]
    async fn outer_timeout_counts_cancelled_call_not_returned_success() -> Result<()> {
        let mut timing = CliTiming::default();
        assert!(
            tokio::time::timeout(
                Duration::from_millis(5),
                timing.measure(Phase::Add, std::future::pending::<Result<()>>()),
            )
            .await
            .is_err()
        );
        timing.measure(Phase::Add, async { Ok(()) }).await?;
        let report = timing.report();
        assert_eq!(report["add"]["calls"], 2);
        assert_eq!(report["add"]["returned"], 1);
        assert_eq!(report["add"]["errors"], 0);
        assert_eq!(report["add"]["cancelled"], 1);
        assert!(report["add"]["seconds"].as_f64().is_some_and(|v| v > 0.0));
        assert_eq!(report["target_read"]["calls"], 0);
        Ok(())
    }

    #[test]
    fn unpolled_future_is_not_a_cli_attempt() {
        let mut timing = CliTiming::default();
        drop(timing.measure(Phase::Add, async { Ok(()) }));
        assert_eq!(timing.report()["add"]["calls"], 0);
    }
}
