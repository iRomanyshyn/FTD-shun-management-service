// Deterministic presentation checks: no browser, sockets, API or device access.
const assert = require("node:assert/strict");
const test = require("node:test");
const { refreshPresentation, queuePresentation, failureText } = require("../../static/freshness.js");

const initial = () => ({ refresh_schedule_mode: "per_device", refresh_enabled: true,
  refresh_in_progress: false, pending_refresh_device_count: 0, active_device_count: 0,
  next_baseline_refresh: "baseline", next_interactive_refresh: "interactive",
  devices: { "1": { state: "ready", active: false, refresh_pending: false } }, device_cycles: {} });
const timing = (baseline = 270, interactive = 30) => (key) => ({ baseline, interactive })[key] ?? null;

test('operator scheduling pauses belong to Status while Queue keeps work counts', () => {
  const status = { ...initial(), managed_addition_controls: { available: true, imports: { paused: true }, restoration: { paused: true } }, queue: { counts: { QUEUED: 16 } } };
  assert.equal(queuePresentation(status).activity, 'waiting');
  assert.equal(queuePresentation(status).badge, '16');
  assert.equal(refreshPresentation(status, timing()).badge, '2 paused');
  assert.equal(refreshPresentation(status, timing()).activity, 'paused');
  assert.equal(refreshPresentation(status, timing()).attention, false);
  assert.match(refreshPresentation(status, timing()).description, /Imports paused.*Automatic restoration paused/);
  status.managed_addition_controls.restoration.paused = false;
  assert.equal(refreshPresentation(status, timing()).badge, '1 paused');
  status.pending_refresh_device_count = 1;
  assert.equal(refreshPresentation(status, timing()).badge, '30s · 1 paused');
  status.queue.counts.UNVERIFIED = 1;
  assert.equal(queuePresentation(status).attention, true);
  status.queue.counts.RUNNING = 1;
  assert.equal(queuePresentation(status).activity, 'busy');
  status.managed_addition_controls.available = false;
  assert.doesNotMatch(refreshPresentation(status, timing()).badge, /paused/);
});

test('pending confirmation is neutral waiting, not a failed or completed write', () => {
  const view = queuePresentation({ queue: { counts: { AWAITING_CONFIRMATION: 16 } } });
  assert.equal(view.activity, 'waiting');
  assert.equal(view.attention, false);
  assert.equal(view.badge, '16');
  assert.match(view.description, /16 awaiting a complete device read; not yet confirmed/);
});

test('known observation outcomes do not masquerade as running or failed work', () => {
  const view = queuePresentation({ queue: { counts: { OBSERVED_PRESENT: 16, CONFIRMED_ABSENT: 2 } } });
  assert.equal(view.activity, 'idle');
  assert.equal(view.attention, false);
  assert.equal(view.badge, '');
});

test('a sampled absence timer requests another check, never promises a successful write', () => {
  const status = { deferred_confirmation: { '1': { held: false, mutations_paused: false, retry_in_seconds: 4.1 } },
    queue: { counts: { CONFIRMED_ABSENT: 16 } } };
  const view = queuePresentation(status);
  assert.equal(view.activity, 'waiting');
  assert.equal(view.attention, false);
  assert.equal(view.badge, '…');
  assert.match(view.description, /absence check eligible in 5s/);
  status.deferred_confirmation['1'].retry_in_seconds = 0;
  assert.match(queuePresentation(status).description, /waiting for an available device session/);
  status.deferred_confirmation['1'].held = true;
  assert.doesNotMatch(queuePresentation(status).description, /Absence check eligible/);
});

test('a device error is still visible during pending confirmation', () => {
  const view = queuePresentation({ devices: { '1': { state: 'error' } },
    queue: { counts: { AWAITING_CONFIRMATION: 16 } } });
  assert.equal(view.attention, true);
  assert.match(view.description, /open Status/);
});

test('pending settlement is not a fresh read or a refresh completion', () => {
  for (const action of ['settling_pending_additions', 'awaiting_confirmation']) {
    const status = { ...initial(), pending_refresh_device_count: 1, refresh_in_progress: true,
      devices: { '1': { state: 'refreshing', active: true, refresh_pending: true } },
      device_cycles: { '1': { action, awaiting_confirmation: 16 } } };
    const view = refreshPresentation(status, timing(270, 0));
    assert.equal(view.activity, 'waiting');
    assert.notEqual(view.phase, 'reading');
    assert.match(view.timing, /current device operation/);
  }
});

