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
from ftd_shun_manager.import_review import ImportReviews
from ftd_shun_manager.managed_review import ManagedRemovalReviews
from ftd_shun_manager.managed_intent import canonical_managed_fleet_scope
from ftd_shun_manager.managed_retirement_review import ManagedRetirementReviews
from ftd_shun_manager.bulk_removal_review import ReadyRemovalReviews
from ftd_shun_manager.bulk_ordered_review import OrderedRemovalReviews, validate_ordered_status
from ftd_shun_manager.bulk_ordered_removals import _DOMAIN, _digest
from ftd_shun_manager.bulk_intent import canonical_bulk_intent
from ftd_shun_manager.bulk_preparation_view import operation_key, validate_report, validate_proposal
from ftd_shun_manager.bulk_confirmation_view import BulkConfirmationReviews, validate_receipt_page
from ftd_shun_manager.bulk_cancellation_view import BulkCancellationReviews, validate_review_page, validate_status
from ftd_shun_manager.bulk_removals import canonical_scope
from ftd_shun_manager.managed_grant_review import ManagedGrantReviews
from ftd_shun_manager.managed_batch_review import ManagedBatchReviews, parse_standing_list
from ftd_shun_manager.managed_import_web import BrowserImportReviews
from ipaddress import IPv4Address
from ftd_shun_manager.web import Identity, templates
p = json.load(sys.stdin)
policy_entries = (p.get("policy") or {}).get("entries", [])
enabled_ips = frozenset(entry["ip"] for entry in policy_entries if entry["enabled"])
disabled_ips = frozenset(entry["ip"] for entry in policy_entries if not entry["enabled"])
preview = None
managed_import_report = None
inspection = ordered_status = None
ordered_key = "88888888-8888-4888-8888-888888888888"
bulk_draft = bulk_drafts = bulk_proposal = None
policy_receipt = None
bulk_cancellation = None
if p.get("submitted"):
    parsed = parse_blocklist(p["source_text"])
    preview = paginate_preview(summarize_preview(parsed, dict(policy_revision=1, devices=[dict(id=1,hostname="lab-ftd")],
        addresses=[dict(ip=ip,protected=ip=="198.51.100.10",devices=[dict(id=1,hostname="lab-ftd",already_shunned=ip=="203.0.113.20")]) for ip in parsed["ips"]])), p.get("page", 1))
shun = dict(ip="198.51.100.10", device_id=1, device_hostname="lab-ftd FIXTURE_EVENT_" + str(p["generation"]), interface="outside",
            first_seen_at="2026-10-14T10:00:00Z", active_since_at="2026-10-15T10:00:00Z", last_seen_at="2026-10-15T10:00:00Z",
            manual_imports=p.get("shun_origins", []))
event = dict(timestamp="2026-10-15T10:00:00Z", event_type="FIXTURE_EVENT_" + str(p["generation"]),
             device_hostname="lab-ftd", actor_display_name="Test Operator", actor_subject="test", ip=shun["ip"])
review = ImportReviews().prepare("test", "fixture-token", preview, p.get("label", ""), "Fixture only") if p["template"] == "import-confirm.html" else None
if p["template"] == "managed-remove-review.html":
    if p.get("fleet_review"):
        scope = dict(ip="198.51.100.251", managed_initialized=True, managed_revision=p["managed"]["revision"], protected_revision=1, protected=False,
            targets=[dict(device_id=1,hostname="maintained-missing",device_enabled=True,observed_present=False,maintenance_enabled=True,intent_id="11111111-1111-4111-8111-111111111111",generation=1),
                dict(device_id=2,hostname="observed-only",device_enabled=True,observed_present=True,maintenance_enabled=False,intent_id=None,generation=None),
                dict(device_id=3,hostname="disabled-missing",device_enabled=p.get("all_devices_enabled", False),observed_present=False,maintenance_enabled=True,intent_id="22222222-2222-4222-8222-222222222222",generation=2)])
        review = ManagedRemovalReviews().prepare_fleet("test", "fixture-token", dict(**scope, scope_digest=canonical_managed_fleet_scope(scope)[1]), IPv4Address(scope["ip"]), 900, "Fixture only", ordered_wait=p.get("ordered_wait", False))
    else:
        review = ManagedRemovalReviews().prepare("test", "fixture-token", p["managed"], 1, IPv4Address("198.51.100.251"), 900, "Fixture only")
if p["template"] == "managed-retirement-review.html":
    review = ManagedRetirementReviews().prepare("test", "fixture-token", p["managed"], 1, IPv4Address("198.51.100.251"), "Fixture only")
if p["template"] in ("bulk-removal-review.html", "bulk-ordered-review.html", "bulk-ordered-status.html"):
    scope = dict(version=2,scope="fleet",ip="198.51.100.251",managed_revision=1,protected_revision=1,protected=False,
        targets=[dict(device_id=i,hostname="<b>Fixture FTD</b>",device_enabled=True,observed_present=i==1,
            maintenance_enabled=i==1,intent_id="11111111-1111-4111-8111-111111111111" if i==1 else None,
            generation=1 if i==1 else None,authorization_request_id="22222222-2222-4222-8222-222222222222" if i==1 else None,
            target_revision=1 if i==1 else None) for i in (1,2)])
    if p["template"] == "bulk-removal-review.html":
        review = ReadyRemovalReviews().prepare("test","fixture-token",dict(**scope,scope_digest=canonical_scope(scope)[1],
            read_only=True,execution_available=False,device_work_admitted=False),IPv4Address(scope["ip"]),reason="<b>Synthetic only</b>")
    else:
        predecessor = dict(request_id="33333333-3333-4333-8333-333333333333",job_id="44444444-4444-4444-8444-444444444444",
            intent_id=scope["targets"][0]["intent_id"],generation=1,authorization_request_id=scope["targets"][0]["authorization_request_id"],
            target_revision=1,snapshot_id="55555555-5555-4555-8555-555555555555",snapshot_started_at="2026-10-21T12:00:00.000Z",
            snapshot_at="2026-10-21T12:00:00.000Z",requested_at="2026-10-21T12:00:00.000Z",expires_at="2026-10-21T12:15:00.000Z",
            started_at="2026-10-21T12:00:01.000Z",executor_owner="66666666-6666-4666-8666-666666666666",executor_epoch=1,
            lease_until="2026-10-21T12:02:15.000Z",claim_event_id="77777777-7777-4777-8777-777777777777",evidence_digest="a"*64)
        inspection = dict(intent_format=2,mode="ordered-removal-preflight",inspected_at="2026-10-21T12:00:02.000Z",
            scope=scope,scope_digest=canonical_scope(scope)[1],targets=[dict(device_id=i,disposition="WAITING_ADD" if i==1 else "READY",
                blockers=[],predecessor=predecessor if i==1 else None) for i in (1,2)],global_blockers=[],blocked_target_count=0,
            waiting_target_count=1,disposition="WAITING_ADD",read_only=True,execution_available=False,device_work_admitted=False)
        inspection["preflight_digest"] = _digest(inspection,_DOMAIN)
        if p["template"] == "bulk-ordered-review.html":
            review = OrderedRemovalReviews().prepare("test","fixture-token",inspection,IPv4Address(scope["ip"]),reason="<b>Synthetic only</b>")
        else:
            phase = p["refresh"].get("fixture_ordered_phase","WAITING_ADD")
            admitted = phase in ("ADMITTED","VERIFIED")
            jobs = [dict(device_id=i,job_id=f"9999999{i}-9999-4999-8999-999999999999",state="VERIFIED" if phase=="VERIFIED" else "QUEUED") for i in (1,2)] if admitted else []
            ordered_status = dict(operation_id=ordered_key,intent_format=2,action="STOP_AND_REMOVE_ORDERED",owner_subject="test",predecessor_count=1,
                scope=scope,requested_at="2026-10-21T12:00:02.000Z",expires_at="2026-10-21T12:15:02.000Z",
                state="ADMITTED" if admitted else phase,predecessors=[dict(device_id=1,job_id=predecessor["job_id"],state="NOOP" if admitted else "FAILED" if phase=="ATTENTION" else "RUNNING",missing_evidence=False)],
                cleanup_jobs=jobs,verified_removal=phase=="VERIFIED",cleanup_reserved=not admitted,read_only=True,device_work_admitted=admitted,
                attention=phase=="ATTENTION",decision=dict(jobs=[dict(device_id=j["device_id"],job_id=j["job_id"]) for j in jobs],requested_at="2026-10-21T12:00:02.000Z",expires_at="2026-10-21T12:15:02.000Z") if admitted else dict(reason="ADMISSION_CONFLICT") if phase=="ATTENTION" else None)
            validate_ordered_status(ordered_key,ordered_status)
if p["template"] == "managed-grant-review.html":
    classification = dict(policy_revision=1, addresses=[dict(ip="198.51.100.252", protected=False,
        devices=[dict(id=1, hostname="lab-ftd", already_shunned=False)])])
    review = ManagedGrantReviews().prepare("test", "fixture-token", p["managed"], classification, 1, IPv4Address("198.51.100.252"), "Fixture", "Synthetic only")
if p["template"] == "managed-batch-review.html":
    parsed = parse_standing_list("\\n".join(f"198.18.0.{i}" for i in range(1, 103)), [1])
    classification = dict(policy_revision=1, addresses=[dict(ip=ip, protected=False,
        devices=[dict(id=1, hostname="lab-ftd", already_shunned=False)]) for ip in parsed["ips"]])
    review = ManagedBatchReviews().prepare("test", "fixture-token", p["managed"], classification, parsed, [1], "Fixture", "Synthetic only")
if p["template"] == "managed-import-review.html":
    targets = [dict(device_id=1,ip=f"198.18.0.{i}",classification="EXCLUDED_PROTECTED" if i==1 else "PROPOSE_ADOPT" if i==2 else "PROPOSE_ADD") for i in range(1,103)]
    header = dict(plan_id="33333333-3333-4333-8333-333333333333",digest="a"*64,target_count=102,
        classification_counts=dict(PROPOSE_ADD=100,PROPOSE_ADOPT=1,ALREADY_MANAGED=0,EXCLUDED_PROTECTED=1),
        devices=[dict(id=1,hostname="<b>Fixture FTD</b>")], source_counts=dict(Ready=102,Invalid=1),
        label="<b>Escaped import</b>",reason="Synthetic only",managed_revision=1,protected_revision=1,
        managed_initialized=True,expires_at="2099-01-01T00:00:00.000Z",can_execute=False,state="PREPARED")
    managed_import_report = dict(**header,page=1,pages=2,targets=targets[:100],report_rows=[dict(line=103,ip=None,status="Invalid",reason="Not an exact IPv4 token")])
    if p.get("import_kind") == "cancel":
        cancellation = dict(operation_id="44444444-4444-4444-8444-444444444444",can_cancel=True,device_work_admitted=False,
            accepted_count=101,counts=dict(WAITING_OUTCOME=1,RETAINED_APPLIED=5,STOPPED_UNSENT=95),attention_count=0,
            reviewed_at="2026-10-21T12:00:00.000Z",review_digest="b"*64)
        review = BrowserImportReviews().cancellation("test","fixture-token",cancellation)
        managed_import_report = dict(header=header,page=1,pages=2,targets=targets[:100],report_rows=[])
    else:
        review = BrowserImportReviews().confirmation("test","fixture-token",managed_import_report)
