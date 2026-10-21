"""Session-bound browser adapter for prepared policy, not an executor."""

import json
from dataclasses import dataclass
from uuid import UUID, uuid5

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from .import_review import ReviewUnavailable
from .managed_review import ManagedRemovalReviews

PREFIX = "/api/v1/managed-imports/"
CLASSES = ("PROPOSE_ADD", "PROPOSE_ADOPT", "ALREADY_MANAGED", "EXCLUDED_PROTECTED")


def operation_key(preparation_id):
    return str(uuid5(UUID(preparation_id), "ftd-shun-manager:prepared-policy:v1"))


@dataclass(frozen=True)
class BrowserImportReview:
    token: str
    subject: str
    cookie_hash: str
    request_id: str  # Cache identity only; never used as policy authority.
    expires: float
    expires_at: str
    kind: str
    operation_id: str
    payload_json: str
    summary_json: str

    def payload(self):
        return json.loads(self.payload_json)

    @property
    def summary(self):
        return json.loads(self.summary_json)


def preparation_summary(value):
    counts = value["classification_counts"]
    if (set(counts) != set(CLASSES) or any(type(counts[key]) is not int or counts[key] < 0 for key in CLASSES)
            or type(value["target_count"]) is not int or sum(counts.values()) != value["target_count"]
            or not 1 <= value["target_count"] <= 100000 or value["can_execute"] is not False
            or len(value["digest"]) != 64 or any(c not in "0123456789abcdef" for c in value["digest"])):
        raise ValueError("Invalid frozen preparation summary.")
    return {key: value[key] for key in ("plan_id", "digest", "target_count", "classification_counts", "devices",
        "source_counts", "label", "reason", "managed_revision", "protected_revision", "managed_initialized", "expires_at")}


class BrowserImportReviews(ManagedRemovalReviews):
    def confirmation(self, subject, cookie, report):
        summary = preparation_summary(report)
        count = summary["target_count"] - summary["classification_counts"]["EXCLUDED_PROTECTED"]
        if not 1 <= count <= 1000 or report["state"] != "PREPARED" or summary["managed_initialized"] is not True:
            raise ReviewUnavailable("Only a live, initialized preparation with 1–1000 accepted pairs can be reviewed for confirmation.")
        payload = {"preparation_id": summary["plan_id"], "preparation_digest": summary["digest"],
                   "accepted_count": count, "maintain_present": True}
        return self._save(BrowserImportReview, subject, cookie, kind="confirm", operation_id=operation_key(summary["plan_id"]),
                          payload_json=json.dumps(payload, sort_keys=True), summary_json=json.dumps(summary, sort_keys=True))

    def cancellation(self, subject, cookie, value):
        if (value["can_cancel"] is not True or value["device_work_admitted"] is not False
                or type(value["accepted_count"]) is not int or not 1 <= value["accepted_count"] <= 1000
                or sum(value["counts"].values()) != value["accepted_count"]):
            raise ReviewUnavailable("Cancellation is already requested or its exact scope is unavailable.")
        payload = {key: value[key] for key in ("operation_id", "reviewed_at", "review_digest", "accepted_count")}
        return self._save(BrowserImportReview, subject, cookie, kind="cancel", operation_id=value["operation_id"],
                          payload_json=json.dumps(payload, sort_keys=True), summary_json=json.dumps(value, sort_keys=True))


