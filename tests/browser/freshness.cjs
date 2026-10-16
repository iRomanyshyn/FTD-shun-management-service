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
from ftd_shun_manager.import_preview import paginate_preview, parse_blocklist, summarize_preview
from ftd_shun_manager.web import Identity, templates
p = json.load(sys.stdin)
policy_entries = (p.get("policy") or {}).get("entries", [])
enabled_ips = frozenset(entry["ip"] for entry in policy_entries if entry["enabled"])
disabled_ips = frozenset(entry["ip"] for entry in policy_entries if not entry["enabled"])
preview = None
if p.get("submitted"):
    parsed = parse_blocklist(p["source_text"])
    preview = paginate_preview(summarize_preview(parsed, dict(policy_revision=1, devices=[dict(id=1,hostname="lab-ftd")],
        addresses=[dict(ip=ip,protected=ip=="198.51.100.10",devices=[dict(id=1,hostname="lab-ftd",already_shunned=ip=="203.0.113.20")]) for ip in parsed["ips"]])), p.get("page", 1))
shun = dict(ip="198.51.100.10", device_id=1, device_hostname="lab-ftd FIXTURE_EVENT_" + str(p["generation"]), interface="outside",
            first_seen_at="2026-10-15T10:00:00Z", last_seen_at="2026-10-15T10:00:00Z")
event = dict(timestamp="2026-10-15T10:00:00Z", event_type="FIXTURE_EVENT_" + str(p["generation"]),
             device_hostname="lab-ftd", actor_display_name="Test Operator", actor_subject="test", ip=shun["ip"])
print(templates.get_template(p["template"]).render(identity=Identity("test", "Test Operator", ("Operator",)),
    csrf_token="fixture-token", shuns=[shun], refresh=p["refresh"], search_query=p["query"],
    search_results=None, trusted_policy_ips=enabled_ips, disabled_policy_ips=disabled_ips, recent_events=p.get("history", {}).get("events", [event]),
    pagination=p.get("history", {}), anchored_history=bool(p.get("anchor")),
    ip=shun["ip"], events=[event], is_trusted_policy_ip=shun["ip"] in enabled_ips,
    is_disabled_policy_ip=shun["ip"] in disabled_ips, policy=p.get("policy"),
    source_text=p.get("source_text", ""), batch_label=p.get("label", ""), batch_reason=p.get("reason", ""),
    selected_devices=[1] if p.get("submitted") else [], preview=preview, preview_error=None,
    devices=[dict(id=1,hostname="lab-ftd",enabled=True),dict(id=2,hostname="disabled-ftd",enabled=False)],
    active_page="imports" if p["template"] == "import-preview.html" else "protected" if p["template"] == "protected-ips.html" else "history" if p["template"] == "history.html" else "shuns",
    auto_request=p["template"] not in ("protected-ips.html", "history.html", "import-preview.html")))
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
      const { resolve, reject, deadline } = pending.get(value.id);
      clearTimeout(deadline);
      pending.delete(value.id);
      if (value.error) reject(new Error(value.error.message)); else resolve(value.result);
    }
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const next = ++id;
    const deadline = setTimeout(() => {
      pending.delete(next);
      reject(new Error(`CDP timed out: ${method} ${(params.expression || "").slice(0, 100)}`));
    }, 15000);
    pending.set(next, { resolve, reject, deadline });
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