if p["template"] in ("bulk-import-workspace.html", "bulk-import-report.html", "bulk-confirmation-review.html", "bulk-policy-receipt.html", "bulk-cancellation-review.html", "bulk-cancellation-status.html"):
    plan_id="33333333-3333-4333-8333-333333333333"
    all_targets=[dict(device_id=1,ip=f"198.18.0.{i}",classification="EXCLUDED_PROTECTED" if i==1 else "PROPOSE_ADOPT" if i==2 else "PROPOSE_ADD",
        observed_at="2026-10-26T12:00:00.000Z" if i==2 else None,managed_enabled=False,
        previous_intent_id=None,previous_generation=None,previous_authorization_request_id=None) for i in range(1,103)]
    diagnostics=[dict(line=i,ip=f"198.18.0.{i}",status="Ready",source_lines=[i],reason="Exact IPv4 address") for i in range(1,103)]
    diagnostics.append(dict(line=103,ip=None,status="Invalid",source_lines=[103],reason="Not an exact IPv4 token"))
    current=p.get("bulk_page",1)
    bulk_draft=dict(version=1,scope="managed_import_preparation",plan_id=plan_id,actor_subject="test",actor_display_name="Test Operator",actor_roles=["Operator"],
        created_at="2026-10-26T12:00:00.000Z",expires_at="2026-10-26T12:10:00.000Z",label="<b>Fixture draft</b>",reason="Intentional fixture metadata",
        managed_initialized=True,managed_revision=0,protected_revision=1,devices=[dict(id=1,hostname="<b>Fixture FTD</b>")],target_count=102,address_count=102,ignored_lines=0,
        source_row_count=103,source_counts=dict(Ready=102,Invalid=1),classification_counts=dict(PROPOSE_ADD=100,PROPOSE_ADOPT=1,ALREADY_MANAGED=0,EXCLUDED_PROTECTED=1),
        digest="a"*64,can_execute=False,execution_started=False,state="PREPARED",confirmed_operation_id=None,page=current,pages=2,page_size=100,
        targets=all_targets[(current-1)*100:current*100],report_rows=diagnostics[(current-1)*100:current*100],intent_format=2,policy_saved=False,device_work_admitted=False)
    validate_report(bulk_draft,plan_id,"test",current)
    summary={key:bulk_draft[key] for key in ("plan_id","created_at","expires_at","label","target_count","address_count","classification_counts","state","confirmed_operation_id","digest","can_execute")}
    initialized=p["refresh"].get("fixture_bulk_storage",True)
    bulk_drafts=dict(initialized=initialized,plans=[summary] if initialized else [],intent_format=2,can_execute=False,policy_saved=False,device_work_admitted=False)
    if p.get("bulk_review") or p["template"] in ("bulk-confirmation-review.html", "bulk-policy-receipt.html"):
        summary,canonical,digest=canonical_bulk_intent(((r["device_id"],IPv4Address(r["ip"]),r["classification"]) for r in all_targets),(1,),operation_key(plan_id),plan_id,
            bulk_draft["digest"],0,1,bulk_draft["label"],bulk_draft["reason"])
        bulk_proposal=dict(intent_format=2,operation_id=operation_key(plan_id),preparation_id=plan_id,canonical=canonical,digest=digest,manifest=summary.as_dict(),can_execute=False,policy_saved=False,device_work_admitted=False)
        validate_proposal(bulk_proposal,bulk_draft)
    if p["template"] == "bulk-confirmation-review.html":
        review=BulkConfirmationReviews().prepare("test","fixture-token",bulk_draft,bulk_proposal,
            concurrent=p["refresh"].get("bulk_policy_concurrent_enabled",False),
            expected_suspended=p["refresh"].get("managed_execution_suspended",True))
    if p["template"] == "bulk-policy-receipt.html":
        members=[dict(r,request_id=operation_key(plan_id),managed_enabled=0,
            intent_id=f"11111111-1111-4111-8111-{i:012d}" if r["classification"] != "EXCLUDED_PROTECTED" else None,
            generation=1 if r["classification"] != "EXCLUDED_PROTECTED" else None,
            authorization_request_id=operation_key(plan_id) if r["classification"] != "EXCLUDED_PROTECTED" else None) for i,r in enumerate(all_targets,1)]
        saved=dict(operation_id=operation_key(plan_id),status="policy_saved",intent_format=2,managed_revision=1,changed_targets=101,
            replayed=False,accepted_pairs=101,classification_counts=bulk_draft["classification_counts"],policy_only=True,
            device_work_admitted=False,restoration_suspended=True,confirmation_actor=dict(subject="test",display_name="<b>Original operator</b>",roles=["Operator"]))
        if p["refresh"].get("fixture_fenced_receipt"):
            saved.update(admission_mode="fenced",restoration_suspended=False)
        policy_receipt=dict(intent_format=2,historical_confirmation=True,read_only=True,can_execute=False,operation_id=operation_key(plan_id),
            preparation_id=plan_id,result=saved,manifest=bulk_proposal["manifest"],canonical=canonical,digest=digest,
            page=current,pages=2,targets=members[(current-1)*100:current*100])
        validate_receipt_page(policy_receipt,operation_key(plan_id),"test",current)
    if p["template"] in ("bulk-cancellation-review.html", "bulk-cancellation-status.html"):
        cancel_key=operation_key(plan_id)
        frozen_counts=dict(RETAINED_ADOPTED=1,WAITING_OUTCOME=1,STOPPED_UNSENT=99)
        frozen=dict(operation_id=cancel_key,reviewed_at="2026-10-26T12:00:00.000Z",expires_at="2026-10-26T12:05:00.000Z",
            review_digest="b"*64,scope_digest="c"*64,accepted_count=101,counts=frozen_counts,can_cancel=True,device_work_admitted=False)
        accepted=[dict(device_id=1,ip=r["ip"],classification=r["classification"],intent_id=f"11111111-1111-4111-8111-{i:012d}",
            generation=1,authorization_request_id=cancel_key,current_revision=1,
            state="RETAINED_ADOPTED" if i==2 else "WAITING_OUTCOME" if i==3 else "STOPPED_UNSENT",
            **(dict(job_id="22222222-2222-4222-8222-222222222222",attempt_digest="d"*64) if i==3 else {})) for i,r in enumerate(all_targets,1) if i!=1]
        if p["template"] == "bulk-cancellation-review.html":
            review=BulkCancellationReviews().prepare("test","fixture-token",frozen)
            managed_import_report=dict(review=frozen,page=current,pages=2,targets=accepted[(current-1)*100:current*100])
            validate_review_page(managed_import_report,frozen,current)
        else:
            outcome=p["refresh"].get("fixture_bulk_cancel_outcome")
            current_counts=dict(frozen_counts)
            projected=[]
            for row in accepted:
                item=dict(row,import_id=cancel_key,initial_state=row["state"],attention=False,
                    job_id=row.get("job_id"),attempt_digest=row.get("attempt_digest"))
                if row["state"]=="WAITING_OUTCOME" and outcome:
                    item.update(state="STOPPED_UNVERIFIED" if outcome=="UNVERIFIED" else "RETAINED_APPLIED",
                        attention=outcome=="UNVERIFIED",outcome=outcome,settled_at="2026-10-26T12:01:00.000Z")
                    current_counts.pop("WAITING_OUTCOME")
                    current_counts[item["state"]]=1
                projected.append(item)
            result=dict(operation_id=cancel_key,intent_format=2,status="cancelled_uncompleted",accepted_count=101,counts=frozen_counts,
                changed_targets=99,managed_revision=2,device_work_admitted=False,device_removal_requested=False,replayed=False)
            bulk_cancellation=dict(operation_id=cancel_key,requested=True,read_only=True,can_execute=False,historical_cancellation=True,
                settled=bool(outcome),page=current,pages=2,result=result,current_counts=current_counts,attention_count=int(outcome=="UNVERIFIED"),
                targets=projected[(current-1)*100:current*100])
            validate_status(bulk_cancellation,cancel_key,current)
print(templates.get_template(p["template"]).render(identity=Identity("test", "Test Operator", ("Operator",)),
    review=review, report=managed_import_report, accepted=None, result=None, confirm_ip="", message=None, admission_enabled=p["refresh"].get("managed_policy_admission_enabled" if p["template"] == "managed-import-review.html" else "import_admission_enabled", False),
    retry_available=p["refresh"].get("import_admission_enabled", False), execution_enabled=False,
    removal_admission_enabled=p["refresh"].get("managed_removal_admission_enabled", False),
    frozen_view=p["template"] in ("import-confirm.html", "managed-remove-review.html", "bulk-removal-review.html", "bulk-ordered-review.html", "bulk-import-workspace.html", "bulk-import-report.html", "bulk-confirmation-review.html", "bulk-policy-receipt.html", "bulk-cancellation-review.html", "managed-retirement-review.html", "managed-grant-review.html", "managed-batch-form.html", "managed-batch-review.html"),
    ready_removal_local_enabled=p["refresh"].get("fixture_ready_local_enabled",False),
    ordered_removal_local_enabled=p["refresh"].get("fixture_ordered_local_enabled",False),
    inspection=inspection,ordered=ordered_status,operation_id=bulk_cancellation["operation_id"] if bulk_cancellation else ordered_key,cancellation=bulk_cancellation,
    drafts=bulk_drafts,draft=bulk_draft,proposal=bulk_proposal,preparation_id="33333333-3333-4333-8333-333333333333",review_mode=p.get("bulk_review",False),
    creation_unknown=False,draft_label="",draft_reason="",
    bulk_policy_local_enabled=p["refresh"].get("fixture_bulk_policy_local_enabled",False),typed_count="",consent=False,receipts=None,receipt=policy_receipt,
    bulk_policy_local_concurrent=p["refresh"].get("fixture_bulk_policy_local_concurrent",False),
    admission_available=p["refresh"].get("managed_policy_admission_enabled", False),
    page=1, pages=2, page_targets=review.targets[:100] if p["template"] == "managed-batch-review.html" else [],
    confirm_count="", acknowledged=False, import_text_limit=1048576,
    managed=p.get("managed"), handoffs=p.get("handoffs"), fleet_cleanup=p.get("fleet_cleanup"),
    csrf_token="fixture-token", shuns=[shun], refresh=p["refresh"], search_query=p["query"],
    search_results=None, trusted_policy_ips=enabled_ips, disabled_policy_ips=disabled_ips, recent_events=p.get("history", {}).get("events", [event]),
    pagination=p.get("history", {}), anchored_history=bool(p.get("anchor")),
    ip=shun["ip"], events=[event], is_trusted_policy_ip=shun["ip"] in enabled_ips,
    is_disabled_policy_ip=shun["ip"] in disabled_ips, policy=p.get("policy"),
    source_text=p.get("source_text", ""), batch_label=p.get("label", ""), batch_reason=p.get("reason", ""),
    selected_devices=[1] if p.get("submitted") else [], preview=preview, preview_error=None,
    devices=[dict(id=1,hostname="lab-ftd",enabled=True),dict(id=2,hostname="disabled-ftd",enabled=False)],
    active_page="managed" if p["template"].startswith("bulk-ordered-") or p["template"] in ("managed-shuns.html", "bulk-managed-shuns.html", "managed-remove-review.html", "bulk-removal-review.html", "managed-retirement-review.html", "managed-grant-review.html", "managed-batch-form.html", "managed-batch-review.html") else "imports" if p["template"] in ("import-preview.html", "bulk-confirmation-review.html", "bulk-policy-receipt.html", "bulk-cancellation-review.html", "bulk-cancellation-status.html") or p["template"].startswith("bulk-import-") else "protected" if p["template"] == "protected-ips.html" else "history" if p["template"] == "history.html" else "shuns",
    auto_request=p["template"] not in ("protected-ips.html", "history.html", "import-preview.html", "import-confirm.html", "bulk-import-workspace.html", "bulk-import-report.html", "bulk-confirmation-review.html", "bulk-policy-receipt.html", "bulk-cancellation-review.html", "bulk-cancellation-status.html", "managed-shuns.html", "bulk-managed-shuns.html", "managed-remove-review.html", "bulk-removal-review.html", "bulk-ordered-review.html", "bulk-ordered-status.html", "managed-retirement-review.html", "managed-grant-review.html", "managed-batch-form.html", "managed-batch-review.html")))
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

async function connectPage(debugOrigin, url, readySelector = "[data-refresh-request]") {
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
  await until(`Boolean(document.querySelector(${JSON.stringify(readySelector)}))`);
  return { call, evaluate, until, errors, close: async () => {
    assert.deepEqual(errors, [], "No browser JavaScript exceptions");
    await fetch(`${debugOrigin}/json/close/${target.id}`);
    socket.close();
  } };
}