def validate_receipt(review, value):
    """An HTTP 200 alone is not a policy or cancellation acknowledgment."""
    if (not isinstance(value, dict) or value.get("operation_id") != review.operation_id
            or type(value.get("replayed")) is not bool or value.get("device_work_admitted") is not False):
        raise ValueError("Unconfirmed import outcome.")
    payload = review.payload()
    if review.kind == "confirm":
        counts = review.summary["classification_counts"]
        expected = {"status": "policy_saved", "source": "prepared_managed_import", "policy_only": True,
                    "preparation_id": payload["preparation_id"], "preparation_digest": payload["preparation_digest"],
                    "accepted_pairs": payload["accepted_count"], "proposed_adds": counts["PROPOSE_ADD"],
                    "adopted_pairs": counts["PROPOSE_ADOPT"], "already_managed_pairs": counts["ALREADY_MANAGED"],
                    "excluded_protected_pairs": counts["EXCLUDED_PROTECTED"],
                    "changed_targets": counts["PROPOSE_ADD"] + counts["PROPOSE_ADOPT"],
                    "managed_revision": review.summary["managed_revision"] + 1}
        actor = value.get("confirmation_actor", {})
        if not isinstance(actor, dict) or actor.get("subject") != review.subject:
            raise ValueError("Unconfirmed import author.")
    else:
        expected = {**payload, "status": "cancellation_requested", "can_cancel": False,
                    "device_removal_requested": False, "counts": review.summary["counts"]}
    if any(type(value.get(key)) is not type(expected_value) or value[key] != expected_value
           for key, expected_value in expected.items()):
        raise ValueError("Import response does not match the frozen request.")
    return value


