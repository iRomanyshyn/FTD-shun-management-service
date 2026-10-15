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
        status.refresh_in_progress = true;
        status.interactive_refresh_state = "running";
        status.status_revision += 1;
      }
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
        await page.evaluate("document.querySelector('#ip-search').value='203.0.113'; document.querySelector('details').open=true");
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
        assert.equal(await page.evaluate("document.querySelector('details').open"), true);
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
  } finally {
    browser.kill("SIGTERM");
    await Promise.race([once(browser, "exit"), delay(3000)]);
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
    fs.rmSync(profile, { recursive: true, force: true });
  }
});