test('reviewed historical unknowns do not warn or change an idle queue icon', () => {
  const view = queuePresentation({ queue: { counts: { VERIFIED: 15, UNVERIFIED: 1 },
    attention_counts: { FAILED: 0, UNVERIFIED: 0 }, reviewed_history: { total: 1, items: [] } } });
  assert.equal(view.attention, false);
  assert.equal(view.activity, 'idle');
  assert.equal(view.badge, '');
  assert.match(view.description, /0 need attention/);
});

test('a later unknown or failed operation still warns alongside reviewed history', () => {
  const view = queuePresentation({ queue: { counts: { FAILED: 1, UNVERIFIED: 2 },
    attention_counts: { FAILED: 1, UNVERIFIED: 1 }, reviewed_history: { total: 1, items: [] } } });
  assert.equal(view.attention, true);
  assert.equal(view.badge, '!2');
});

test('missing or inconsistent review metadata retains the original unknown warning', () => {
  for (const metadata of [{}, { attention_counts: { FAILED: 0, UNVERIFIED: 0 } },
      { attention_counts: { FAILED: 0, UNVERIFIED: 0 }, reviewed_history: { total: 0, items: [] } },
      { attention_counts: { FAILED: 0, UNVERIFIED: -1 }, reviewed_history: { total: 2, items: [] } }]) {
    assert.equal(queuePresentation({ queue: { counts: { UNVERIFIED: 1 }, ...metadata } }).attention, true);
  }
});

test('brief storage retry is neutral; persistent retry and device errors remain actionable', () => {
  const status = { ...initial(), execution_recovery: { state: 'retrying', attempts: 1, retry_at: 'interactive' } };
  const view = refreshPresentation(status, timing());
  assert.equal(view.phase, 'recovering');
  assert.equal(view.activity, 'waiting');
  assert.equal(view.attention, false);
  assert.equal(view.timing, 'in 30s');
  assert.match(view.description, /retrying automatically/);
  assert.doesNotMatch(view.timing, /4m/);
  const queue = queuePresentation({ ...status, queue: { counts: { QUEUED: 2 } } });
  assert.equal(queue.attention, false);
  assert.match(queue.description, /import is retained/);
  status.execution_recovery.reason = 'Storage busy';
  status.last_error = 'Storage busy';
  assert.equal(refreshPresentation(status, timing()).attention, false);
  status.execution_recovery.attempts = 3;
  assert.equal(refreshPresentation(status, timing()).attention, true);
  assert.equal(queuePresentation(status).attention, true);
  status.execution_recovery.attempts = 1;
  status.last_error = 'Different genuine error';
  assert.equal(refreshPresentation(status, timing()).attention, true);
  status.last_error = 'Storage busy';
  status.devices['1'].last_error = 'Device timeout';
  assert.equal(refreshPresentation(status, timing()).attention, true);
  assert.equal(queuePresentation({ ...status, queue: { counts: { QUEUED: 2 } } }).attention, true);
  delete status.devices['1'].last_error;
  delete status.execution_recovery.attempts;
  assert.equal(refreshPresentation(status, timing()).attention, true, 'Missing retry metadata never hides warnings');
});

test('stopped execution gives operator guidance without pretending monitoring continues', () => {
  const status = { ...initial(), refresh_enabled: false, execution_recovery: { state: 'stopped',
    operator_action: 'Inspect retained outcomes; do not cancel or reimport.' } };
  const view = refreshPresentation(status, timing());
  assert.equal(view.phase, 'stopped');
  assert.equal(view.activity, 'paused');
  assert.match(view.timing, /no refresh is scheduled/);
  assert.match(view.timingHelp, /do not cancel or reimport/);
  const queue = queuePresentation(status);
  assert.equal(queue.activity, 'paused');
  assert.equal(queue.attention, true);
  assert.doesNotMatch(queue.description, /monitoring continues/);
});

test('staged additions are device work; their group observation is a real read phase', () => {
  const status = { ...initial(), refresh_in_progress: true, active_device_count: 1,
    devices: { '1': { state: 'refreshing', active: true } },
    device_cycles: { '1': { action: 'stage_addition', pending_verification: 3 } } };
  assert.equal(refreshPresentation(status, timing()).phase, 'working');
  status.device_cycles['1'].action = 'verify_addition_batch';
  assert.equal(refreshPresentation(status, timing()).phase, 'reading');
});

test('fetch and response-body network failures retain data with a readable retry notice', () => {
  for (const error of [new TypeError('NetworkError when attempting to fetch resource'),
      { name: 'NetworkError' }, { name: 'TimeoutError' }, { name: 'AbortError' }]) {
    assert.match(failureText(error), /Keeping last data and retrying automatically/);
    assert.doesNotMatch(failureText(error), /NetworkError/);
  }
});

