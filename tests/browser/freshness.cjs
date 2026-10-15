// Uses real Chromium, production templates/JS, and a local synthetic BFF.
// No Docker, FTD connection, user environment file, or new npm package is used.
const assert = require("node:assert/strict");
const { spawn, execFileSync } = require("node:child_process");
const { once } = require("node:events");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const root = path.resolve(__dirname, "../..");
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const future = (seconds) => new Date(Date.now() + seconds * 1000).toISOString();
const renderScript = `
import json, sys
from ftd_shun_manager.web import Identity, templates
p = json.load(sys.stdin)
shun = dict(ip="198.51.100.10", device_id=1, device_hostname="lab-ftd", interface="outside",
            first_seen_at="2026-10-15T10:00:00Z", last_seen_at="2026-10-15T10:00:00Z")
event = dict(timestamp="2026-10-15T10:00:00Z", event_type="FIXTURE_EVENT_" + str(p["generation"]),
             device_hostname="lab-ftd", actor_display_name="Test Operator", actor_subject="test", ip=shun["ip"])
print(templates.get_template(p["template"]).render(identity=Identity("test", "Test Operator", ("Operator",)),
    csrf_token="fixture-token", shuns=[shun], refresh=p["refresh"], search_query=p["query"],
    search_results=None, trusted_policy_ips=frozenset(), recent_events=[event],
    ip=shun["ip"], events=[event], is_trusted_policy_ip=False))
`;

const initial = () => ({
  instance_id: "instance-1", status_revision: 1, data_revision: 1, cycle_revision: 1,
  cycle_id: 1, cycle_outcome: "success", refresh_enabled: true, refresh_in_progress: false,
  last_successful_refresh: "2026-10-15T10:00:00Z", last_error: null,
  next_baseline_refresh: future(180), next_interactive_refresh: future(60),
  interactive_refresh_state: "idle", interactive_min_interval_seconds: 60,
  baseline_interval_seconds: 300, history_retention_days: 366,
  trusted_auto_remove_ips: [], trusted_auto_remove_ip_count: 0,
  queue: { revision: 0, items: [], counts: {}, next_eligible_at: null },
  devices: { "1": { hostname: "lab-ftd", state: "ready", stale: false,
    last_successful_refresh: "2026-10-15T10:00:00Z", last_error: null } },
});