test("refresh interaction in real Chromium", { timeout: 180000 }, async (t) => {
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
  let confirmationPosts = 0;
  let managedCancelPosts = 0;
  let managed = { initialized: false, revision: 0, entries: [], limit: 1000,
    restoration_suspended: true, controller_available: false, read_only: true };
  let handoffs = { initialized: false, counts: {}, items: [], display_limit: 20, read_only: true };
  let fleetCleanup = { initialized: false, counts: {}, items: [], display_limit: 20, scope_display_limit: 5, read_only: true };
  let historyRows = [];
  let shunOrigins = [];
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
        const priority = status.refresh_in_progress && status.session_cycles_enabled && status.refresh_schedule_mode !== "per_device";
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
      const maintained = policy.entries.find((entry) => entry.ip === ip)?.maintained_devices || 0;
      if (field("managed_revision") && Number(field("managed_revision")) !== policy.managed_revision) {
        response.statusCode = 409;
        response.end(JSON.stringify({ detail: "Managed policy changed. Reload saved values and review the maintenance warning." }));
        return;
      }
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
    } else if (/^\/managed-shuns\/(handoffs|fleet-waits)\/[^/]+\/cancel$/.test(url.pathname) && request.method === "POST") {
      let body = "";
      for await (const chunk of request) body += chunk;
      assert.match(request.headers["content-type"], /^application\/x-www-form-urlencoded/);
      assert.equal(new URLSearchParams(body).get("csrf"), "fixture-token");
      managedCancelPosts += 1;
      if (url.pathname.includes("/fleet-waits/")) {
        fleetCleanup.items[0].state = "CANCELLED";
        fleetCleanup.items[0].active = false;
        fleetCleanup.counts = { settled: 1 };
      } else {
        handoffs.items[0].state = "CANCELLED";
        handoffs.counts = { CANCELLED: 1 };
      }
      status.queue.revision += 1;
      status.data_revision += 1;
      status.status_revision += 1;
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify(stamp()));
    } else if (url.pathname === "/imports/confirm" && request.method === "POST") {
      let body = "";
      for await (const chunk of request) body += chunk;
      const fields = new URLSearchParams(body);
      assert.equal(fields.get("csrf"), "fixture-token");
      assert.equal(fields.get("confirm_count"), "1");
      assert.ok(fields.get("review"));
      confirmationPosts += 1;
      response.setHeader("Content-Type", "text/html");
      response.end("<p>Fixture admission received; no device work</p>");
    } else if (["/", "/history", "/protected-ips", "/imports", "/imports/review", "/managed-imports/review", "/managed-shuns", "/managed-shuns/removal-review", "/managed-shuns/fleet-removal-review", "/managed-shuns/v2/removal-review", "/managed-shuns/v2/ordered-removal-review", "/managed-shuns/retirement-review", "/managed-shuns/grant-review", "/managed-shuns/bulk", "/managed-shuns/bulk-review"].includes(url.pathname) || url.pathname.startsWith("/shuns/") || url.pathname.startsWith("/managed-shuns/v2/ordered-removals/") || url.pathname.startsWith("/managed-imports/v2")) {
      pageReads += 1;
      let previewFields = {};
      if (url.pathname === "/imports/review") previewFields = {
        submitted: true, source_text: "192.0.2.30", label: "<b>Review fixture</b>", page: 1,
      };
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
      let managedView = managed;
      if (url.pathname === "/managed-shuns") {
        const revision = url.searchParams.get("revision");
        const current = Number(url.searchParams.get("page") || 1);
        managedView = revision !== null && Number(revision) !== managed.revision
          ? { changed: true, initialized: false, entries: [] }
          : { ...managed, total: managed.entries.length, page: current,
            pages: Math.max(1, Math.ceil(managed.entries.length / 100)), page_size: 100,
            entries: managed.entries.slice((current - 1) * 100, current * 100) };
      }
      const payload = { refresh: stamp(), generation, query: url.searchParams.get("q") || "", shun_origins: shunOrigins,
        bulk_page: Number(url.searchParams.get("page") || 1), bulk_review: url.pathname.endsWith("/review"),
        import_kind: url.searchParams.get("kind"),
        fleet_review: url.pathname === "/managed-shuns/fleet-removal-review",
        ordered_wait: url.searchParams.get("ordered") === "yes", all_devices_enabled: url.searchParams.get("enabled") === "all",
        history, anchor: url.searchParams.get("anchor"),
        ...previewFields,
        policy, managed: managedView, handoffs, fleet_cleanup: fleetCleanup, template: url.pathname === "/" ? "index.html" : url.pathname === "/history" ? "history.html"
          : url.pathname === "/protected-ips" ? "protected-ips.html" : url.pathname === "/imports" ? "import-preview.html"
            : url.pathname === "/imports/review" ? "import-confirm.html" : url.pathname === "/managed-imports/review" ? "managed-import-review.html"
              : url.pathname === "/managed-imports/v2/confirmation-review" ? "bulk-confirmation-review.html"
                : url.pathname === "/managed-imports/v2/cancellation-review" ? "bulk-cancellation-review.html"
                : url.pathname.startsWith("/managed-imports/v2/cancellations/") ? "bulk-cancellation-status.html"
                : url.pathname.startsWith("/managed-imports/v2/receipts/") ? "bulk-policy-receipt.html"
                : url.pathname === "/managed-imports/v2" ? "bulk-import-workspace.html" : url.pathname.startsWith("/managed-imports/v2/") ? "bulk-import-report.html"
              : url.pathname === "/managed-shuns" ? (managed.intent_format === 2 ? "bulk-managed-shuns.html" : "managed-shuns.html")
              : url.pathname === "/managed-shuns/v2/removal-review" ? "bulk-removal-review.html"
                : url.pathname === "/managed-shuns/v2/ordered-removal-review" ? "bulk-ordered-review.html"
                  : url.pathname.startsWith("/managed-shuns/v2/ordered-removals/") ? "bulk-ordered-status.html"
                : ["/managed-shuns/removal-review", "/managed-shuns/fleet-removal-review"].includes(url.pathname) ? "managed-remove-review.html"
                : url.pathname === "/managed-shuns/retirement-review" ? "managed-retirement-review.html"
                  : url.pathname === "/managed-shuns/grant-review" ? "managed-grant-review.html"
                    : url.pathname === "/managed-shuns/bulk" ? "managed-batch-form.html"
                      : url.pathname === "/managed-shuns/bulk-review" ? "managed-batch-review.html" : "detail.html" };
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
    await t.test("independent device demand stays clickable and timers never fabricate refreshed data", async () => {
      status = initial();
      Object.assign(status, { refresh_schedule_mode: "per_device", active_device_count: 1,
        pending_refresh_device_count: 2, refresh_in_progress: true, device_cycle: {},
        device_cycles: { "1": { action: "add_and_verify", ip: "198.51.100.20", completed: 3 } },
        interactive_refresh_state: "checkpoint_pending", next_interactive_refresh: future(40) });
      Object.assign(status.devices["1"], { active: true, refresh_pending: true,
        next_interactive_refresh: future(40), next_baseline_refresh: future(250) });
      status.devices["2"] = { hostname: "slow-ftd", state: "error", stale: true, active: false,
        refresh_pending: true, last_successful_refresh: null, last_error: "Device fence held.",
        next_interactive_refresh: future(0), next_baseline_refresh: future(0), retry_in_seconds: 5 };
      const page = await connectPage(debugOrigin, `${origin}/?q=198.51`);
      try {
        await page.until("document.querySelector('[data-refresh-request]').textContent.includes('2 device(s)')");
        assert.equal(await page.evaluate("document.querySelector('[data-refresh-request]').disabled"), false);
        assert.match(await page.evaluate("document.querySelector('[data-status-indicator]').textContent"), /2 waiting/);
        assert.match(await page.evaluate("document.querySelector('[data-device-status]').textContent"), /Device fence held/);
        assert.match(await page.evaluate("document.querySelector('[data-cycle-progress]').textContent"), /Adding and verifying.*3 items/);
        await page.evaluate("document.querySelector('#ip-search').value='203.0.113'; document.querySelector('#status-menu').open=true");
        const before = postCount;
        await page.evaluate("document.querySelector('[data-refresh-request]').click()");
        await page.until("!document.querySelector('[data-refresh-request]').disabled");
        await page.evaluate("document.querySelector('[data-refresh-request]').click()");
        await page.until("!document.querySelector('[data-refresh-request]').disabled");
        assert.equal(postCount, before + 2, "Repeated requests join server demand, not a disabled global cycle");
        const reads = pageReads;
        status.next_interactive_refresh = future(-1);
        status.status_revision += 1;
        await wake(page);
        await page.until("document.querySelector('[data-refresh-request]').textContent.includes('waiting for verification')");
        assert.equal(pageReads, reads, "Elapsed countdown is not new observation evidence");
        status.pending_refresh_device_count = 1;
        status.data_revision += 1;
        status.status_revision += 1;
        generation += 1;
        await wake(page);
        await page.until(`document.querySelector('#active-shuns').textContent.includes('FIXTURE_EVENT_${generation}')`);
        assert.equal(await page.evaluate("document.querySelector('#ip-search').value"), "203.0.113");
        assert.equal(await page.evaluate("document.querySelector('#status-menu').open"), true);
        assert.match(await page.evaluate("document.querySelector('[data-status-indicator]').textContent"), /1 waiting/);
      } finally { await page.close(); }
    });
    await t.test("restricted continuous API profile advertises only available controls", async () => {
      status = initial();
      Object.assign(status, { runtime_mode: "continuous-observation", refresh_schedule_mode: "per_device",
        manual_mutations_available: false, managed_workflows_available: false, active_device_count: 0,
        pending_refresh_device_count: 0, device_cycles: {} });
      const page = await connectPage(debugOrigin, `${origin}/shuns/198.51.100.10`);
      try {
        assert.equal(await page.evaluate("document.querySelectorAll('[data-queue-form]').length"), 0);
        assert.equal(await page.evaluate("document.querySelector('.primary-nav a[href=\"/managed-shuns\"]')"), null);
        assert.equal(await page.evaluate("document.querySelector('.primary-nav a[href=\"/imports\"]').textContent"), "Import preview");
        assert.equal(await page.evaluate("document.querySelector('[data-runtime-notice]').hidden"), false);
        const before = postCount;
        await page.evaluate("document.querySelector('[data-refresh-request]').click()");
        await page.until("!document.querySelector('[data-refresh-request]').disabled");
        assert.equal(postCount, before + 1);
      } finally { await page.close(); }
      const preview = await connectPage(debugOrigin, `${origin}/imports`);
      try {
        assert.equal(await preview.evaluate("document.querySelector('button[formaction=\"/imports/review\"]')"), null);
        assert.equal(await preview.evaluate("document.querySelector('a[href=\"/managed-shuns/bulk\"]')"), null);
        assert.match(await preview.evaluate("document.querySelector('#import-preview-form').textContent"), /admission are unavailable/);
        assert.equal(await preview.evaluate("document.querySelector('#import-preview-form button[name=page]').textContent"), "Parse preview");
      } finally { await preview.close(); }
    });
    await t.test("v2 policy pages stay bounded, preserve drafts, show retained attention and never admit commands", async () => {
      const previous = managed;
      status = initial();
      Object.assign(status, { runtime_mode: "continuous-observation", managed_policy_format: 2,
        manual_mutations_available: false, managed_workflows_available: false,
        managed_policy_view_available: true, managed_policy_retirement_available: true });
      managed = { initialized: true, intent_format: 2, limit: 200000, revision: 7,
        restoration_suspended: true, attempt_ledger_initialized: true, read_only: true,
        entries: Array.from({length: 101}, (_, i) => ({ device_id: 1, hostname: "Synthetic FTD", ip: `198.18.0.${i+1}`,
          enabled: true, device_enabled: true, observed_present: i === 0, protected: i === 0,
          generation: 1, intent_id: "11111111-1111-4111-8111-111111111111", pending_jobs: 0,
          attention: i === 0, last_attempt_state: i === 0 ? "UNVERIFIED" : "NOOP",
          last_attempt_generation: 1, missing_unknown_job: i === 0, actor_subject: "synthetic",
          actor_display_name: "<b>Fixture author</b>", authorized_at: "2026-10-23T10:00:00Z",
          label: "<b>Escaped label</b>", reason: "Synthetic only" })) };
      const hints = postCount, executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/managed-shuns`);
      try {
        assert.equal(await page.evaluate("document.querySelectorAll('table[aria-label=\"Version-2 managed policy\"] tbody tr').length"), 100);
        assert.equal(await page.evaluate("document.querySelector('.primary-nav a[aria-current=page]').textContent"), "Managed shuns");
        assert.ok(await page.evaluate("document.querySelector('[data-runtime-notice]').textContent.includes('stop-maintaining is available')"));
        assert.ok(await page.evaluate("document.querySelector('#managed-shun-state').textContent.includes('Original unknown queue evidence is missing')"));
        assert.equal(await page.evaluate("document.querySelectorAll('#managed-shun-state td b').length"), 0);
        assert.equal(await page.evaluate("document.querySelectorAll('[data-queue-form], [action=\"/managed-shuns/grant-review\"]').length"), 0);
        await page.evaluate("document.querySelector('#retirement-target').closest('details').open=true; document.querySelector('#retirement-target').value='1:198.18.0.1'; document.querySelector('#retirement-reason').value='Keep this draft'; document.querySelector('#retirement-reason').focus()");
        status.data_revision += 1;
        const reads = pageReads;
        await wake(page);
        await page.until(`document.querySelector('#retirement-reason').value==='Keep this draft' && document.activeElement.id==='retirement-reason'`);
        const deadline = Date.now() + 8000;
        while (pageReads <= reads && Date.now() < deadline) await delay(50);
        assert.ok(pageReads > reads);
        assert.equal(await page.evaluate("document.querySelector('#retirement-target').value"), "1:198.18.0.1");
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        }
        const next = await page.evaluate("document.querySelector('a[rel=next]').getAttribute('href')");
        assert.equal(next, "/managed-shuns?page=2&revision=7");
        await page.call("Page.navigate", {url: origin + next});
        await page.until("document.querySelectorAll('table[aria-label=\"Version-2 managed policy\"] tbody tr').length===1");
        managed.revision += 1;
        status.data_revision += 1;
        await wake(page);
        await page.until("document.querySelector('#managed-shun-state').textContent.includes('No scope was rebased')");
        assert.equal(await page.evaluate("document.querySelector('#retirement-target')"), null);
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); managed = previous; }
    });
    await t.test("v2 removal confirmation is independently gated, frozen, escaped and usable on mobile", async () => {
      status = initial();
      Object.assign(status, { runtime_mode: "continuous-observation", managed_policy_format: 2,
        ready_removal_review_available: true, ready_removal_admission_enabled: true });
      const hints = postCount, executions = executionCount;
      const disabled = await connectPage(debugOrigin, `${origin}/managed-shuns/v2/removal-review`);
      try {
        assert.equal(await disabled.evaluate("document.querySelector('.import-confirm-form button').disabled"), true);
      } finally { await disabled.close(); }
      status.fixture_ready_local_enabled = true; // Renderer fixture, never a production status capability.
      const page = await connectPage(debugOrigin, `${origin}/managed-shuns/v2/removal-review`);
      try {
        assert.equal(await page.evaluate("document.querySelectorAll('table[aria-label=\"Frozen v2 removal scope\"] tbody tr').length"), 2);
        assert.equal(await page.evaluate("document.querySelector('.import-confirm-form button').disabled"), false);
        assert.equal(await page.evaluate("document.querySelectorAll('td b').length"), 0);
        assert.equal(await page.evaluate("document.querySelector('.import-confirm-form').checkValidity()"), false);
        const key = await page.evaluate("document.querySelector('input[name=review]').value");
        await page.evaluate("document.querySelector('#confirm-ready-ip').value='198.51.100.251'; document.querySelector('#confirm-ready-ip').focus()");
        const reads = pageReads;
        status.data_revision += 1;
        status.status_revision += 1;
        await wake(page);
        await delay(300);
        assert.equal(pageReads, reads);
        assert.equal(await page.evaluate("document.querySelector('input[name=review]').value"), key);
        assert.equal(await page.evaluate("document.querySelector('#confirm-ready-ip').value"), "198.51.100.251");
        assert.equal(await page.evaluate("document.activeElement.id"), "confirm-ready-ip");
        assert.equal(await page.evaluate("document.querySelector('.import-confirm-form').checkValidity()"), true);
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
          assert.ok(await page.evaluate("document.querySelector('.import-confirm-form button').getBoundingClientRect().top>document.querySelector('#confirm-ready-ip').getBoundingClientRect().bottom"));
        }
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("ordered confirmation keeps separate gates, frozen scope, focus and mobile spacing", async () => {
      status = initial();
      Object.assign(status, { runtime_mode: "continuous-observation", managed_policy_format: 2,
        ordered_removal_review_available: true, ordered_removal_admission_enabled: true,
        ordered_removal_promotion_enabled: true });
      const hints = postCount, executions = executionCount;
      const disabled = await connectPage(debugOrigin, `${origin}/managed-shuns/v2/ordered-removal-review`);
      try {
        assert.equal(await disabled.evaluate("document.querySelector('.import-confirm-form button').disabled"), true);
      } finally { await disabled.close(); }
      status.fixture_ordered_local_enabled = true; // Synthetic renderer setting, not a production API capability.
      const page = await connectPage(debugOrigin, `${origin}/managed-shuns/v2/ordered-removal-review`);
      try {
        assert.equal(await page.evaluate("document.querySelectorAll('table[aria-label=\"Frozen ordered removal scope\"] tbody tr').length"), 2);
        assert.equal(await page.evaluate("document.querySelector('.import-confirm-form button').disabled"), false);
        assert.equal(await page.evaluate("document.querySelectorAll('td b').length"), 0);
        assert.equal(await page.evaluate("document.querySelector('.import-confirm-form').checkValidity()"), false);
        const key = await page.evaluate("document.querySelector('input[name=review]').value");
        await page.evaluate("document.querySelector('#confirm-ordered-ip').value='198.51.100.251';document.querySelector('#confirm-ordered-ip').focus()");
        const reads = pageReads;
        status.data_revision += 1;
        await wake(page);
        await delay(300);
        assert.equal(pageReads, reads);
        assert.equal(await page.evaluate("document.querySelector('input[name=review]').value"), key);
        assert.equal(await page.evaluate("document.activeElement.id"), "confirm-ordered-ip");
        assert.equal(await page.evaluate("document.querySelector('.import-confirm-form').checkValidity()"), true);
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
          assert.ok(await page.evaluate("document.querySelector('.import-confirm-form button').getBoundingClientRect().top>document.querySelector('#confirm-ordered-ip').getBoundingClientRect().bottom"));
        }
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("ordered status updates local evidence, retains dirty waiting form and never implies premature success", async () => {
      status = initial();
      Object.assign(status, { runtime_mode: "continuous-observation", managed_policy_format: 2,
        ordered_removal_review_available: true, fixture_ordered_phase: "WAITING_ADD" });
      const hints = postCount, executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/managed-shuns/v2/ordered-removals/88888888-8888-4888-8888-888888888888`);
      try {
        assert.ok(await page.evaluate("document.querySelector('[data-ordered-phase]').textContent.includes('not confirmed')"));
        await page.evaluate("document.querySelector('#ordered-wait-cancellation').open=true;document.querySelector('#cancel-ordered-ip').value='198.51.100.251';document.querySelector('#cancel-ordered-ip').focus()");
        status.fixture_ordered_phase = "ATTENTION";
        status.data_revision += 1;
        await wake(page);
        await page.until("document.querySelector('[data-ordered-phase]').textContent.includes('ATTENTION')");
        assert.equal(await page.evaluate("document.querySelector('#ordered-wait-cancellation').open"), true);
        assert.equal(await page.evaluate("document.querySelector('#cancel-ordered-ip').value"), "198.51.100.251");
        assert.equal(await page.evaluate("document.activeElement.id"), "cancel-ordered-ip");
        status.fixture_ordered_phase = "ADMITTED";
        status.data_revision += 1;
        await wake(page);
        await page.until("document.querySelector('[data-ordered-phase]').textContent.includes('ADMITTED')");
        assert.equal(await page.evaluate("document.querySelector('#cancel-ordered-ip')"), null);
        assert.ok(await page.evaluate("document.querySelector('[data-ordered-phase]').textContent.includes('not confirmed')"));
        status.fixture_ordered_phase = "VERIFIED";
        status.data_revision += 1;
        await wake(page);
        await page.until("document.querySelector('[data-ordered-phase]').textContent.includes('All original REMOVE jobs verified')");
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        }
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("v2 draft workspace preserves pasted text and device choices without automatic creation", async () => {
      status = initial();
      Object.assign(status, { runtime_mode: "continuous-observation", managed_policy_format: 2,
        managed_workflows_available: false, bulk_import_preparation_available: true });
      const hints = postCount, executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/managed-imports/v2`);
      try {
        assert.equal(await page.evaluate("document.querySelector('.primary-nav [aria-current=page]').getAttribute('href')"), "/managed-imports/v2");
        assert.equal(await page.evaluate("document.querySelector('#bulk-draft-form').checkValidity()"), false);
        await page.evaluate("document.querySelector('#bulk-source').value='shun 198.51.100.250 # draft only';document.querySelector('input[name=device_ids][value=\"1\"]').checked=true;document.querySelector('#bulk-label').value='Keep my label';document.querySelector('#bulk-source').focus()");
        const reads = pageReads;
        status.data_revision += 1;
        await wake(page);
        await delay(300);
        assert.equal(pageReads, reads);
        assert.equal(await page.evaluate("document.querySelector('#bulk-source').value"), "shun 198.51.100.250 # draft only");
        assert.equal(await page.evaluate("document.querySelector('#bulk-label').value"), "Keep my label");
        assert.equal(await page.evaluate("document.querySelector('input[name=device_ids][value=\"1\"]').checked"), true);
        assert.equal(await page.evaluate("document.querySelector('input[name=device_ids][value=\"2\"]').disabled"), true);
        assert.equal(await page.evaluate("document.activeElement.id"), "bulk-source");
        assert.equal(await page.evaluate("document.querySelector('#bulk-draft-form').checkValidity()"), true);
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        }
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
      status.fixture_bulk_storage = false;
      const absent = await connectPage(debugOrigin, `${origin}/managed-imports/v2`);
      try {
        assert.equal(await absent.evaluate("document.querySelector('#bulk-draft-form button').disabled"), true);
        assert.ok(await absent.evaluate("document.body.textContent.includes('journal is not initialized')"));
      } finally { await absent.close(); }
    });
    await t.test("v2 frozen report and exact proposal paginate, escape and highlight exclusions without admission", async () => {
      status = initial();
      Object.assign(status, { runtime_mode: "continuous-observation", managed_policy_format: 2,
        managed_workflows_available: false, bulk_import_preparation_available: true });
      const hints = postCount, executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/managed-imports/v2/33333333-3333-4333-8333-333333333333/review`);
      try {
        assert.equal(await page.evaluate("document.querySelectorAll('table[aria-label=\"Frozen bulk targets\"] tbody tr').length"), 100);
        assert.equal(await page.evaluate("document.querySelectorAll('table[aria-label=\"Frozen bulk targets\"] td b').length"), 0);
        assert.equal(await page.evaluate("document.querySelectorAll('.protected-shun').length"), 1);
        assert.ok(await page.evaluate("document.querySelector('section[aria-label=\"Frozen policy proposal\"] form').getAttribute('action').endsWith('/confirmation-review')"));
        assert.equal(await page.evaluate("document.querySelector('form[action$=\"/confirm\"]')"), null);
        const binding = await page.evaluate("document.querySelector('.import-review-metadata').textContent");
        const reads = pageReads;
        status.data_revision += 1;
        await wake(page);
        await delay(300);
        assert.equal(pageReads, reads);
        assert.equal(await page.evaluate("document.querySelector('.import-review-metadata').textContent"), binding);
        const next = await page.evaluate("document.querySelector('a[rel=next]').getAttribute('href')");
        await page.call("Page.navigate", {url: origin + next});
        await page.until("document.querySelectorAll('table[aria-label=\"Frozen bulk targets\"] tbody tr').length===2");
        assert.equal(await page.evaluate("document.querySelectorAll('table[aria-label=\"Bulk source diagnostics\"] tbody tr').length"), 3);
        assert.equal(await page.evaluate("document.querySelector('[data-preview-status=Invalid]').textContent.includes('Invalid')"), true);
        assert.equal(await page.evaluate("document.querySelector('a[rel=prev]').getAttribute('href')"), "/managed-imports/v2/33333333-3333-4333-8333-333333333333/review?page=1");
        assert.equal(await page.evaluate("document.querySelector('.import-review-metadata').textContent"), binding);
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        }
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("v2 standing consent requires exact count and recurring consent, preserving frozen input and focus", async () => {
      status = initial();
      Object.assign(status, { runtime_mode: "continuous-observation", managed_policy_format: 2,
        bulk_import_preparation_available: true, bulk_policy_admission_enabled: true, bulk_policy_admission_device_ids: [1] });
      const hints = postCount, executions = executionCount;
      const gated = await connectPage(debugOrigin, `${origin}/managed-imports/v2/confirmation-review`);
      try {
        assert.equal(await gated.evaluate("document.querySelector('#bulk-policy-consent button').disabled"), true);
      } finally { await gated.close(); }
      status.fixture_bulk_policy_local_enabled = true;
      const page = await connectPage(debugOrigin, `${origin}/managed-imports/v2/confirmation-review`);
      try {
        assert.equal(await page.evaluate("document.querySelector('#bulk-policy-consent button').disabled"), false);
        assert.equal(await page.evaluate("document.querySelector('#bulk-policy-consent').checkValidity()"), false);
        await page.evaluate("document.querySelector('#bulk-accepted-count').value='102';document.querySelector('input[name=maintain_present]').checked=true");
        assert.equal(await page.evaluate("document.querySelector('#bulk-policy-consent').checkValidity()"), false);
        await page.evaluate("document.querySelector('#bulk-accepted-count').value='101';document.querySelector('#bulk-accepted-count').focus()");
        assert.equal(await page.evaluate("document.querySelector('#bulk-policy-consent').checkValidity()"), true);
        assert.equal(await page.evaluate("document.querySelectorAll('.import-review-metadata b').length"), 0);
        assert.equal(await page.evaluate("document.querySelectorAll('.protected-shun').length"), 1);
        const binding = await page.evaluate("document.querySelector('.import-review-metadata').textContent");
        const reads = pageReads;
        status.data_revision += 1;
        status.status_revision += 1;
        await wake(page);
        await delay(300);
        assert.equal(pageReads, reads);
        assert.equal(await page.evaluate("document.activeElement.id"), "bulk-accepted-count");
        assert.equal(await page.evaluate("document.querySelector('#bulk-accepted-count').value"), "101");
        assert.equal(await page.evaluate("document.querySelector('input[name=maintain_present]').checked"), true);
        assert.equal(await page.evaluate("document.querySelector('.import-review-metadata').textContent"), binding);
        assert.equal(await page.evaluate("document.querySelector('button[name=page]').formNoValidate"), true);
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
          assert.equal(await page.evaluate("document.querySelector('#bulk-policy-consent button').getBoundingClientRect().top>=document.querySelector('#bulk-accepted-count').getBoundingClientRect().bottom"), true);
        }
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("v2 historical policy receipt stays read-only and paged without false execution success", async () => {
      status = initial();
      Object.assign(status, { runtime_mode: "continuous-observation", managed_policy_format: 2,
        bulk_import_preparation_available: true });
      const hints = postCount, executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/managed-imports/v2/receipts/fixture`);
      try {
        assert.equal(await page.evaluate("document.querySelectorAll('table[aria-label=\"Historical policy members\"] tbody tr').length"), 100);
        assert.equal(await page.evaluate("document.querySelector('form[action*=confirm]')"), null);
        assert.equal(await page.evaluate("document.body.textContent.includes('does not prove current maintenance or any device ADD')"), true);
        assert.equal(await page.evaluate("document.querySelectorAll('main b').length"), 0);
        const reads = pageReads;
        status.data_revision += 1;
        await wake(page);
        await delay(300);
        assert.equal(pageReads, reads);
        const next = await page.evaluate("document.querySelector('a[rel=next]').getAttribute('href')");
        await page.call("Page.navigate", { url: origin + next });
        await page.until("document.querySelectorAll('table[aria-label=\"Historical policy members\"] tbody tr').length===2");
        assert.equal(await page.evaluate("document.querySelector('nav.history-pagination').textContent.includes('Page 2 / 2')"), true);
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        }
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("concurrent standing consent has an independent local gate and honest active historical receipt", async () => {
      status = initial();
      Object.assign(status, { runtime_mode: "continuous-observation", managed_policy_format: 2,
        bulk_import_preparation_available: true, bulk_policy_admission_enabled: true, bulk_policy_admission_device_ids: [1],
        bulk_policy_concurrent_enabled: true, managed_execution_suspended: false, fixture_bulk_policy_local_enabled: true });
      const hints = postCount, executions = executionCount;
      const gated = await connectPage(debugOrigin, `${origin}/managed-imports/v2/confirmation-review`);
      try {
        assert.equal(await gated.evaluate("document.querySelector('#bulk-policy-consent button').disabled"), true);
      } finally { await gated.close(); }
      status.fixture_bulk_policy_local_concurrent = true;
      const page = await connectPage(debugOrigin, `${origin}/managed-imports/v2/confirmation-review`);
      try {
        assert.equal(await page.evaluate("document.querySelector('#bulk-policy-consent button').disabled"), false);
        assert.equal(await page.evaluate("document.querySelector('h1').textContent.includes('alongside active work')"), true);
        assert.equal(await page.evaluate("document.body.textContent.includes('already active when reviewed')"), true);
        await page.evaluate("document.querySelector('#bulk-accepted-count').value='101';document.querySelector('input[name=maintain_present]').checked=true;document.querySelector('#bulk-accepted-count').focus()");
        const binding = await page.evaluate("document.querySelector('.import-review-metadata').textContent");
        const reads = pageReads;
        status.data_revision += 1;
        status.managed_execution_suspended = true;
        await wake(page);
        await delay(300);
        assert.equal(pageReads, reads);
        assert.equal(await page.evaluate("document.activeElement.id"), "bulk-accepted-count");
        assert.equal(await page.evaluate("document.querySelector('#bulk-accepted-count').value"), "101");
        assert.equal(await page.evaluate("document.querySelector('.import-review-metadata').textContent"), binding);
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        }
      } finally { await page.close(); }
      status.fixture_fenced_receipt = true;
      status.bulk_policy_concurrent_enabled = false;
      const historical = await connectPage(debugOrigin, `${origin}/managed-imports/v2/receipts/fixture`);
      try {
        assert.equal(await historical.evaluate("document.body.textContent.includes('while desired execution was already active')"), true);
        assert.equal(await historical.evaluate("document.body.textContent.includes('not current worker eligibility')"), true);
        assert.equal(await historical.evaluate("document.body.textContent.includes('Policy was saved with restoration suspended')"), false);
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await historical.close(); }
    });
    await t.test("v2 cancellation consent preserves exact count and scope without an admission gate", async () => {
      status = initial();
      Object.assign(status, { runtime_mode: "continuous-observation", managed_policy_format: 2,
        bulk_import_cancellation_available: true, bulk_policy_admission_enabled: false });
      const hints = postCount, executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/managed-imports/v2/cancellation-review`);
      try {
        assert.equal(await page.evaluate("document.querySelector('#bulk-cancellation-consent button').disabled"), false);
        assert.equal(await page.evaluate("document.querySelector('#bulk-cancellation-consent').checkValidity()"), false);
        await page.evaluate("document.querySelector('#cancel-accepted-count').value='102'");
        assert.equal(await page.evaluate("document.querySelector('#bulk-cancellation-consent').checkValidity()"), false);
        await page.evaluate("document.querySelector('#cancel-accepted-count').value='101';document.querySelector('#cancel-accepted-count').focus()");
        assert.equal(await page.evaluate("document.querySelector('#bulk-cancellation-consent').checkValidity()"), true);
        const binding = await page.evaluate("document.querySelector('.import-review-metadata').textContent");
        const reads = pageReads;
        status.data_revision += 1;
        await wake(page);
        await delay(300);
        assert.equal(pageReads, reads);
        assert.equal(await page.evaluate("document.activeElement.id"), "cancel-accepted-count");
        assert.equal(await page.evaluate("document.querySelector('#cancel-accepted-count').value"), "101");
        assert.equal(await page.evaluate("document.querySelector('.import-review-metadata').textContent"), binding);
        assert.equal(await page.evaluate("document.querySelectorAll('table[aria-label=\"Frozen cancellation members\"] tbody tr').length"), 100);
        assert.equal(await page.evaluate("document.body.textContent.includes('does not unblock an IP')"), true);
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
          assert.equal(await page.evaluate("document.querySelector('#bulk-cancellation-consent button').getBoundingClientRect().top>=document.querySelector('#cancel-accepted-count').getBoundingClientRect().bottom"), true);
        }
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("v2 cancellation local status updates settlements, preserves original receipt and never hides unknown attention", async () => {
      status = initial();
      Object.assign(status, { runtime_mode: "continuous-observation", managed_policy_format: 2, bulk_import_cancellation_available: true });
      const hints = postCount, executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/managed-imports/v2/cancellations/fixture`);
      try {
        assert.equal(await page.evaluate("document.querySelector('[data-cancellation-phase]').textContent.includes('WAITING_OUTCOME')"), true);
        await page.evaluate("document.querySelector('#bulk-cancellation-original').open=true");
        const original = await page.evaluate("document.querySelector('#bulk-cancellation-original').textContent");
        status.fixture_bulk_cancel_outcome = "UNVERIFIED";
        status.data_revision += 1;
        status.status_revision += 1;
        await wake(page);
        await page.until("document.querySelector('[data-cancellation-phase]').textContent.includes('SETTLED')");
        assert.equal(await page.evaluate("document.querySelector('[data-cancellation-phase]').textContent.includes('1 require attention')"), true);
        assert.equal(await page.evaluate("document.querySelector('#bulk-cancellation-original').open"), true);
        assert.equal(await page.evaluate("document.querySelector('#bulk-cancellation-original').textContent"), original);
        assert.equal(await page.evaluate("document.querySelector('table[aria-label=\"Current cancellation members\"]').textContent.includes('STOPPED_UNVERIFIED')"), true);
        const next = await page.evaluate("document.querySelector('nav[aria-label=\"Cancellation pages\"] a[rel=next]').getAttribute('href')");
        await page.call("Page.navigate", { url: origin + next });
        await page.until("document.querySelectorAll('table[aria-label=\"Current cancellation members\"] tbody tr').length===1");
        assert.equal(await page.evaluate("document.querySelector('nav[aria-label=\"Cancellation pages\"]').textContent.includes('Page 2 / 2')"), true);
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        }
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
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
    await t.test("permanent protection retirement retains its reviewed revision until explicit reload", async () => {
      status = initial();
      status.policy_revision = 1;
      status.managed_policy_revision = 10;
      status.managed_policy_initialized = true;
      policy = { revision: 1, limit: 1000, managed_policy_available: true, managed_revision: 10, entries: [
        { ip: "198.51.100.10", name: "Maintained office", comment: "Fixture", enabled: true,
          active_devices: 0, last_auto_removed_at: null, maintained_devices: 2 },
      ] };
      const hints = postCount;
      const executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/protected-ips`);
      try {
        assert.ok(await page.evaluate("document.querySelector('[data-maintenance-warning]').textContent.includes('Enabled maintenance: 2')"));
        await page.evaluate(`(() => { const form=document.getElementById('edit-policy-form-198.51.100.10'); form.closest('details').open=true;
          form.elements.enabled.checked=false;
          form.elements.enabled.dispatchEvent(new Event('input',{bubbles:true})); })()`);
        policy.managed_revision = status.managed_policy_revision = 11;
        policy.entries[0].maintained_devices = 3;
        status.status_revision += 1;
        await wake(page);
        await page.until("document.querySelector('[data-maintenance-warning]').textContent.includes('Enabled maintenance: 3')");
        assert.equal(await page.evaluate("document.getElementById('edit-policy-form-198.51.100.10').elements.managed_revision.value"), "10");
        assert.equal(await page.evaluate("document.getElementById('edit-policy-form-198.51.100.10').elements.enabled.checked"), false);
        assert.equal(await page.evaluate("document.getElementById('delete-policy-form-198.51.100.10').elements.managed_revision.value"), "11");
        await page.evaluate("document.getElementById('edit-policy-form-198.51.100.10').requestSubmit()");
        await page.until("document.querySelector('[data-action-warning]').textContent.includes('Managed policy changed')");
        assert.equal(policy.entries[0].enabled, true);
      } finally { await page.close(); }
      const clean = await connectPage(debugOrigin, `${origin}/protected-ips`);
      try {
        assert.equal(await clean.evaluate("document.getElementById('edit-policy-form-198.51.100.10').elements.managed_revision.value"), "11");
        assert.equal(await clean.evaluate("document.querySelector('[name=confirm_maintenance_resume]')"), null);
        assert.equal(await clean.evaluate("document.getElementById('add-policy-form').elements.managed_revision.value"), "11");
        assert.ok(await clean.evaluate("document.querySelector('[data-maintenance-warning]').textContent.includes('permanently stop')"));
        await clean.call("Emulation.setDeviceMetricsOverride", { width: 375, height: 800, deviceScaleFactor: 1, mobile: true });
        assert.equal(await clean.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await clean.close(); }
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
        assert.equal(await page.evaluate("document.querySelector('#active-shuns td time').dateTime"), "2026-10-15T10:00:00Z", "Current appearance is displayed, not lifetime first detection");
        assert.ok(await page.evaluate("document.querySelector('#active-shuns td time').textContent !== '2026-10-15T10:00:00Z'"), "Current appearance is localized");
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
    await t.test("ADD eligibility, live phase and occurrence provenance render without device mutations", async () => {
      status = initial();
      policy = { revision: 0, limit: 1000, entries: [] };
      shunOrigins = [{ source: "manual_import", batch_id: "fixture-batch", operation_id: "fixture-operation",
        actor_display_name: "Test Operator", label: "<img src=x onerror=alert(1)>", reason: "<script>fixture</script>",
        verified_at: "2026-10-15T10:00:00Z" }];
      status.queue = { revision: 1, counts: { QUEUED: 1 }, add_execution_enabled: false, items: [
        { id: "held-add", action: "ADD", device_id: 1, hostname: "lab-ftd", ip: "198.51.100.10", state: "QUEUED",
          requested_at: future(0), reason: "ADD execution is not enabled", requests: [
            { id: "fixture-request", actor_subject: "test", actor_display_name: "Test Operator", source: "manual_import", state: "ACTIVE" },
          ] },
      ] };
      const writes = removalKeys.length;
      const page = await connectPage(debugOrigin, `${origin}/`);
      try {
        await page.until("Boolean(document.querySelector('#active-shuns .import-origin'))");
        assert.equal(await page.evaluate("document.querySelector('.import-origin').textContent"), "Manually imported");
        await page.evaluate("document.querySelector('#queue-menu').open=true");
        await page.until("document.querySelector('[data-operation-queue]').textContent.includes('Held — ADD execution disabled')");
        assert.ok(await page.evaluate("document.querySelector('[data-operation-queue]').textContent.includes('Add · lab-ftd')"));
        status.import_execution_enabled = true;
        status.session_cycles_enabled = true;
        status.refresh_in_progress = true;
        status.device_cycle = { device_id: 1, action: "add_and_verify", ip: "198.51.100.10", completed: 0, limit: 16 };
        status.queue.items[0].execution_enabled = true;
        status.queue.items[0].state = "RUNNING";
        status.queue.items[0].reason = null;
        status.queue.counts = { RUNNING: 1 };
        status.status_revision += 1;
        await wake(page);
        await page.until("document.querySelector('[data-cycle-progress]').textContent.includes('Adding and verifying')");
        assert.equal(await page.evaluate("document.querySelector('[data-operation-queue]').textContent.includes('Held')"), false);
        assert.equal(await page.evaluate("Boolean(document.querySelector('[data-operation-queue] progress:not([value])'))"), true);
        status.import_execution_enabled = false;
        status.refresh_in_progress = false;
        status.queue.items[0].execution_enabled = false;
        status.queue.items[0].state = "QUEUED";
        status.queue.counts = { QUEUED: 1 };
        status.status_revision += 1;
        await wake(page);
        await page.until("document.querySelector('[data-operation-queue]').textContent.includes('Held — ADD execution disabled')");
        await page.evaluate("document.querySelector('[data-operation-cancel]').click()");
        await page.until("document.querySelector('[data-queue-completed]').textContent.includes('CANCELLED')");
        await page.call("Page.navigate", { url: `${origin}/shuns/198.51.100.10` });
        await page.until("document.querySelector('#device-shuns').textContent.includes('Import provenance')");
        assert.equal(await page.evaluate("document.querySelectorAll('#device-shuns img,#device-shuns script').length"), 0);
        assert.ok(await page.evaluate("document.querySelector('#device-shuns').textContent.includes('<script>fixture</script>')"));
        shunOrigins = [];
        complete();
        await wake(page);
        await page.until("!document.querySelector('#device-shuns .import-origin')");
        assert.equal(removalKeys.length, writes, "Holding/cancelling/provenance refresh does not submit a device mutation");
      } finally { await page.close(); shunOrigins = []; }
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
        assert.ok(await page.evaluate("document.querySelector('#recent-events').textContent.includes('Unverified operations and unresolved cleanup evidence are kept beyond this period.')"));
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
          for (const phase of ["refreshing", "error", "paused", "cleanup_error", "restoration_error", "ready"]) {
            status.refresh_in_progress = phase === "refreshing";
            status.devices["1"].state = ["paused", "cleanup_error", "restoration_error"].includes(phase) ? "ready" : phase;
            status.devices["1"].stale = phase === "error";
            status.last_error = phase === "error" ? "A long device failure. ".repeat(12) : null;
            status.queue.counts = phase === "error" ? { UNVERIFIED: 12345 } : {};
            status.queue.mutations_suspended = phase === "paused";
            status.managed_removal_worker_error = phase === "cleanup_error" ? "Managed cleanup handoff failed; mutations skipped for this cycle." : null;
            status.managed_restoration_error = phase === "restoration_error" ? "Managed restoration failed; mutations skipped for this cycle." : null;
            status.status_revision += 1;
            await wake(page);
            const label = { refreshing: "Refreshing", error: "Error", ready: "Current", paused: "Current", cleanup_error: "Current", restoration_error: "Current" }[phase];
            await page.until(`document.querySelector('[data-device-status]').textContent.includes('${label}')`);
            await page.until(`document.querySelector('[data-recovery-warning]').hidden === ${!["paused", "cleanup_error", "restoration_error"].includes(phase)}`);
            if (phase === "paused") assert.ok(await page.evaluate("document.querySelector('[data-recovery-warning]').textContent.includes('Monitoring continues')"));
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
    await t.test("frozen import review keeps its token and draft through status updates; native confirmation stays explicit", async () => {
      status = initial();
      status.import_admission_enabled = false;
      const hints = postCount;
      const executions = executionCount;
      const confirmations = confirmationPosts;
      const disabled = await connectPage(debugOrigin, `${origin}/imports/review`);
      try {
        assert.equal(await disabled.evaluate("document.querySelector('.import-confirm-form button').disabled"), true);
        assert.ok(await disabled.evaluate("document.body.textContent.includes('admission is disabled')"));
      } finally { await disabled.close(); }
      status.import_admission_enabled = true;
      const page = await connectPage(debugOrigin, `${origin}/imports/review`);
      try {
        assert.equal(await page.evaluate("document.querySelectorAll('.import-review-targets tbody tr').length"), 1);
        assert.equal(await page.evaluate("document.querySelectorAll('.import-review-metadata b').length"), 0);
        await page.evaluate("window.reviewToken=document.querySelector('[name=review]').value; document.querySelector('#confirm-count').value='1'; document.querySelector('#confirm-count').focus()");
        const reads = pageReads;
        complete("partial");
        await wake(page);
        await page.until("document.querySelector('[data-refresh-message]').textContent.includes('partially completed')");
        await delay(700);
        assert.equal(pageReads, reads, "Frozen POST view must not cause metadata-driven GET/reparse");
        assert.equal(await page.evaluate("document.querySelector('[name=review]').value===window.reviewToken"), true);
        assert.equal(await page.evaluate("document.querySelector('#confirm-count').value"), "1");
        assert.equal(await page.evaluate("document.activeElement.id"), "confirm-count");
        assert.equal(confirmationPosts, confirmations);
        await page.call("Emulation.setDeviceMetricsOverride", { width: 375, height: 800, deviceScaleFactor: 1, mobile: true });
        assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        await page.evaluate("document.querySelector('#confirm-count').value='2'; document.querySelector('.import-confirm-form').requestSubmit()");
        await delay(100);
        assert.equal(confirmationPosts, confirmations, "Wrong count fails native validation");
        await page.evaluate("document.querySelector('#confirm-count').value='1'; document.querySelector('.import-confirm-form').requestSubmit()");
        await page.until("Boolean(document.body?.textContent.includes('Fixture admission received'))");
        assert.equal(confirmationPosts, confirmations + 1);
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("managed pagination stays bounded through live updates and exposes membership conflicts", async () => {
      status = initial();
      status.managed_policy_revision = 1;
      status.managed_policy_initialized = true;
      status.managed_policy_available = true;
      const original = managed;
      const hints = postCount, executions = executionCount;
      managed = { initialized: true, revision: 1, limit: 1000, restoration_suspended: true,
        controller_available: true, controller_enabled: false,
        entries: Array.from({ length: 251 }, (_, i) => ({ device_id: 1, hostname: "synthetic-ftd",
          ip: `198.18.0.${i}`, enabled: true, device_enabled: true, observed_present: false,
          protected: false, generation: 1, actor_subject: "test", actor_display_name: "Test Operator",
          authorized_at: "2026-10-21T10:00:00Z", label: "Synthetic", reason: "No device work" })) };
      const page = await connectPage(debugOrigin, `${origin}/managed-shuns`);
      try {
        await page.until("document.querySelector('[aria-label=\"Managed policy pagination\"]')?.textContent.includes('Page 1 of 3')");
        assert.equal(await page.evaluate("document.querySelectorAll('[aria-label=\"Managed shun policy\"] tbody tr').length"), 100);
        await page.evaluate("document.querySelector('[aria-label=\"Managed policy pagination\"] a[rel=next]').click()");
        await page.until("location.search.includes('page=2') && document.querySelector('[aria-label=\"Managed policy pagination\"]')?.textContent.includes('Page 2 of 3')");
        assert.equal(await page.evaluate("document.querySelector('[aria-label=\"Managed shun policy\"] tbody a').textContent"), "198.18.0.100");
        assert.equal(await page.evaluate("document.querySelectorAll('#managed-review-target option').length"), 101);
        managed.entries[100].observed_present = true;
        status.data_revision += 1;
        status.status_revision += 1;
        await wake(page);
        await page.until("document.querySelector('[aria-label=\"Managed shun policy\"] tbody tr').textContent.includes('Observed present')");
        assert.ok(await page.evaluate("location.search.includes('page=2')"));
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        }
        managed.revision += 1;
        status.managed_policy_revision += 1;
        status.status_revision += 1;
        await wake(page);
        await page.until("document.querySelector('#managed-shun-state').textContent.includes('Managed policy changed while')");
        assert.equal(await page.evaluate("document.querySelector('#managed-shun-state').textContent.includes('has not been initialized')"), false);
        assert.equal(await page.evaluate("Boolean(document.querySelector('#managed-review-target'))"), false);
        await page.evaluate("document.querySelector('#managed-shun-state a[href=\"/managed-shuns\"]').click()");
        await page.until("location.search==='' && Boolean(document.querySelector('[aria-label=\"Managed shun policy\"]'))");
        assert.equal(await page.evaluate("document.querySelectorAll('[aria-label=\"Managed shun policy\"] tbody tr').length"), 100);
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { managed = original; await page.close(); }
    });
    await t.test("version footer and read-only managed state work on mobile and follow policy revisions without hints", async () => {
      status = initial();
      status.managed_policy_revision = 0;
      status.managed_policy_initialized = false;
      status.managed_policy_available = true;
      const hints = postCount;
      const executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/managed-shuns`);
      try {
        assert.ok(await page.evaluate("document.querySelector('#managed-shun-state').textContent.includes('has not been initialized')"));
        assert.match(await page.evaluate("document.querySelector('[data-product-version]').textContent"), /^v\d+\.\d+\.\d+/);
        assert.equal(await page.evaluate("getComputedStyle(document.querySelector('.app-footer')).position"), "static");
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.querySelector('.app-footer').getBoundingClientRect().top>=document.querySelector('main').getBoundingClientRect().bottom-1"), true);
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        }
        managed = { ...managed, initialized: true, revision: 1, entries: [
          { device_id: 1, hostname: "lab-ftd", ip: "198.51.100.251", enabled: true, device_enabled: true,
            intent_id: "00000000-0000-4000-8000-000000000001",
            observed_present: false, protected: false, generation: 1, actor_subject: "test", actor_display_name: "Test Operator",
            authorized_at: "2026-10-17T10:00:00Z", label: "<img src=x onerror=alert(1)>", reason: "Fixture only" },
        ] };
        status.managed_policy_initialized = true;
        status.managed_policy_revision = 1;
        status.status_revision += 1;
        await wake(page);
        await page.until("document.querySelector('#managed-shun-state').textContent.includes('Maintain presence')");
        assert.ok(await page.evaluate("document.querySelector('#managed-shun-state').textContent.includes('Not currently observed')"));
        assert.equal(await page.evaluate("document.querySelectorAll('#managed-shun-state img, #managed-shun-state form, #managed-shun-state button').length"), 0);
        assert.equal(await page.evaluate("document.querySelectorAll('#managed-removal-preparation form').length"), 1);
        assert.ok(await page.evaluate("document.querySelector('.local-timestamp').textContent.match(/GMT|UTC/) !== null"));
        assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        managed.entries[0].protected = true;
        status.policy_revision = 2;
        status.status_revision += 1;
        await wake(page);
        await page.until("document.querySelector('#managed-shun-state').textContent.includes('Blocked by Protected IP')");
        managed.entries[0].enabled = false;
        managed.revision += 1;
        status.managed_policy_revision += 1;
        status.status_revision += 1;
        await wake(page);
        await page.until("document.querySelector('#managed-shun-state').textContent.includes('Maintenance stopped')");
        Object.assign(managed.entries[0], { enabled: true, protected: false, restoration_attention: true,
          restoration_state: "UNVERIFIED", restoration_generation: 1, last_verified_restoration_at: null });
        status.queue.revision += 1;
        await wake(page);
        await page.until("document.querySelector('#managed-shun-state').textContent.includes('Restoration needs reviewed resolution')");
        assert.ok(await page.evaluate("document.querySelector('#managed-shun-state').textContent.includes('Last attempt: UNVERIFIED')"));
        assert.ok(await page.evaluate("document.querySelector('#managed-shun-state').textContent.includes('Not recorded')"));
        managed.entries[0].last_verified_restoration_at = "2026-10-18T10:00:00Z";
        status.queue.revision += 1;
        await wake(page);
        await page.until("Boolean(document.querySelector('#managed-shun-state time[datetime=\"2026-10-18T10:00:00Z\"]')?.textContent.match(/GMT|UTC/))");
        Object.assign(managed.entries[0], { enabled: false, protected: true, restoration_attention: false });
        handoffs = { initialized: true, counts: { WAITING_ADD: 1 }, display_limit: 20, items: [
          { id: "00000000-0000-4000-8000-000000000002", device_hostname: "lab-ftd", ip: "198.51.100.251",
            actor_subject: "test", actor_display_name: "<script>Fixture</script>", state: "WAITING_ADD",
            queue_state: null, reason: null, requested_at: "2026-10-17T10:00:00Z", expires_at: "2026-10-17T10:15:00Z" },
        ] };
        status.queue.revision += 1;
        await wake(page);
        await page.until("document.querySelector('#managed-removal-state').textContent.includes('Waiting for ADD to finish')");
        assert.equal(await page.evaluate("document.querySelectorAll('#managed-removal-state script').length"), 0);
        const waitingColor = await page.evaluate("getComputedStyle(document.querySelector('.cleanup-state')).backgroundColor");
        handoffs.items[0].state = "ADMITTED";
        handoffs.items[0].queue_state = "UNVERIFIED";
        status.queue.revision += 1;
        await wake(page);
        await page.until("document.querySelector('#managed-removal-state').textContent.includes('Outcome unknown')");
        assert.notEqual(await page.evaluate("getComputedStyle(document.querySelector('.cleanup-state')).backgroundColor"), waitingColor);
        handoffs.items[0].queue_state = "VERIFIED";
        status.queue.revision += 1;
        await wake(page);
        await page.until("document.querySelector('#managed-removal-state').textContent.includes('Verified removal')");
        assert.equal(await page.evaluate("document.querySelector('#managed-removal-state details').open"), false);
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("fleet cleanup keeps outcomes honest, mobile spacing and wait cancellation without hints", async () => {
      status = initial();
      const hints = postCount;
      const executions = executionCount;
      const key = "00000000-0000-4000-8000-000000000003";
      const item = { id: key, ip: "198.51.100.251", state: "WAITING_ADD", reason: null,
        actor_subject: "test", actor_display_name: "<script>Fixture</script>",
        target_count: 3, scope_sample: [{ device_id: 1, hostname: "synthetic-1" }],
        requested_at: "2026-10-18T10:00:00Z", expires_at: "2026-10-18T10:15:00Z",
        predecessor_total: 2, predecessor_counts: { RUNNING: 2 }, queue_request_state: null,
        outcomes: {}, unknown_targets: 0, settled_targets: 0, verified: false, attention: false, active: true };
      fleetCleanup = { ...fleetCleanup, initialized: true, counts: { active: 1 }, items: [item] };
      const page = await connectPage(debugOrigin, `${origin}/managed-shuns`);
      try {
        await page.until("document.querySelector('#managed-fleet-state').textContent.includes('Waiting for all captured ADDs')");
        assert.equal(await page.evaluate("document.querySelectorAll('#managed-fleet-state script').length"), 0);
        assert.equal(await page.evaluate(`document.querySelector('#fleet-cancel-${key}').open`), false);
        await page.evaluate(`document.querySelector('#fleet-cancel-${key}').open=true`);
        status.queue.revision += 1;
        await wake(page);
        await page.until(`document.querySelector('#fleet-cancel-${key}').open`);
        const cancellations = managedCancelPosts;
        await page.evaluate("document.querySelector('#managed-fleet-state [data-managed-cancel-form] button').click()");
        await page.until("document.querySelector('#managed-fleet-state').textContent.includes('Waiting cleanup cancelled')");
        assert.equal(managedCancelPosts, cancellations + 1);
        assert.equal(await page.evaluate("location.pathname"), "/managed-shuns");
        assert.equal(await page.evaluate("Boolean(document.querySelector('#managed-fleet-state [data-managed-cancel-form]'))"), false);
        assert.equal(await page.evaluate(`document.querySelector('#fleet-cleanup-${key}').open`), false);
        Object.assign(item, { state: "ADMITTED", active: true, queue_request_state: "ACTIVE",
          settled_targets: 1, outcomes: { VERIFIED: 1, QUEUED: 2 }, predecessor_counts: { UNVERIFIED: 1, NOOP: 1 } });
        fleetCleanup.counts = { active: 1 };
        status.queue.revision += 1;
        await wake(page);
        await page.until("document.querySelector('#managed-fleet-state progress')?.value===1");
        assert.equal(await page.evaluate("document.querySelector('#managed-fleet-state progress').max"), 3);
        assert.equal(await page.evaluate("document.querySelector('#managed-fleet-state .cleanup-state').dataset.cleanupState"), "active");
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
          assert.ok(await page.evaluate("document.querySelector('#managed-fleet-state progress').getBoundingClientRect().top-document.querySelector('.fleet-cleanup-progress label').getBoundingClientRect().bottom>=6"));
        }
        Object.assign(item, { active: false, settled_targets: 3, outcomes: { VERIFIED: 2, NOOP: 1 } });
        status.queue.revision += 1;
        await wake(page);
        await page.until("document.querySelector('#managed-fleet-state').textContent.includes('Linked jobs settled — inspect outcomes')");
        assert.equal(await page.evaluate("document.querySelector('#managed-fleet-state .cleanup-state').dataset.cleanupState"), "settled");
        Object.assign(item, { verified: true, outcomes: { VERIFIED: 3 } });
        status.queue.revision += 1;
        await wake(page);
        await page.until("document.querySelector('#managed-fleet-state').textContent.includes('All targets verified removed')");
        assert.equal(await page.evaluate("document.querySelector('#managed-fleet-state .cleanup-state').dataset.cleanupState"), "verified");
        Object.assign(item, { verified: false, outcomes: {}, unknown_targets: 3, settled_targets: 0, attention: true });
        fleetCleanup.counts = { attention: 1 };
        status.queue.revision += 1;
        await wake(page);
        await page.until("document.querySelector('#managed-fleet-state').textContent.includes('Queue history incomplete — outcome unknown')");
        assert.equal(await page.evaluate("document.querySelector('#managed-fleet-state .cleanup-state').dataset.cleanupState"), "attention");
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally {
        fleetCleanup = { ...fleetCleanup, initialized: false, counts: {}, items: [] };
        await page.close();
      }
    });
    await t.test("managed removal review stays frozen, non-executable and usable on mobile", async () => {
      status = initial();
      const hints = postCount;
      const executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/managed-shuns/removal-review`);
      try {
        const original = await page.evaluate("document.querySelector('input[name=review]').value");
        await page.evaluate("document.querySelector('#confirm-managed-ip').value='198.51.100.251'; document.querySelector('#confirm-managed-ip').focus()");
        const reads = pageReads;
        generation += 1;
        status.data_revision += 1;
        status.queue.revision += 1;
        await wake(page);
        await delay(300);
        assert.equal(pageReads, reads, "Frozen POST review must not be fetched/replaced by status updates");
        assert.equal(await page.evaluate("document.querySelector('input[name=review]').value"), original);
        assert.equal(await page.evaluate("document.querySelector('#confirm-managed-ip').value"), "198.51.100.251");
        assert.equal(await page.evaluate("document.activeElement.id"), "confirm-managed-ip");
        assert.equal(await page.evaluate("document.querySelector('.import-confirm-form button').disabled"), true);
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        }
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("fleet review includes missing and disabled targets, remains frozen and cannot execute", async () => {
      status = initial();
      const hints = postCount;
      const executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/managed-shuns/fleet-removal-review`);
      try {
        assert.ok(await page.evaluate("document.body.textContent.includes('3 exact device/IP targets')"));
        assert.ok(await page.evaluate("document.body.textContent.includes('Disabled devices are included')"));
        assert.equal(await page.evaluate("document.querySelectorAll('table[aria-label=\"Frozen fleet removal scope\"] tbody tr').length"), 3);
        const original = await page.evaluate("document.querySelector('input[name=review]').value");
        await page.evaluate("document.querySelector('#confirm-managed-ip').value='198.51.100.251'; document.querySelector('#confirm-managed-ip').focus()");
        const reads = pageReads;
        status.data_revision += 1;
        status.managed_policy_revision = (status.managed_policy_revision || 0) + 1;
        await wake(page);
        await delay(300);
        assert.equal(pageReads, reads);
        assert.equal(await page.evaluate("document.querySelector('input[name=review]').value"), original);
        assert.equal(await page.evaluate("document.querySelector('#confirm-managed-ip').value"), "198.51.100.251");
        assert.equal(await page.evaluate("document.activeElement.id"), "confirm-managed-ip");
        assert.equal(await page.evaluate("document.querySelector('.import-confirm-form button').disabled"), true);
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        }
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("enabled cleanup review freezes device or whole-fleet ordered consent without submitting commands", async () => {
      status = initial();
      status.managed_removal_admission_enabled = true;
      status.managed_removal_worker_enabled = true;
      const hints = postCount;
      const executions = executionCount;
      for (const scope of ["device", "fleet-ready", "fleet-ordered"]) {
        const endpoint = scope === "device" ? "/managed-shuns/removal-review" : `/managed-shuns/fleet-removal-review?enabled=all&ordered=${scope === "fleet-ordered" ? "yes" : "no"}`;
        const page = await connectPage(debugOrigin, `${origin}${endpoint}`);
        try {
          assert.equal(await page.evaluate("document.querySelector('.import-confirm-form button').disabled"), false);
          assert.equal(await page.evaluate("document.querySelector('.import-confirm-form').checkValidity()"), false);
          if (scope !== "device") assert.ok(await page.evaluate(`document.body.textContent.includes('${scope === "fleet-ordered" ? "Ordered mode: wait for all" : "Ready-only mode: a RUNNING ADD conflicts"}')`));
          const key = await page.evaluate("document.querySelector('input[name=review]').value");
          await page.evaluate("document.querySelector('#confirm-managed-ip').value='198.51.100.251'; document.querySelector('#confirm-managed-ip').focus()");
          assert.equal(await page.evaluate("document.querySelector('.import-confirm-form').checkValidity()"), true);
          const reads = pageReads;
          status.data_revision += 1;
          status.queue.revision += 1;
          status.status_revision += 1;
          await wake(page);
          await delay(300);
          assert.equal(pageReads, reads);
          assert.equal(await page.evaluate("document.querySelector('input[name=review]').value"), key);
          assert.equal(await page.evaluate("document.activeElement.id"), "confirm-managed-ip");
          for (const width of [1100, 375]) {
            await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
            assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
            assert.ok(await page.evaluate("document.querySelector('.import-confirm-form button').getBoundingClientRect().top>document.querySelector('#confirm-managed-ip').getBoundingClientRect().bottom"));
          }
        } finally { await page.close(); }
      }
      const page = await connectPage(debugOrigin, `${origin}/managed-shuns`);
      try {
        await page.evaluate("document.querySelector('#managed-fleet-review-preparation').open=true; document.querySelector('[name=ordered_wait]').checked=true; document.querySelector('#fleet-review-ip').value='198.51.100.251'");
        status.data_revision += 1;
        await wake(page);
        await delay(300);
        assert.equal(await page.evaluate("document.querySelector('[name=ordered_wait]').checked"), true);
        assert.equal(await page.evaluate("document.querySelector('#fleet-review-ip').value"), "198.51.100.251");
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("policy-only retirement review is frozen and waiting cancellation updates without navigation or writes", async () => {
      status = initial();
      managed.entries[0].enabled = true;
      const hints = postCount;
      const executions = executionCount;
      const reviewPage = await connectPage(debugOrigin, `${origin}/managed-shuns/retirement-review`);
      try {
        assert.ok(await reviewPage.evaluate("document.body.textContent.includes('No device command')"));
        assert.equal(await reviewPage.evaluate("document.querySelector('.import-confirm-form button').disabled"), false);
        const original = await reviewPage.evaluate("document.querySelector('input[name=review]').value");
        await reviewPage.evaluate("document.querySelector('#confirm-retirement-ip').value='198.51.100.251'; document.querySelector('#confirm-retirement-ip').focus()");
        const reads = pageReads;
        status.managed_policy_revision = 50;
        status.data_revision += 1;
        status.status_revision += 1;
        await wake(reviewPage);
        await delay(300);
        assert.equal(pageReads, reads);
        assert.equal(await reviewPage.evaluate("document.querySelector('input[name=review]').value"), original);
        assert.equal(await reviewPage.evaluate("document.activeElement.id"), "confirm-retirement-ip");
        assert.equal(await reviewPage.evaluate("document.querySelector('#confirm-retirement-ip').value"), "198.51.100.251");
        for (const width of [1100, 375]) {
          await reviewPage.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await reviewPage.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
        }
      } finally { await reviewPage.close(); }
      handoffs.items[0].state = "WAITING_ADD";
      handoffs.items[0].queue_state = null;
      handoffs.counts = { WAITING_ADD: 1 };
      const page = await connectPage(debugOrigin, `${origin}/managed-shuns`);
      try {
        assert.equal(await page.evaluate("document.querySelector('[data-managed-cancel-form]').closest('details').open"), false);
        await page.evaluate("document.querySelector('[data-managed-cancel-form]').closest('details').open=true");
        const cancelBefore = managedCancelPosts;
        await page.evaluate("document.querySelector('[data-managed-cancel-form] button').click()");
        await page.until("document.querySelector('#managed-removal-state').textContent.includes('Cleanup cancelled')");
        assert.equal(managedCancelPosts, cancelBefore + 1);
        assert.equal(await page.evaluate("location.pathname"), "/managed-shuns");
        assert.equal(await page.evaluate("Boolean(document.querySelector('[data-managed-cancel-form]'))"), false);
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("standing grant keeps explicit consent frozen, native validation and mobile layout without hints", async () => {
      status = initial();
      managed.initialized = true;
      status.managed_policy_admission_enabled = true;
      const hints = postCount;
      const executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/managed-shuns/grant-review`);
      try {
        assert.ok(await page.evaluate("document.body.textContent.includes('Persistent policy, not a one-time import')"));
        const key = await page.evaluate("document.querySelector('input[name=review]').value");
        assert.equal(await page.evaluate("document.querySelector('.managed-grant-form').checkValidity()"), false);
        await page.evaluate("document.querySelector('#confirm-grant-ip').value='198.51.100.252'");
        assert.equal(await page.evaluate("document.querySelector('.managed-grant-form').checkValidity()"), false);
        await page.evaluate("document.querySelector('[name=maintain_present]').checked=true; document.querySelector('#confirm-grant-ip').focus()");
        assert.equal(await page.evaluate("document.querySelector('.managed-grant-form').checkValidity()"), true);
        const reads = pageReads;
        status.data_revision += 1;
        status.status_revision += 1;
        status.managed_policy_revision = 99;
        status.managed_policy_admission_enabled = false;
        await wake(page);
        await delay(300);
        assert.equal(pageReads, reads);
        assert.equal(await page.evaluate("document.querySelector('input[name=review]').value"), key);
        assert.equal(await page.evaluate("document.querySelector('#confirm-grant-ip').value"), "198.51.100.252");
        assert.equal(await page.evaluate("document.querySelector('[name=maintain_present]').checked"), true);
        assert.equal(await page.evaluate("document.activeElement.id"), "confirm-grant-ip");
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
          assert.ok(await page.evaluate("document.querySelector('[name=maintain_present]').getBoundingClientRect().width<40"));
          assert.ok(await page.evaluate("document.querySelector('.managed-grant-form button').getBoundingClientRect().top>document.querySelector('#confirm-grant-ip').getBoundingClientRect().bottom"));
        }
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("standing batch freezes 102 pairs, count/consent and responsive paged review without hints", async () => {
      status = initial();
      managed.initialized = true;
      status.managed_policy_admission_enabled = true;
      const hints = postCount;
      const executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/managed-shuns/bulk-review`);
      try {
        assert.equal(await page.evaluate("document.querySelectorAll('[data-standing-target]').length"), 100);
        assert.ok(await page.evaluate("document.body.textContent.includes('102 device/IP pairs')"));
        assert.ok(await page.evaluate("document.body.textContent.includes('Page 1 of 2')"));
        const key = await page.evaluate("document.querySelector('input[name=review]').value");
        assert.equal(await page.evaluate("document.querySelector('#standing-batch-confirm').checkValidity()"), false);
        await page.evaluate("document.querySelector('#confirm-batch-count').value='101'; document.querySelector('[name=maintain_present]').checked=true");
        assert.equal(await page.evaluate("document.querySelector('#standing-batch-confirm').checkValidity()"), false);
        await page.evaluate("document.querySelector('#confirm-batch-count').value='102'; document.querySelector('#confirm-batch-count').focus()");
        assert.equal(await page.evaluate("document.querySelector('#standing-batch-confirm').checkValidity()"), true);
        const reads = pageReads;
        status.data_revision += 1;
        status.status_revision += 1;
        status.managed_policy_admission_enabled = false;
        await wake(page);
        await delay(300);
        assert.equal(pageReads, reads);
        assert.equal(await page.evaluate("document.querySelector('input[name=review]').value"), key);
        assert.equal(await page.evaluate("document.querySelector('#confirm-batch-count').value"), "102");
        assert.equal(await page.evaluate("document.querySelector('[name=maintain_present]').checked"), true);
        assert.equal(await page.evaluate("document.activeElement.id"), "confirm-batch-count");
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
          assert.ok(await page.evaluate("document.querySelector('[name=maintain_present]').getBoundingClientRect().width<40"));
          assert.ok(await page.evaluate("document.querySelector('.managed-grant-form button').getBoundingClientRect().top>document.querySelector('#confirm-batch-count').getBoundingClientRect().bottom"));
        }
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("standing paste draft survives refresh without truncation or hidden execution", async () => {
      status = initial();
      const hints = postCount;
      const executions = executionCount;
      const page = await connectPage(debugOrigin, `${origin}/managed-shuns/bulk`);
      try {
        await page.evaluate("document.querySelector('#blocklist-text').value='198.51.100.10 # Office'; document.querySelector('#blocklist-text').dispatchEvent(new Event('input', {bubbles:true})); document.querySelector('#blocklist-text').focus()");
        const reads = pageReads;
        status.data_revision += 1;
        status.status_revision += 1;
        await wake(page);
        await delay(300);
        assert.equal(pageReads, reads);
        assert.equal(await page.evaluate("document.querySelector('#blocklist-text').value"), "198.51.100.10 # Office");
        assert.equal(await page.evaluate("document.querySelector('#blocklist-text').hasAttribute('maxlength')"), false);
        assert.ok(await page.evaluate("document.querySelector('#paste-size').textContent.includes((1048576).toLocaleString())"));
        assert.equal(postCount, hints);
        assert.equal(executionCount, executions);
      } finally { await page.close(); }
    });
    await t.test("managed import review preserves session fields, consent, escaping and mobile spacing", async () => {
      status.managed_policy_admission_enabled = true;
      const page = await connectPage(debugOrigin, `${origin}/managed-imports/review`, "#prepared-import-confirm");
      try {
        await page.until("document.querySelector('#prepared-import-confirm')");
        const reads = pageReads, hints = postCount, submissions = confirmationPosts;
        const token = await page.evaluate("document.querySelector('[name=review]').value");
        await page.evaluate("document.querySelector('#accepted-pair-count').value='101'; document.querySelector('[name=maintain_present]').checked=true; document.querySelector('#accepted-pair-count').focus()");
        assert.ok(await page.evaluate("document.body.textContent.includes('<b>Escaped import</b>')"));
        assert.equal(await page.evaluate("document.querySelectorAll('td b, dd b').length"), 0);
        assert.equal(await page.evaluate("document.querySelector('#prepared-import-confirm').checkValidity()"), true);
        assert.ok(await page.evaluate("getComputedStyle(document.querySelector('.protected-shun td')).backgroundColor !== 'rgba(0, 0, 0, 0)'"));
        assert.equal(await page.evaluate("document.querySelectorAll('table[aria-label=\"Exact import pairs\"] tbody tr').length"), 100);
        await wake(page); await delay(300);
        assert.equal(pageReads, reads); assert.equal(postCount, hints); assert.equal(confirmationPosts, submissions);
        assert.equal(await page.evaluate("document.querySelector('[name=review]').value"), token);
        assert.equal(await page.evaluate("document.activeElement.id"), "accepted-pair-count");
        assert.equal(await page.evaluate("document.querySelector('[name=maintain_present]').checked"), true);
        for (const width of [1100, 375]) {
          await page.call("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width === 375 });
          assert.equal(await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), true);
          assert.ok(await page.evaluate("(() => {const input=document.querySelector('#accepted-pair-count').getBoundingClientRect();const button=document.querySelector('#prepared-import-confirm > button').getBoundingClientRect();return button.top-input.bottom>=8;})()"));
        }
      } finally { await page.close(); }
    });

    await t.test("import cancellation warns about retained shuns and has no maintenance-consent switch", async () => {
      status.managed_policy_admission_enabled = false;
      const page = await connectPage(debugOrigin, `${origin}/managed-imports/review?kind=cancel`, "#prepared-import-confirm");
      try {
        await page.until("document.querySelector('#prepared-import-confirm')");
        assert.ok(await page.evaluate("document.body.textContent.includes('This does not unblock already added addresses')"));
        assert.ok(await page.evaluate("document.body.textContent.includes('WAITING_OUTCOME: 1')"));
        assert.equal(await page.evaluate("document.querySelector('[name=maintain_present]')"), null);
        assert.equal(await page.evaluate("document.querySelector('#prepared-import-confirm > button').disabled"), false);
        assert.equal(await page.evaluate("document.querySelector('[name=kind]').value"), "cancel");
        assert.equal(await page.evaluate("document.querySelector('#prepared-import-confirm').checkValidity()"), false);
        await page.evaluate("document.querySelector('#accepted-pair-count').value='101'");
        assert.equal(await page.evaluate("document.querySelector('#prepared-import-confirm').checkValidity()"), true);
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