test("refresh interaction in real Chromium", { timeout: 90000 }, async (t) => {
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
  let policy = { revision: 1, limit: 1000, entries: [] };
  let policyPosts = 0;
  let previewPosts = 0;
  let historyRows = [];
  const appendHistory = () => {
    const sequence = historyRows.length + 1;
    historyRows.push({ id: `00000000-0000-4000-8000-${sequence.toString(16).padStart(12, "0")}`,
      timestamp: "2026-10-15T10:00:00Z", event_type: `HISTORY_EVENT_${sequence}`,
      device_hostname: "lab-ftd", actor_display_name: "Test Operator", ip: "198.51.100.10" });
  };
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
    if (url.pathname === "/static/app.css") {
      response.setHeader("Content-Type", "text/css");
      response.end(fs.readFileSync(path.join(root, "static/app.css")));
    } else if (url.pathname === "/static/freshness.js") {
      response.setHeader("Content-Type", "text/javascript");
      response.end(fs.readFileSync(path.join(root, "static/freshness.js")));
    } else if (url.pathname === "/static/import-preview.js") {
      response.setHeader("Content-Type", "text/javascript");
      response.end(fs.readFileSync(path.join(root, "static/import-preview.js")));
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
    } else if (url.pathname.startsWith("/protected-ips/") && request.method === "POST") {
      let body = "";
      for await (const chunk of request) body += chunk;
      const field = (name) => body.match(new RegExp(`name="${name}"\\r\\n\\r\\n([^\\r\\n]*)`))?.[1] || "";
      assert.equal(field("csrf"), "fixture-token");
      policyPosts += 1;
      response.setHeader("Content-Type", "application/json");
      if (Number(field("revision")) !== policy.revision) {
        response.statusCode = 409;
        response.end(JSON.stringify({ detail: "Protected IPs changed. Reload saved values before retrying." }));
        return;
      }
      const ip = field("ip");
      if (url.pathname.endsWith("/delete")) {
        assert.equal(field("confirm_ip"), ip);
        policy.entries = policy.entries.filter((entry) => entry.ip !== ip);
      } else {
        const entry = { ip, name: field("name"), comment: field("comment"), enabled: field("enabled") === "true",
          active_devices: 0, last_auto_removed_at: null };
        const index = policy.entries.findIndex((item) => item.ip === ip);
        if (index === -1) policy.entries.push(entry); else policy.entries[index] = entry;
      }
      policy.revision += 1;
      status.policy_revision = policy.revision;
      status.status_revision += 1;
      response.end(JSON.stringify(stamp()));
    } else if (["/", "/history", "/protected-ips", "/imports"].includes(url.pathname) || url.pathname.startsWith("/shuns/")) {
      pageReads += 1;
      let previewFields = {};
      if (url.pathname === "/imports" && request.method === "POST") {
        let body = "";
        for await (const chunk of request) body += chunk;
        const fields = new URLSearchParams(body);
        assert.equal(fields.get("csrf"), "fixture-token");
        assert.deepEqual(fields.getAll("device_ids"), ["1"]);
        previewPosts += 1;
        previewFields = { submitted: true, source_text: fields.get("text"), label: fields.get("label"), reason: fields.get("reason"), page: Number(fields.get("page") || 1) };
      }
      let history;
      if (url.pathname === "/history") {
        const anchor = url.searchParams.get("anchor");
        const last = anchor ? historyRows.findIndex((row) => row.id === anchor) : historyRows.length - 1;
        const rows = historyRows.slice(0, last + 1).reverse();
        const pages = Math.max(1, Math.ceil(rows.length / 100));
        const current = Math.min(Number(url.searchParams.get("page") || 1), pages);
        history = { page: current, pages, total: rows.length, page_size: 100,
          anchor: rows[0]?.id || null, events: rows.slice((current - 1) * 100, current * 100) };
      }
      const payload = { refresh: stamp(), generation, query: url.searchParams.get("q") || "",
        history, anchor: url.searchParams.get("anchor"),
        ...previewFields,
        policy, template: url.pathname === "/" ? "index.html" : url.pathname === "/history" ? "history.html"
          : url.pathname === "/protected-ips" ? "protected-ips.html" : url.pathname === "/imports" ? "import-preview.html" : "detail.html" };
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

    await t.test("one click; slow status; partial updates preserve fields and open status menu", async () => {
      const page = await connectPage(debugOrigin, `${origin}/?q=198.51.100`);
      try {
        await page.until("document.querySelector('[data-refresh-request]').textContent.includes('Request refresh (')");
        assert.equal(postCount, 0);
        await page.evaluate("document.querySelector('#ip-search').value='203.0.113'; document.querySelector('#status-menu').open=true");
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
        await page.until("document.querySelector('#active-shuns').textContent.includes('FIXTURE_EVENT_2')");
        assert.equal(await page.evaluate("document.querySelector('#ip-search').value"), "203.0.113");
        assert.equal(await page.evaluate("document.querySelector('#status-menu').open"), true);
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
          await page.until(`document.querySelector('#active-shuns').textContent.includes('FIXTURE_EVENT_${generation}')`);
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
        await page.evaluate("document.querySelector('#ip-search').value='203.0.113'; document.querySelector('#status-menu').open=true");
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
        await page.until(`document.querySelector('#active-shuns').textContent.includes('FIXTURE_EVENT_${generation}')`);
        assert.equal(await page.evaluate("document.querySelector('#ip-search').value"), "203.0.113");
        assert.equal(await page.evaluate("document.querySelector('#status-menu').open"), true);
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
        await page.evaluate("document.querySelector('#queue-menu > summary').click()");
        await page.until("document.querySelector('#queue-menu').open");
        assert.ok(await page.evaluate("(() => { const bar=document.querySelector('.request-progress progress'); return bar.getBoundingClientRect().top-bar.previousElementSibling.getBoundingClientRect().bottom>=12; })()"), "Progress has visible spacing from text");
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
    await t.test("compact menus dismiss accessibly and failures remain visible while closed", async () => {
      status = initial();
      status.last_error = "Synthetic failure requiring attention";
      status.devices["1"].stale = true;
      status.devices["1"].state = "error";
      status.queue.counts = { UNVERIFIED: 1 };
      const page = await connectPage(debugOrigin, origin);
      try {
        assert.equal(await page.evaluate("document.querySelector('#status-menu').open || document.querySelector('#queue-menu').open"), false);
        assert.ok(await page.evaluate("document.querySelector('[data-refresh-warning]').getBoundingClientRect().height>0"));
        assert.ok(await page.evaluate("document.querySelector('[data-queue-warning]').getBoundingClientRect().height>0"));
        await page.call("Page.bringToFront");
        await page.evaluate("document.querySelector('#status-menu > summary').focus()");
        assert.equal(await page.evaluate("document.activeElement===document.querySelector('#status-menu > summary')"), true);
        await page.call("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r" });
        await page.call("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
        await page.until("document.querySelector('#status-menu').open");
        await page.evaluate("document.querySelector('#queue-menu > summary').click()");
        await page.until("document.querySelector('#queue-menu').open && !document.querySelector('#status-menu').open");
        await page.call("Emulation.setDeviceMetricsOverride", { width: 375, height: 800, deviceScaleFactor: 1, mobile: false });
        assert.ok(await page.evaluate("(() => { const box=document.querySelector('#queue-menu .utility-panel').getBoundingClientRect(); return box.left>=0 && box.right<=innerWidth; })()"), "Panel fits narrow viewport");
        await page.call("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape" });
        await page.until("!document.querySelector('#queue-menu').open");
        assert.equal(await page.evaluate("document.activeElement===document.querySelector('#queue-menu > summary')"), true);
        await page.evaluate("document.querySelector('#status-menu > summary').click()");
        await page.until("document.querySelector('#status-menu').open");
        await page.evaluate("document.querySelector('h1').click()");
        assert.equal(await page.evaluate("document.querySelector('#status-menu').open"), false);
      } finally { await page.close(); }
    });
    await t.test("policy drafts retain original revision and per-IP values; CRUD updates without Cisco hints", async () => {
      status = initial();
      status.policy_revision = 1;
      policy = { revision: 1, limit: 1000, entries: [10, 11].map((last) => ({ ip: `198.51.100.${last}`,
        name: `Office ${last}`, comment: "Existing", enabled: true, active_devices: 0, last_auto_removed_at: null })) };
      const hints = postCount;
      const page = await connectPage(debugOrigin, `${origin}/protected-ips`);
      try {
        await page.evaluate(`(() => { const form=document.getElementById('edit-policy-form-198.51.100.10'); form.closest('details').open=true;
          form.elements.name.value='Unsaved office'; form.elements.name.dispatchEvent(new Event('input',{bubbles:true})); })()`);
        policy.entries[1].name = "Other administrator edit";
        policy.revision = status.policy_revision = 2;
        status.status_revision += 1;
        await wake(page);
        await page.until("document.querySelector('#protected-policy').textContent.includes('Other administrator edit')");
        assert.equal(await page.evaluate("document.getElementById('edit-policy-form-198.51.100.10').elements.name.value"), "Unsaved office");
        assert.equal(await page.evaluate("document.getElementById('edit-policy-form-198.51.100.10').elements.revision.value"), "1");
        assert.equal(await page.evaluate("document.getElementById('edit-policy-form-198.51.100.11').elements.name.value"), "Other administrator edit");
        await page.evaluate("document.getElementById('edit-policy-form-198.51.100.10').requestSubmit()");
        await page.until("document.querySelector('[data-refresh-message]').textContent.includes('Protected IPs changed')");
        assert.equal(policy.entries[0].name, "Office 10", "Stale draft did not overwrite the stored policy");
        await page.call("Page.navigate", { url: `${origin}/protected-ips` });
        await page.until("document.getElementById('edit-policy-form-198.51.100.10')?.elements.revision.value==='2'");
        await page.evaluate(`(() => { const form=document.getElementById('edit-policy-form-198.51.100.10'); form.closest('details').open=true;
          form.elements.name.value='Saved office'; form.elements.enabled.checked=false;
          form.elements.name.dispatchEvent(new Event('input',{bubbles:true})); form.requestSubmit(); })()`);
        await page.until("document.querySelector('#protected-policy').textContent.includes('Saved office')");
        assert.equal(policy.entries[0].enabled, false);
        await page.evaluate(`(() => { const form=document.getElementById('add-policy-form'); form.closest('details').open=true;
          form.elements.ip.value='203.0.113.20'; form.elements.name.value='<img src=x onerror=alert(1)>';
          form.elements.name.dispatchEvent(new Event('input',{bubbles:true})); form.requestSubmit(); })()`);
        await page.until("document.querySelector('#protected-policy').textContent.includes('203.0.113.20')");
        assert.equal(await page.evaluate("document.querySelectorAll('#protected-policy img').length"), 0, "Untrusted label remains escaped");
        await page.evaluate(`(() => { const form=document.getElementById('delete-policy-form-203.0.113.20'); form.closest('details').open=true;
          form.elements.confirm_ip.value='203.0.113.20'; form.requestSubmit(); })()`);
        await page.until("!document.getElementById('delete-policy-form-203.0.113.20')");
        assert.equal(policyPosts, 4);
        assert.equal(postCount, hints, "Policy page background polling and CRUD do not request FTD refresh");
      } finally { await page.close(); }
    });
    await t.test("enabled/disabled badges and observed disabled protection update across policy, shuns and detail", async () => {
      status = initial();
      status.policy_revision = 1;
      policy = { revision: 1, limit: 1000, entries: [
        { ip: "198.51.100.10", name: "Paused office", enabled: false, active_devices: 1, last_auto_removed_at: null },
        { ip: "198.51.100.11", name: "Enabled office", enabled: true, active_devices: 0, last_auto_removed_at: null },
      ] };
      const page = await connectPage(debugOrigin, `${origin}/protected-ips`);
      try {
        assert.equal(await page.evaluate("document.querySelector('.policy-disabled').textContent"), "Disabled");
        assert.equal(await page.evaluate("getComputedStyle(document.querySelector('.policy-disabled')).backgroundColor"), "rgb(180, 35, 24)");
        assert.equal(await page.evaluate("getComputedStyle(document.querySelector('.policy-enabled')).backgroundColor"), "rgb(22, 101, 52)");
        assert.ok(await page.evaluate("document.querySelector('.policy-disabled-warning').textContent.includes('Protection disabled — currently shunned.')"));
        await page.call("Page.navigate", { url: `${origin}/` });
        await page.until("Boolean(document.querySelector('#active-shuns .disabled-protection-shun'))");
        assert.equal(await page.evaluate("document.querySelector('#active-shuns .policy-disabled').textContent"), "Protection disabled");
        await page.call("Page.navigate", { url: `${origin}/shuns/198.51.100.10` });
        await page.until("Boolean(document.querySelector('.disabled-protection-notice'))");
        assert.ok(await page.evaluate("document.querySelector('#protection-notice').textContent.includes('currently shunned')"));
        policy.entries[0].enabled = true;
        policy.revision = status.policy_revision = 2;
        status.status_revision += 1;
        await wake(page);
        await page.until("Boolean(document.querySelector('.protected-ip-notice'))");
        assert.equal(await page.evaluate("Boolean(document.querySelector('.disabled-protection-notice'))"), false);
        await page.call("Page.navigate", { url: `${origin}/` });
        await page.until("Boolean(document.querySelector('#active-shuns .protected-shun'))");
        assert.equal(await page.evaluate("Boolean(document.querySelector('#active-shuns .policy-disabled'))"), false);
      } finally { await page.close(); policy = { revision: 0, limit: 1000, entries: [] }; }
    });
    await t.test("history is expanded and paginates 100 records without shifting older windows", async () => {
      status = initial();
      historyRows = [];
      for (let index = 0; index < 251; index += 1) appendHistory();
      const hints = postCount;
      const page = await connectPage(debugOrigin, `${origin}/history`);
      try {
        assert.equal(await page.evaluate("Boolean(document.querySelector('#recent-events-details'))"), false);
        assert.equal(await page.evaluate("document.querySelectorAll('#recent-events tbody tr').length"), 100);
        assert.ok(await page.evaluate("document.querySelector('[data-history-page-summary]').textContent.includes('Page 1 of 3')"));
        let next = await page.evaluate("document.querySelector('[rel=next]').href");
        await page.call("Page.navigate", { url: next });
        await page.until("document.querySelector('[data-history-page-summary]')?.textContent.includes('Page 2 of 3')");
        const ids = await page.evaluate("Array.from(document.querySelectorAll('#recent-events tbody tr'),row=>row.dataset.eventId)");
        assert.equal(ids.length, 100);
        assert.equal(await page.evaluate("document.querySelector('#recent-events table').getBoundingClientRect().height>0"), true);
        appendHistory();
        complete();
        await wake(page);
        await page.until("document.querySelector('[data-refresh-message]').textContent==='Refresh completed.'");
        assert.deepEqual(await page.evaluate("Array.from(document.querySelectorAll('#recent-events tbody tr'),row=>row.dataset.eventId)"), ids);
        assert.equal(await page.evaluate("location.href"), next);
        next = await page.evaluate("document.querySelector('[rel=next]').href");
        await page.call("Page.navigate", { url: next });
        await page.until("document.querySelector('[data-history-page-summary]')?.textContent.includes('Page 3 of 3')");
        assert.equal(await page.evaluate("document.querySelectorAll('#recent-events tbody tr').length"), 51);
        assert.equal(await page.evaluate("Boolean(document.querySelector('[rel=next]'))"), false);
        await page.call("Page.navigate", { url: `${origin}/history` });
        await page.until("document.querySelector('#recent-events')?.textContent.includes('HISTORY_EVENT_252')");
        assert.ok(await page.evaluate("document.querySelector('.history-retention').textContent.includes('366 days')"));
        assert.equal(postCount, hints);
      } finally { await page.close(); }
    });
    await t.test("refresh, queue notices and request failures never shift the working content", async () => {
      status = initial();
      failStatus = false;
      const page = await connectPage(debugOrigin, origin);
      try {
        assert.equal(await page.evaluate("Boolean(document.querySelector('[data-refresh-message]').closest('#status-menu'))"), true);
        const position = () => page.evaluate("document.querySelector('.universal-search').getBoundingClientRect().top+scrollY");
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: false });
          const baseline = await position();
          for (const phase of ["refreshing", "error", "ready"]) {
            status.refresh_in_progress = phase === "refreshing";
            status.devices["1"].state = phase;
            status.devices["1"].stale = phase === "error";
            status.last_error = phase === "error" ? "A long device failure. ".repeat(12) : null;
            status.queue.counts = phase === "error" ? { UNVERIFIED: 12345 } : {};
            status.status_revision += 1;
            await wake(page);
            const label = { refreshing: "Refreshing", error: "Error", ready: "Current" }[phase];
            await page.until(`document.querySelector('[data-device-status]').textContent.includes('${label}')`);
            assert.equal(await position(), baseline, `${width}px viewport / ${phase} leaves search in place`);
          }
          failStatus = true;
          await wake(page);
          await page.until("!document.querySelector('[data-action-warning]').hidden");
          assert.ok(await page.evaluate("document.querySelector('[data-action-warning]').getBoundingClientRect().height>0"));
          assert.equal(await position(), baseline, "Network error is visible without moving content");
          failStatus = false;
          await wake(page);
          await page.until("document.querySelector('[data-action-warning]').hidden");
        }
      } finally { failStatus = false; await page.close(); }
    });
    await t.test("import preview is non-executable, escaped and preserved through metadata updates", async () => {
      status = initial();
      const hints = postCount;
      const executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/imports`);
      const source = "# ignore 192.0.2.99\n198.51.100.10 # <img src=x onerror=alert(1)>\n203.0.113.20\n192.0.2.30,192.0.2.30\nsource 192.0.2.40 destination 192.0.2.41\n192.0.2.0/24\n555.555.555.666";
      try {
        assert.equal(await page.evaluate("document.querySelectorAll('[name=device_ids]:checked').length"), 0);
        assert.equal(await page.evaluate("document.querySelector('[name=device_ids][value=\"2\"]').disabled"), true);
        await page.evaluate(`document.querySelector('#blocklist-text').value=${JSON.stringify(source)}; document.querySelector('[name=device_ids][value="1"]').checked=true; document.querySelector('.import-form').requestSubmit()`);
        await page.until("Boolean(document.querySelector('#import-results'))");
        assert.equal(previewPosts, 1);
        for (const state of ["Protected", "Already shunned", "Ready", "Duplicate", "Ambiguous", "Unsupported", "Invalid"]) {
          assert.equal(await page.evaluate(`document.querySelectorAll('[data-preview-state="${state}"]').length`), 1);
        }
        const colours = { Ready: "rgb(22, 101, 52)", Invalid: "rgb(180, 35, 24)", Unsupported: "rgb(180, 35, 24)",
          Ambiguous: "rgb(146, 64, 14)", Protected: "rgb(146, 64, 14)", "Already shunned": "rgb(29, 78, 216)", Duplicate: "rgb(68, 83, 102)" };
        for (const theme of ["light", "dark"]) {
          await page.call("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: theme }] });
          for (const [state, colour] of Object.entries(colours)) {
            const styles = await page.evaluate(`(() => {
              const row=document.querySelector('[data-preview-state="${state}"]');
              const badge=row.querySelector('.preview-state-badge');
              const total=document.querySelector('.preview-counts [data-preview-status="${state}"]');
              return {text:badge.textContent, background:getComputedStyle(badge).backgroundColor,
                foreground:getComputedStyle(badge).color, summary:getComputedStyle(total).backgroundColor,
                border:getComputedStyle(row.cells[0]).borderLeftColor,
                borderWidth:getComputedStyle(row.cells[0]).borderLeftWidth,
                rowBackground:getComputedStyle(row.cells[0]).backgroundColor};
            })()`);
            assert.equal(styles.text, state, "Colour never replaces the text label");
            assert.equal(styles.background, colour, `${state} badge in ${theme} theme`);
            assert.equal(styles.summary, colour, "Full-list count shares the row status colour");
            assert.equal(styles.foreground, "rgb(255, 255, 255)");
            if (["Invalid", "Unsupported", "Ambiguous"].includes(state)) {
              assert.equal(styles.border, state === "Ambiguous" ? "rgb(217, 119, 6)" : "rgb(180, 35, 24)");
              assert.notEqual(styles.borderWidth, "0px");
              assert.notEqual(styles.rowBackground, "rgba(0, 0, 0, 0)");
            }
          }
        }
        assert.ok(await page.evaluate("document.querySelector('#import-results').textContent.includes('1 candidate device/IP pairs')"));
        assert.equal(await page.evaluate("document.querySelectorAll('#import-results img').length"), 0);
        assert.equal(await page.evaluate("document.querySelector('#blocklist-text').value"), source);
        assert.equal(await page.evaluate("Boolean(document.querySelector('[data-queue-form], [data-policy-form]'))"), false);
        await page.evaluate("document.querySelector('#blocklist-text').value+='\\n192.0.2.55'; document.querySelector('#blocklist-text').focus()");
        const previousReads = pageReads;
        complete("partial");
        await wake(page);
        await page.until("document.querySelector('[data-refresh-message]').textContent.includes('partially completed')");
        const deadline = Date.now() + 8000;
        while (pageReads <= previousReads && Date.now() < deadline) await delay(50);
        assert.ok(pageReads > previousReads, "Metadata-driven GET completed while the preview stayed local");
        assert.equal(await page.evaluate("document.querySelector('#blocklist-text').value"), source + "\n192.0.2.55");
        assert.ok(await page.evaluate("Boolean(document.querySelector('#import-results'))"));
        assert.equal(await page.evaluate("document.activeElement.id"), "blocklist-text");
        assert.equal(previewPosts, 1);
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("large pasted lists are not truncated; UTF-8 limit is explicit and results page by 100", async () => {
      status = initial();
      const hints = postCount;
      const executions = executionCount;
      const parses = previewPosts;
      const source = Array.from({ length: 7307 }, (_, i) => `shun 198.18.${i >> 8}.${i & 255}`).join("\n");
      const page = await connectPage(debugOrigin, `${origin}/imports`);
      try {
        assert.equal(await page.evaluate("document.querySelector('#blocklist-text').maxLength"), -1);
        assert.equal(await page.evaluate("document.querySelector('#blocklist-text').spellcheck"), false);
        await page.evaluate("document.querySelector('#blocklist-text').focus()");
        // Exercise clipboard paste rather than CDP text insertion. Permissions
        // apply only to the synthetic localhost in this isolated headless profile.
        await page.call("Browser.grantPermissions", { origin, permissions: ["clipboardReadWrite", "clipboardSanitizedWrite"] });
        await page.evaluate("navigator.clipboard.writeText(Array.from({length:7307},(_,i)=>`shun 198.18.${i>>8}.${i&255}`).join('\\n'))");
        await page.call("Input.dispatchKeyEvent", { type: "keyDown", key: "v", code: "KeyV", modifiers: 2, windowsVirtualKeyCode: 86 });
        await page.call("Input.dispatchKeyEvent", { type: "keyUp", key: "v", code: "KeyV", modifiers: 2, windowsVirtualKeyCode: 86 });
        await page.until("document.querySelector('#blocklist-text').value.endsWith('198.18.28.138')");
        assert.equal(await page.evaluate("document.querySelector('#blocklist-text').value"), source, "Real paste retains the final address");
        const bytes = Buffer.byteLength(source.replace(/\n/g, "\r\n"));
        assert.ok(await page.evaluate(`document.querySelector('#paste-size').textContent.includes((${bytes}).toLocaleString())`));
        await page.evaluate("document.querySelector('[name=device_ids][value=\"1\"]').checked=true; document.querySelector('.import-form').requestSubmit()");
        await page.until("document.querySelector('.preview-pagination')?.textContent.includes('Page 1 of 74')");
        assert.equal(await page.evaluate("document.querySelectorAll('[data-preview-state]').length"), 100);
        assert.ok(await page.evaluate("document.querySelector('#import-results').textContent.includes('7307 candidate device/IP pairs')"));
        await page.evaluate("document.querySelector('.preview-pagination button[value=\"2\"]').click()");
        await page.until("document.querySelector('.preview-pagination')?.textContent.includes('Page 2 of 74')");
        assert.equal(await page.evaluate("document.querySelectorAll('[data-preview-state]').length"), 100);
        assert.equal(await page.evaluate("document.querySelector('#blocklist-text').value"), source);
        await page.evaluate("document.querySelector('[data-preview-last]').click()");
        await page.until("document.querySelector('.preview-pagination')?.textContent.includes('Page 74 of 74')");
        assert.equal(await page.evaluate("document.querySelectorAll('[data-preview-state]').length"), 7);
        assert.ok(await page.evaluate("document.querySelector('.preview-table').textContent.includes('198.18.28.138')"));
        assert.equal(previewPosts, parses + 3);
        await page.evaluate(`(() => { const input=document.querySelector('#blocklist-text'); input.value='ї'.repeat(524289);
          input.dispatchEvent(new Event('input',{bubbles:true})); document.querySelector('.import-form').requestSubmit(); })()`);
        assert.equal(await page.evaluate("document.querySelector('#blocklist-text').validity.customError"), true);
        assert.ok(await page.evaluate("document.querySelector('#paste-size').textContent.includes('Over limit')"));
        assert.equal(await page.evaluate("document.querySelector('#blocklist-text').value.length"), 524289);
        assert.equal(previewPosts, parses + 3, "Oversize Unicode paste is blocked without discarding its source");
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
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