async function connectPage(debugOrigin, url) {
  const target = await fetch(`${debugOrigin}/json/new?${encodeURIComponent("about:blank")}`, { method: "PUT" }).then((r) => r.json());
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await once(socket, "open");
  let id = 0;
  const pending = new Map();
  const errors = [];
  socket.addEventListener("message", ({ data }) => {
    const value = JSON.parse(data);
    if (value.method === "Runtime.exceptionThrown") errors.push(value.params.exceptionDetails);
    if (pending.has(value.id)) {
      const { resolve, reject } = pending.get(value.id);
      pending.delete(value.id);
      if (value.error) reject(new Error(value.error.message)); else resolve(value.result);
    }
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const next = ++id;
    pending.set(next, { resolve, reject });
    socket.send(JSON.stringify({ id: next, method, params }));
  });
  const evaluate = async (expression) => {
    const result = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const until = async (expression) => {
    const deadline = Date.now() + 8000;
    while (Date.now() < deadline) {
      if (await evaluate(expression)) return;
      await delay(50);
    }
    throw new Error(`Timed out: ${expression}`);
  };
  await call("Page.enable");
  await call("Runtime.enable");
  await call("Emulation.setFocusEmulationEnabled", { enabled: true });
  await call("Page.navigate", { url });
  await until("Boolean(document.querySelector('[data-refresh-request]'))");
  return { call, evaluate, until, errors, close: async () => {
    assert.deepEqual(errors, [], "No browser JavaScript exceptions");
    await fetch(`${debugOrigin}/json/close/${target.id}`);
    socket.close();
  } };
}

test("refresh interaction in real Chromium", { timeout: 60000 }, async (t) => {
  let status = initial();
  let generation = 1;
  let failStatus = false;
  let failPost = false;
  let holdStatus = null;
  let postCount = 0;
  let executionCount = 0;
  let pageReads = 0;
  let failQueueReply = false;
  const removalKeys = [];
  const stamp = () => ({ ...status, server_time: new Date().toISOString() });
  const complete = (outcome = "success") => {
    status.status_revision += 1;
    status.cycle_revision += 1;
    status.cycle_outcome = outcome;
    status.refresh_in_progress = false;
    status.interactive_refresh_state = "idle";
    status.next_baseline_refresh = future(300);
    status.next_interactive_refresh = future(60);
    if (outcome === "success") status.data_revision += 1;
    else status.last_error = "Repeated synthetic device failure";
    generation += 1;
  };
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://fixture");
    response.setHeader("Cache-Control", "no-store");
    if (url.pathname === "/static/freshness.js") {
      response.setHeader("Content-Type", "text/javascript");
      response.end(fs.readFileSync(path.join(root, "static/freshness.js")));
    } else if (url.pathname === "/refresh-status") {
      if (holdStatus) await holdStatus;
      response.setHeader("Content-Type", "application/json");
      response.statusCode = failStatus ? 503 : 200;
      response.end(JSON.stringify(stamp()));
    } else if (url.pathname === "/refresh" && request.method === "POST") {
      let body = "";
      for await (const chunk of request) body += chunk;
      assert.ok(body.includes("fixture-token"), "POST carries rendered CSRF token");
      postCount += 1;
      if (!status.refresh_in_progress) executionCount += 1;
      response.setHeader("Content-Type", "application/json");
      response.statusCode = failPost ? 503 : 200;
      if (!failPost) {
        const priority = status.refresh_in_progress && status.session_cycles_enabled;
        status.refresh_in_progress = true;
        status.interactive_refresh_state = priority ? "checkpoint_pending" : "running";
        if (priority) {
          status.priority_refresh_available = false;
          status.device_cycle.priority_state = "waiting_for_checkpoint";
        }
        status.status_revision += 1;
      }
      response.end(JSON.stringify(stamp()));
    } else if (url.pathname.startsWith("/devices/") && request.method === "POST") {
      let body = "";
      for await (const chunk of request) body += chunk;
      assert.ok(body.includes("fixture-token"));
      const key = body.match(/name="request_id"\r\n\r\n([^\r\n]+)/)[1];
      removalKeys.push(key);
      if (!status.queue.items.length) {
        status.queue.items.push({ id: "job-1", device_id: 1, hostname: "lab-ftd", ip: "198.51.100.10",
          state: "QUEUED", requested_at: future(0), requests: [{ id: key, actor_subject: "test",
            actor_display_name: "Test Operator", source: "manual", state: "ACTIVE" }] });
        status.queue.counts = { QUEUED: 1 };
      }
      status.queue.revision += 1;
      status.status_revision += 1;
      response.setHeader("Content-Type", "application/json");
      response.statusCode = failQueueReply ? 503 : 200;
      response.end(JSON.stringify(failQueueReply ? { detail: "Admission reply lost. Retry the same request." } : stamp()));
    } else if (url.pathname.startsWith("/operations/") && request.method === "POST") {
      for await (const _ of request) { /* drain form data */ }
      status.queue.items[0].state = "CANCELLED";
      status.queue.items[0].requests[0].state = "CANCELLED";
      status.queue.counts = { CANCELLED: 1 };
      status.queue.revision += 1;
      status.status_revision += 1;
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify(stamp()));
    } else if (url.pathname === "/" || url.pathname.startsWith("/shuns/")) {
      pageReads += 1;
      const payload = { refresh: stamp(), generation, query: url.searchParams.get("q") || "",
        template: url.pathname === "/" ? "index.html" : "detail.html" };
      response.setHeader("Content-Type", "text/html; charset=utf-8");
      response.end(execFileSync("python3", ["-c", renderScript], {
        cwd: root, input: JSON.stringify(payload), encoding: "utf8",
      }));
    } else {
      response.statusCode = 404;
      response.end();
    }
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const origin = `http://127.0.0.1:${server.address().port}`;
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ftd-refresh-browser-"));
  const browser = spawn(process.env.CHROMIUM || "chromium-browser", [
    "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--disable-background-networking", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
  ], { stdio: ["ignore", "ignore", "pipe"] });
  try {
    const websocket = await new Promise((resolve, reject) => {
      const deadline = setTimeout(() => reject(new Error("Chromium startup timed out")), 10000);
      let stderr = "";
      browser.stderr.on("data", (data) => {
        stderr += data;
        const match = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/);
        if (match) { clearTimeout(deadline); resolve(match[1]); }
      });
      browser.once("exit", (code) => { clearTimeout(deadline); reject(new Error(`Chromium exited ${code}: ${stderr}`)); });
      browser.once("error", reject);
    });
    const debugOrigin = websocket.replace(/^ws:/, "http:").split("/devtools/")[0];
    const wake = (page) => page.evaluate("document.dispatchEvent(new Event('visibilitychange'))");

    await t.test("one click; slow status; partial updates preserve fields and expanded history", async () => {
      const page = await connectPage(debugOrigin, `${origin}/?q=198.51.100`);
      try {
        await page.until("document.querySelector('[data-refresh-request]').textContent.includes('Request refresh (')");
        assert.equal(postCount, 0);
        await page.evaluate("document.querySelector('#ip-search').value='203.0.113'; document.querySelector('#recent-events-details').open=true");
        status.next_interactive_refresh = null;
        status.status_revision += 1;
        await wake(page);
        await page.until("!document.querySelector('[data-refresh-request]').disabled");
        let release;
        holdStatus = new Promise((resolve) => { release = resolve; });
        await wake(page);
        await delay(100);
        await page.evaluate("document.querySelector('[data-refresh-request]').click()");
        await delay(100);
        assert.equal(postCount, 0, "Manual POST waits for in-flight status request");
        holdStatus = null;
        release();
        await page.until("document.querySelector('[data-refresh-request]').textContent==='Refreshing…'");
        assert.equal(postCount, 1);
        const scrollBefore = await page.evaluate("window.scrollTo(0,180); window.scrollY");
        complete();
        await wake(page);
        await page.until("document.querySelector('#recent-events').textContent.includes('FIXTURE_EVENT_2')");
        assert.equal(await page.evaluate("document.querySelector('#ip-search').value"), "203.0.113");
        assert.equal(await page.evaluate("document.querySelector('#recent-events-details').open"), true);
        assert.equal(await page.evaluate("location.search"), "?q=198.51.100");
        assert.equal(await page.evaluate("window.scrollY"), scrollBefore);
      } finally { await page.close(); }
    });

    await t.test("same errors update again; recovery and restart update without navigation", async () => {
      const page = await connectPage(debugOrigin, `${origin}/shuns/198.51.100.10`);
      try {
        await page.evaluate("document.querySelector('[name=confirm_ip]').value='198.51.100'; document.querySelector('[name=confirm_ip]').focus()");
        complete("failed");
        await wake(page);
        await page.until(`document.querySelector('#ip-history').textContent.includes('FIXTURE_EVENT_${generation}')`);
        const before = pageReads;
        complete("failed");
        await wake(page);
        await page.until(`document.querySelector('#ip-history').textContent.includes('FIXTURE_EVENT_${generation}')`);
        assert.ok(pageReads > before, "Identical failure still updates data by revision");
        assert.equal(await page.evaluate("document.querySelector('[name=confirm_ip]').value"), "198.51.100");
        assert.equal(await page.evaluate("document.activeElement.name"), "confirm_ip");
        failStatus = true;
        await wake(page);
        await page.until("document.querySelector('[data-refresh-message]').textContent.includes('unavailable')");
        failStatus = false;
        status = initial();
        status.instance_id = "instance-2";
        generation += 1;
        await wake(page);
        await page.until(`document.querySelector('#ip-history').textContent.includes('FIXTURE_EVENT_${generation}')`);
        assert.equal(await page.evaluate("document.querySelector('[name=confirm_ip]').value"), "198.51.100");
      } finally { await page.close(); }
    });

    await t.test("imminent baseline; two tabs observe one cycle; failed POST can retry", async () => {
      status = initial();
      status.instance_id = "instance-3";
      status.next_baseline_refresh = future(30);
      status.next_interactive_refresh = null;
      const first = await connectPage(debugOrigin, origin);
      const second = await connectPage(debugOrigin, origin);
      try {
        await first.until("document.querySelector('[data-refresh-request]').textContent.startsWith('Scheduled refresh (')");
        status.next_baseline_refresh = future(180);
        status.status_revision += 1;
        await Promise.all([wake(first), wake(second)]);
        await first.until("!document.querySelector('[data-refresh-request]').disabled");
        await second.until("!document.querySelector('[data-refresh-request]').disabled");
        const before = executionCount;
        await Promise.all([first.evaluate("document.querySelector('[data-refresh-request]').click()"),
          second.evaluate("document.querySelector('[data-refresh-request]').click()")]);
        await first.until("document.querySelector('[data-refresh-request]').textContent==='Refreshing…'");
        await second.until("document.querySelector('[data-refresh-request]').textContent==='Refreshing…'");
        assert.equal(executionCount, before + 1);
        complete();
        await Promise.all([wake(first), wake(second)]);
        for (const page of [first, second]) {
          await page.until(`document.querySelector('#recent-events').textContent.includes('FIXTURE_EVENT_${generation}')`);
        }
        status.next_interactive_refresh = null;
        status.status_revision += 1;
        await wake(first);
        await first.until("!document.querySelector('[data-refresh-request]').disabled");
        failPost = true;
        await first.evaluate("document.querySelector('[data-refresh-request]').click()");
        await first.until("document.querySelector('[data-refresh-message]').textContent.includes('unavailable')");
        assert.equal(await first.evaluate("document.querySelector('[data-refresh-request]').disabled"), false);
        failPost = false;
        await first.evaluate("document.querySelector('[data-refresh-request]').click()");
        await first.until("document.querySelector('[data-refresh-request]').textContent==='Refreshing…'");
      } finally { await first.close(); await second.close(); }
    });
    await t.test("queued admission survives lost reply and DOM refresh; cancellation updates progress", async () => {
      status = initial();
      status.instance_id = "instance-4";
      const page = await connectPage(debugOrigin, origin);
      try {
        failQueueReply = true;
        await page.evaluate("document.querySelector('[data-queue-form]').requestSubmit()");
        await page.until("document.querySelector('[data-refresh-message]').textContent.includes('Admission reply lost')");
        failQueueReply = false;
        await wake(page);
        await page.until("document.querySelector('[data-operation-queue]').textContent.includes('QUEUED')");
        assert.equal(await page.evaluate("document.querySelectorAll('[data-operation-queue] tr').length"), 1);
        // The partial render produces a fresh form UUID, but an unknown
        // admission retries with the original operation key.
        await page.evaluate("document.querySelector('[data-queue-form]').requestSubmit()");
        await page.until("document.querySelector('[data-refresh-message]').textContent==='Refresh completed.'");
        assert.equal(removalKeys.length, 2);
        assert.equal(removalKeys[0], removalKeys[1]);
        await page.evaluate("document.querySelector('[data-operation-cancel]').click()");
        await page.until("document.querySelector('[data-queue-completed]').textContent.includes('CANCELLED')");
        assert.equal(await page.evaluate("document.querySelectorAll('[data-operation-queue] tr').length"), 0);
        assert.equal(await page.evaluate("document.querySelector('#queue-results-details').open"), false);
        assert.equal(await page.evaluate("document.querySelectorAll('[data-operation-cancel]').length"), 0);
      } finally { await page.close(); }
    });
    await t.test("priority refresh is usable during a batch and updates data before cycle completion", async () => {
      status = initial();
      status.instance_id = "session-cycle-instance";
      status.session_cycles_enabled = true;
      status.refresh_in_progress = true;
      status.device_cycle = { device_id: 1, action: "remove_and_verify", ip: "198.51.100.10",
        completed: 4, limit: 16, priority_state: "none", budget_deferred: false };
      const page = await connectPage(debugOrigin, `${origin}/?q=198.51`);
      try {
        await page.until("document.querySelector('[data-cycle-progress]').textContent.includes('4 items completed')");
        assert.equal(await page.evaluate("document.querySelector('[data-refresh-request]').disabled"), true);
        await page.evaluate("document.querySelector('#ip-search').value='203.0.113'; document.querySelector('#recent-events-details').open=true");
        status.priority_refresh_available = true;
        status.next_interactive_refresh = null;
        status.status_revision += 1;
        await wake(page);
        await page.until("document.querySelector('[data-refresh-request]').textContent==='Request priority refresh'");
        const beforePosts = postCount;
        const beforeExecutions = executionCount;
        await page.evaluate("document.querySelector('[data-refresh-request]').click()");
        await page.until("document.querySelector('[data-refresh-request]').textContent.includes('waiting for current operation')");
        assert.equal(postCount, beforePosts + 1);
        assert.equal(executionCount, beforeExecutions, "No extra session/cycle requested");
        status.device_cycle.completed = 5;
        status.device_cycle.priority_state = "satisfied";
        status.interactive_refresh_state = "running";
        status.next_interactive_refresh = future(60);
        status.data_revision += 1;
        status.status_revision += 1;
        generation += 1;
        await wake(page);
        await page.until(`document.querySelector('#recent-events').textContent.includes('FIXTURE_EVENT_${generation}')`);
        assert.equal(await page.evaluate("document.querySelector('#ip-search').value"), "203.0.113");
        assert.equal(await page.evaluate("document.querySelector('#recent-events-details').open"), true);
        assert.equal(status.refresh_in_progress, true);
        assert.equal(status.cycle_revision, 1, "Snapshot publication does not complete the batch");
        assert.equal(await page.evaluate("document.querySelector('[data-refresh-request]').disabled"), true);
      } finally { await page.close(); }
    });
    await t.test("completed results collapse, errors remain separate, and long histories stay bounded", async () => {
      status = initial();
      status.instance_id = "grouped-queue-instance";
      const job = (id, state) => ({ id, state, hostname: "lab-ftd", device_id: 1,
        ip: "198.51.100.10", requested_at: future(-60),
        completed_at: ["QUEUED", "RUNNING"].includes(state) ? null : future(-10), requests: [] });
      status.queue = { revision: 1, next_eligible_at: future(40),
        counts: { QUEUED: 1, RUNNING: 1, FAILED: 1, UNVERIFIED: 1, VERIFIED: 225 },
        items: [job("pending", "QUEUED"), job("running", "RUNNING"),
          job("failed", "FAILED"), job("unknown", "UNVERIFIED"),
          ...Array.from({ length: 25 }, (_, index) => job(`done-${index}`, "VERIFIED"))] };
      const page = await connectPage(debugOrigin, origin);
      try {
        await page.until("document.querySelector('[data-queue-summary]').textContent.includes('2 active operations')");
        assert.equal(await page.evaluate("document.querySelectorAll('[data-operation-queue] tr').length"), 2);
        assert.equal(await page.evaluate("document.querySelectorAll('[data-queue-attention] tr').length"), 2);
        assert.equal(await page.evaluate("document.querySelector('[data-queue-attention-section]').hidden"), false);
        assert.equal(await page.evaluate("document.querySelectorAll('[data-queue-completed] tr').length"), 20);
        assert.equal(await page.evaluate("document.querySelector('#queue-results-details').open"), false);
        assert.ok(await page.evaluate("document.querySelector('[data-queue-completed-note]').textContent.includes('20 of 225')"));
        assert.equal(await page.evaluate("document.querySelector('[data-cycle-progress]').hidden"), true);
        assert.equal(await page.evaluate("document.querySelector('[data-queue-completed] a').getAttribute('href')"), "/shuns/198.51.100.10");
        await page.evaluate("document.querySelector('#queue-results-details').open=true");
        status.queue.items[0].state = "VERIFIED";
        status.queue.items[1].state = "VERIFIED";
        status.queue.counts = { FAILED: 1, UNVERIFIED: 1, VERIFIED: 227 };
        status.queue.revision += 1;
        status.status_revision += 1;
        status.data_revision += 1;
        await wake(page);
        await page.until("document.querySelector('[data-queue-summary]').textContent==='Queue is empty.'");
        assert.equal(await page.evaluate("document.querySelector('[data-queue-active-table]').hidden"), true);
        assert.equal(await page.evaluate("document.querySelectorAll('[data-operation-queue] tr').length"), 0);
        assert.equal(await page.evaluate("document.querySelector('#queue-results-details').open"), true);
        assert.equal(await page.evaluate("document.querySelectorAll('[data-queue-completed] tr').length"), 20);
      } finally { await page.close(); }
    });
    await t.test("request progress counts real jobs, keeps uncertain outcomes distinct, and clears on completion", async () => {
      status = initial();
      status.instance_id = "request-progress-instance";
      status.session_cycles_enabled = true;
      status.refresh_in_progress = true;
      status.device_cycle = { device_id: 1, action: "opening_session", completed: 0,
        limit: 16, priority_state: "none", budget_deferred: false };
      const job = (index) => ({ id: `work-${index}`, device_id: 1, hostname: "lab-ftd",
        ip: `198.51.100.${index}`, state: "QUEUED", requested_at: future(-5), requests: [] });
      const request = { id: "batch-request", actor_subject: "test", actor_display_name: "Test Operator",
        source: "manual", total: 3, processed: 0, counts: { QUEUED: 3 } };
      status.queue = { revision: 1, counts: { QUEUED: 3, VERIFIED: 2 }, items: [job(1), job(2), job(3)],
        progress: { requests: [request], total_requests: 1, limit: 20 } };
      const page = await connectPage(debugOrigin, origin);
      try {
        await page.until("document.querySelector('[data-request-progress] progress')?.max===3");
        assert.equal(await page.evaluate("document.querySelector('[data-request-progress] progress').value"), 0);
        assert.ok(await page.evaluate("document.querySelector('[data-request-progress]').textContent.includes('0 / 3 jobs processed')"));
        request.processed = 2;
        request.counts = { VERIFIED: 1, UNVERIFIED: 1, RUNNING: 1 };
        status.queue.counts = { VERIFIED: 3, UNVERIFIED: 1, RUNNING: 1 };
        status.queue.items.forEach((item, index) => { item.state = ["VERIFIED", "UNVERIFIED", "RUNNING"][index]; });
        status.device_cycle.action = "remove_and_verify";
        status.device_cycle.completed = 1;
        status.queue.revision += 1;
        status.status_revision += 1;
        await wake(page);
        await page.until("document.querySelector('[data-request-progress] progress').value===2");
        assert.equal(await page.evaluate("document.querySelector('[data-request-progress] progress').max"), 3, "Cycle cap 16 is not the denominator");
        assert.ok(await page.evaluate("document.querySelector('[data-request-progress]').textContent.includes('1 unverified')"));
        assert.equal(await page.evaluate("document.querySelector('.request-progress').dataset.warning"), "true");
        assert.equal(await page.evaluate("document.querySelector('.operation-running-progress').hasAttribute('value')"), false);
        await page.evaluate("window.previousBar=document.querySelector('[data-request-progress] progress'); window.previousRunning=document.querySelector('.operation-running-progress')");
        status.device_cycle.action = "priority_snapshot";
        status.status_revision += 1;
        await wake(page);
        await page.until("document.querySelector('[data-cycle-progress]').textContent.includes('Reading priority snapshot')");
        assert.equal(await page.evaluate("document.querySelector('[data-request-progress] progress')===window.previousBar"), true, "Unchanged progress does not restart the indicator");
        assert.equal(await page.evaluate("document.querySelector('.operation-running-progress')===window.previousRunning"), true);
        status.queue.progress = { requests: [], total_requests: 0, limit: 20 };
        status.queue.items[2].state = "NOOP";
        status.queue.counts = { VERIFIED: 3, UNVERIFIED: 1, NOOP: 1 };
        status.queue.revision += 1;
        status.status_revision += 1;
        status.refresh_in_progress = false;
        await wake(page);
        await page.until("document.querySelector('[data-request-progress-section]').hidden");
        assert.equal(await page.evaluate("document.querySelectorAll('[data-request-progress] progress').length"), 0);
        assert.equal(await page.evaluate("document.querySelector('[data-queue-attention-section]').hidden"), false);
      } finally { await page.close(); }
    });
  } finally {
    browser.kill("SIGTERM");
    await Promise.race([once(browser, "exit"), delay(3000)]);
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
    fs.rmSync(profile, { recursive: true, force: true });
  }
});