test('authentication and action errors keep their actual explanation', () => {
  assert.equal(failureText(new Error('Authentication is required.')), 'Authentication is required.');
  assert.equal(failureText(new Error('Outcome unconfirmed; inspect the original request.')),
    'Outcome unconfirmed; inspect the original request.');
});

test('a whole import remains visible while its rolling device queue is temporarily empty', () => {
  const status = { queue: { counts: {}, imports: { tasks: [{ active: true, outstanding: 32000, attention: 0 }] } } };
  const view = queuePresentation(status);
  assert.equal(view.activity, 'waiting');
  assert.equal(view.badge, '…');
  assert.match(view.description, /rolling dispatch/);
});

test('whole-import attention is independent of materialized jobs', () => {
  const view = queuePresentation({ queue: { counts: {}, imports: { tasks: [{ outstanding: 0, attention: 1 }] } } });
  assert.equal(view.attention, true);
  assert.match(view.badge, /!1/);
});

test('inactive import history does not keep the queue waiting or erase unresolved attention', () => {
  const task = { active: false, outstanding: 32000, attention: 0 };
  const status = { queue: { counts: { VERIFIED: 5000 }, imports: { tasks: [task] } } };
  assert.equal(queuePresentation(status).activity, 'idle');
  assert.equal(queuePresentation(status).badge, '');
  assert.doesNotMatch(queuePresentation(status).description, /rolling dispatch/);
  task.attention = 1;
  assert.equal(queuePresentation(status).attention, true);
  assert.match(queuePresentation(status).badge, /!1/);
});

test('a held device marks pending import work for attention instead of pretending it is only waiting', () => {
  const view = queuePresentation({ devices: { '1': { state: 'error', last_error: 'Retained device hold' } },
    queue: { counts: {}, imports: { tasks: [{ active: true, outstanding: 32000, attention: 0 }] } } });
  assert.equal(view.attention, true);
  assert.match(view.badge, /!/);
  assert.match(view.description, /open Status/);
});

test("requested refresh displays its eligibility, not the unrelated 4m 30s periodic timer", () => {
  const status = { ...initial(), pending_refresh_device_count: 1 };
  const view = refreshPresentation(status, timing());
  assert.equal(view.phase, "waiting");
  assert.equal(view.timingLabel, "Requested refresh");
  assert.equal(view.timing, "eligible in 30s");
  assert.equal(view.badge, "30s");
  assert.ok(!view.summary.includes("4m 30s"));
});

test("request submission has immediate feedback before the server reply", () => {
  const view = refreshPresentation(initial(), timing(), true);
  assert.equal(view.phase, "requesting");
  assert.equal(view.activity, "waiting");
  assert.match(view.summary, /Sending refresh request/);
  assert.equal(view.timingLabel, "Requested refresh");
});

test("a zero request deadline waits for evidence instead of announcing completion", () => {
  const status = { ...initial(), pending_refresh_device_count: 1 };
  const view = refreshPresentation(status, timing(270, 0));
  assert.equal(view.phase, "waiting");
  assert.equal(view.badge, "1 waiting");
  assert.match(view.timing, /waiting for an available device/);
  assert.doesNotMatch(view.summary, /completed|current|success/);
});

for (const action of ["opening_session", "priority_snapshot", "final_snapshot"]) {
  test(`an actual ${action} has reading feedback without a speculative ETA`, () => {
    const status = initial();
    Object.assign(status, { pending_refresh_device_count: 1, active_device_count: 1,
      refresh_in_progress: true, device_cycles: { "1": { action } } });
    status.devices["1"].active = true;
    const view = refreshPresentation(status, timing());
    assert.equal(view.phase, "reading");
    assert.equal(view.activity, "busy");
    assert.equal(view.timingLabel, "Requested refresh");
    assert.equal(view.badge, "");
    assert.doesNotMatch(view.timing, /30s|4m|5m/);
  });
}

test("requested refresh waits for a mutation checkpoint rather than pretending to read", () => {
  const status = initial();
  Object.assign(status, { pending_refresh_device_count: 1, refresh_in_progress: true,
    device_cycles: { "1": { action: "add_and_verify" } } });
  status.devices["1"].active = true;
  const view = refreshPresentation(status, timing(270, 0));
  assert.equal(view.activity, "waiting");
  assert.match(view.timing, /current device operation/);
});