def register_import_web(app, settings, *, render, identity_for, client_for, form_for, csrf_for):
    confirmations = BrowserImportReviews(settings.sensitive_action_max_age_seconds)
    cancellations = BrowserImportReviews(min(300, settings.sensitive_action_max_age_seconds))

    def identity(request):
        actor = identity_for(request, settings.development_auth)
        if not {"Operator", "Administrator"}.intersection(actor.roles):
            raise HTTPException(403, "Operator or Administrator required for managed imports.")
        return actor

    async def fields(request, allowed, *, large=False):
        actor = identity(request)
        values = await form_for(request, allowed={"csrf", *allowed}, **({} if large else {"max_bytes": 4096}))
        csrf_for(request, values.get("csrf", [""])[0])
        return actor, values

    def post(client, suffix, actor, **payload):
        body = actor.__dict__ if suffix in {"preparations", "receipts"} else {"actor": actor.__dict__, **payload}
        response = client.post(PREFIX + suffix, json=body)
        if response.status_code != 200:
            detail = response.json().get("detail")
            raise HTTPException(response.status_code, detail if isinstance(detail, str) else "Import state is unavailable.")
        value = response.json()
        if not isinstance(value, dict):
            raise TypeError("Invalid import state response.")
        return value

    def view(request, actor, template, **context):
        code = context.pop("code", 200)
        return render(request, template, {"identity": actor, "active_page": "imports", "frozen_view": True,
            "auto_request": False, "review": None, "message": None, "result": None, "confirm_count": "",
            "acknowledged": False, **context}, status_code=code)

    def safe_read(fn):
        try:
            return fn()
        except ReviewUnavailable as error:
            raise HTTPException(409, str(error)) from error
        except HTTPException:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as error:
            raise HTTPException(503, "Import state is unavailable. Inspect saved preparations/receipts before retrying; no new action was confirmed.") from error

    def home(request, actor, *, message=None, code=200):
        with client_for(settings) as client:
            drafts = post(client, "preparations", actor)
            receipts = post(client, "receipts", actor)
            devices = client.get("/api/v1/import-devices")
            devices.raise_for_status()
        return view(request, actor, "managed-imports.html", drafts=drafts, receipts=receipts, devices=devices.json(), message=message, code=code)

    @app.get("/managed-imports", response_class=HTMLResponse)
    def managed_imports(request: Request):
        actor = identity(request)
        return safe_read(lambda: home(request, actor))

    def show_review(request, actor, review, *, page=1, message=None, result=None, code=200, confirm_count="", acknowledged=False):
        with client_for(settings) as client:
            if review.kind == "confirm":
                report = post(client, "preparation", actor, preparation_id=review.payload()["preparation_id"], page=page)
                if preparation_summary(report) != review.summary:
                    raise ValueError("Frozen preparation changed.")
            else:
                report = post(client, "receipt", actor, operation_id=review.operation_id, page=page)
            status = client.get("/api/v1/status")
            status.raise_for_status()
            enabled = settings.managed_policy_admission_enabled and status.json().get("managed_policy_admission_enabled") is True
        return view(request, actor, "managed-import-review.html", review=review, report=report, admission_enabled=enabled,
                    message=message, result=result, code=code, confirm_count=confirm_count, acknowledged=acknowledged)

    @app.post("/managed-imports/prepare", response_class=HTMLResponse)
    async def prepare(request: Request):
        actor, values = await fields(request, {"text", "device_ids", "label", "reason"}, large=True)

        def create():
            selected = values.get("device_ids", [])
            if (not 1 <= len(selected) <= 10 or len(set(selected)) != len(selected)
                    or any(not value.isascii() or not value.isdecimal() or len(value) > 5
                           or not 1 <= int(value) <= 65535 or str(int(value)) != value for value in selected)):
                raise HTTPException(422, "Select 1–10 distinct configured devices.")
            with client_for(settings) as client:
                try:
                    created = post(client, "prepare", actor, text=values.get("text", [""])[0], device_ids=[int(value) for value in selected],
                                   label=values.get("label", [""])[0], reason=values.get("reason", [""])[0])
                except httpx.HTTPError:
                    return home(request, actor, message="Preparation reply was lost. Inspect saved preparations before pasting again; no policy confirmation was sent.", code=503)
                report = post(client, "preparation", actor, preparation_id=created["plan_id"])
            return view(request, actor, "managed-import-report.html", report=report, mode="preparation")

        return await run_in_threadpool(safe_read, create)

    @app.post("/managed-imports/preparation", response_class=HTMLResponse)
    async def preparation(request: Request):
        actor, values = await fields(request, {"preparation_id", "page"})
        return await run_in_threadpool(safe_read, lambda: read_report(request, actor, values, "preparation"))

    @app.post("/managed-imports/report", response_class=HTMLResponse)
    async def receipt(request: Request):
        actor, values = await fields(request, {"operation_id", "page"})
        return await run_in_threadpool(safe_read, lambda: read_report(request, actor, values, "receipt"))

    def read_report(request, actor, values, mode):
        key = "preparation_id" if mode == "preparation" else "operation_id"
        with client_for(settings) as client:
            report = post(client, mode, actor, **{key: values.get(key, [""])[0]}, page=page_number(values))
        return view(request, actor, "managed-import-report.html", report=report, mode=mode)

    def page_number(values):
        raw = values.get("page", ["1"])[0]
        if not raw.isascii() or not raw.isdecimal() or len(raw) > 4 or str(int(raw)) != raw or not 1 <= int(raw) <= 1000:
            raise HTTPException(422, "Select a report page between 1 and 1000.")
        return int(raw)

    @app.post("/managed-imports/review", response_class=HTMLResponse)
    async def review_preparation(request: Request):
        actor, values = await fields(request, {"preparation_id"})

        def prepare_review():
            with client_for(settings) as client:
                report = post(client, "preparation", actor, preparation_id=values.get("preparation_id", [""])[0])
            review = confirmations.confirmation(actor.subject, request.cookies.get("ftd_shun_csrf", ""), report)
            return show_review(request, actor, review)

        return await run_in_threadpool(safe_read, prepare_review)

    @app.post("/managed-imports/cancellation-review", response_class=HTMLResponse)
    async def review_cancellation(request: Request):
        actor, values = await fields(request, {"operation_id"})

        def prepare_review():
            with client_for(settings) as client:
                value = post(client, "cancellation-review", actor, operation_id=values.get("operation_id", [""])[0])
            if value.get("already_requested") is True:
                return cancellation_status(request, actor, values)
            review = cancellations.cancellation(actor.subject, request.cookies.get("ftd_shun_csrf", ""), value)
            return show_review(request, actor, review)

        return await run_in_threadpool(safe_read, prepare_review)

    async def frozen_fields(request, *, paginate=False):
        actor, values = await fields(request, {"review", "kind", "confirm_count", "maintain_present"} | ({"page"} if paginate else set()))
        kind = values.get("kind", [""])[0]
        if kind not in {"confirm", "cancel"}:
            raise HTTPException(422, "Select a fixed import review kind.")
        cache = confirmations if kind == "confirm" else cancellations
        try:
            review = cache.get(values.get("review", [""])[0], actor.subject, request.cookies.get("ftd_shun_csrf", ""))
        except ReviewUnavailable as error:
            raise HTTPException(409, str(error)) from error
        return actor, review, values, cache

    @app.post("/managed-imports/review-page", response_class=HTMLResponse)
    async def review_page(request: Request):
        actor, review, values, _ = await frozen_fields(request, paginate=True)
        return await run_in_threadpool(safe_read, lambda: show_review(request, actor, review, page=page_number(values),
            confirm_count=values.get("confirm_count", [""])[0], acknowledged=values.get("maintain_present", [""])[0] == "yes"))

    @app.post("/managed-imports/submit", response_class=HTMLResponse)
    async def submit(request: Request):
        actor, review, values, cache = await frozen_fields(request)
        count = values.get("confirm_count", [""])[0]
        acknowledged = values.get("maintain_present", [""])[0] == "yes"
        if count != str(review.payload()["accepted_count"]) or (review.kind == "confirm" and not acknowledged):
            raise HTTPException(422, "Type the exact accepted pair count and acknowledge recurring maintenance when saving policy.")
        return await run_in_threadpool(save, request, actor, review, cache, count, acknowledged)

    def save(request, actor, review, cache, count, acknowledged):
        result, message, code = None, None, 200
        try:
            with client_for(settings) as client:
                if review.kind == "confirm":
                    status = client.get("/api/v1/status")
                    if (not settings.managed_policy_admission_enabled or status.status_code != 200
                            or status.json().get("managed_policy_admission_enabled") is not True):
                        raise HTTPException(503, "Standing admission is disabled or unavailable. This attempt was not submitted; inspect any earlier receipt.")
                cache.get(review.token, actor.subject, request.cookies.get("ftd_shun_csrf", ""))  # Recheck after status I/O.
                response = client.post(PREFIX + ("confirm" if review.kind == "confirm" else "cancel-confirmed"),
                    json={"actor": actor.__dict__, **review.payload()}, headers={"Idempotency-Key": review.operation_id})
                if response.status_code in {403, 409, 422}:
                    detail = response.json().get("detail")
                    raise HTTPException(response.status_code, detail if isinstance(detail, str) else "Request rejected; inspect current import state.")
                response.raise_for_status()
                result = validate_receipt(review, response.json())
        except HTTPException as error:
            message, code = error.detail, error.status_code
        except ReviewUnavailable as error:
            message, code = str(error), 409
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            message, code = "Outcome is unconfirmed. Inspect the saved receipt/status, then explicitly retry this same review. Do not start another import.", 503
        # Even if the follow-up read fails, retain the original token and fields.
        try:
            return show_review(request, actor, review, message=message, result=result, code=code,
                               confirm_count=count, acknowledged=acknowledged)
        except (HTTPException, httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            return view(request, actor, "managed-import-review.html", review=review, report=None,
                admission_enabled=False, result=result, confirm_count=count, acknowledged=acknowledged, code=503,
                message=message or "Follow-up report is unavailable. Original review/key retained; inspect saved receipt/status before retrying.")

    @app.post("/managed-imports/cancel-preparation", response_class=HTMLResponse)
    async def cancel_preparation(request: Request):
        actor, values = await fields(request, {"preparation_id"})

        def cancel():
            with client_for(settings) as client:
                post(client, "cancel-preparation", actor, preparation_id=values.get("preparation_id", [""])[0])
            return home(request, actor, message="Unconfirmed preparation cancelled. No device command or policy removal was requested.")

        return await run_in_threadpool(safe_read, cancel)

    def cancellation_status(request, actor, values):
        with client_for(settings) as client:
            status = post(client, "cancellation", actor, operation_id=values.get("operation_id", [""])[0], page=page_number(values))
        return view(request, actor, "managed-import-cancellation.html", status=status)

    @app.post("/managed-imports/cancellation", response_class=HTMLResponse)
    async def cancellation(request: Request):
        actor, values = await fields(request, {"operation_id", "page"})
        return await run_in_threadpool(safe_read, lambda: cancellation_status(request, actor, values))