test("queue work alone is distinct from reading device data", () => {
  const status = { ...initial(), refresh_in_progress: true,
    device_cycles: { "1": { action: "remove_and_verify" } } };
  status.devices["1"].active = true;
  const view = refreshPresentation(status, timing());
  assert.equal(view.phase, "working");
  assert.equal(view.activity, "busy");
  assert.equal(view.timingLabel, "Next periodic check");
});

test("only an updated idle server snapshot returns to the recalculated five-minute periodic timer", () => {
  const view = refreshPresentation(initial(), timing(300));
  assert.equal(view.phase, "idle");
  assert.equal(view.activity, "idle");
  assert.equal(view.badge, "");
  assert.equal(view.timingLabel, "Next periodic check");
  assert.equal(view.timing, "in 5m 00s");
  assert.match(view.timingHelp, /recalculated after a successful device read/);
});

test("a due periodic timer is eligibility, not invented new observations", () => {
  const view = refreshPresentation(initial(), timing(0));
  assert.equal(view.phase, "due");
  assert.equal(view.activity, "waiting");
  assert.match(view.timing, /waiting for device/);
  assert.doesNotMatch(view.summary, /completed|current|success/);
});

test("an unavailable device keeps attention visible alongside coalesced demand", () => {
  const status = { ...initial(), pending_refresh_device_count: 2, last_error: "A device is held." };
  status.devices["1"].state = "error";
  const view = refreshPresentation(status, timing(270, 0));
  assert.equal(view.attention, true);
  assert.match(view.description, /2 device refresh request\(s\) pending/);
  assert.match(view.description, /A device is held/);
  assert.equal(view.activity, "waiting");
});

test("old sweep profiles still distinguish queued and checkpoint-pending work", () => {
  for (const state of ["queued", "checkpoint_pending"]) {
    const status = { ...initial(), refresh_schedule_mode: undefined, interactive_refresh_state: state };
    assert.equal(refreshPresentation(status, timing()).phase, "waiting");
  }
});

test("local failure flags timing as last reported, without fabricated progress", () => {
  const view = refreshPresentation(initial(), timing(), false, "Authentication is required.");
  assert.equal(view.attention, true);
  assert.match(view.timingHelp, /last reported/);
  assert.match(view.description, /Authentication is required/);
});

test("disabled devices do not create activity or an enabled-device count", () => {
  const status = initial();
  status.devices["1"] = { state: "disabled", active: true, refresh_pending: true };
  const view = refreshPresentation(status, timing());
  assert.equal(view.activity, "idle");
  assert.equal(view.pending, 0);
  assert.equal(view.summary, "No enabled devices");
});

test("retained successful jobs leave the queue trigger quiet", () => {
  const view = queuePresentation({ queue: { counts: { VERIFIED: 500, NOOP: 20 } } });
  assert.equal(view.activity, "idle");
  assert.equal(view.attention, false);
  assert.equal(view.badge, "");
});

test("queued and executing work have distinct trigger states", () => {
  assert.equal(queuePresentation({ queue: { counts: { QUEUED: 3 } } }).activity, "waiting");
  const view = queuePresentation({ queue: { counts: { RUNNING: 1, QUEUED: 2 } } });
  assert.equal(view.activity, "busy");
  assert.equal(view.badge, "3");
  assert.match(view.description, /1 running; 2 queued/);
});

test("attention and ongoing work are independent instead of hiding each other", () => {
  const view = queuePresentation({ queue: { counts: { RUNNING: 1, UNVERIFIED: 1 } } });
  assert.equal(view.activity, "busy");
  assert.equal(view.attention, true);
  assert.equal(view.badge, "1 · !1");
});

test("paused mutations are not falsely displayed as running", () => {
  const view = queuePresentation({ queue: { counts: { QUEUED: 2 }, mutations_suspended: true } });
  assert.equal(view.activity, "paused");
  assert.equal(view.attention, true);
  assert.match(view.description, /monitoring continues/);
});

test("large badges stay compact while accessible descriptions retain full counts", () => {
  const view = queuePresentation({ queue: { counts: { QUEUED: 10000, FAILED: 250 } } });
  assert.equal(view.badge, "99+ · !99+");
  assert.match(view.description, /10000 queued; 250 need attention/);
});

test("unknown submission and worker failures are visible outside the queue panel", () => {
  for (const status of [{ managed_restoration_error: "Restoration failed." },
    { managed_removal_worker_error: "Removal failed." }]) {
    assert.equal(queuePresentation(status).attention, true);
  }
  const view = queuePresentation({}, true, "Operation result is unknown.");
  assert.equal(view.activity, "waiting");
  assert.equal(view.attention, true);
  assert.match(view.description, /result is unknown/);
});
