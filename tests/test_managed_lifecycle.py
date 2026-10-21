"""Integrated operator lifecycle on disposable SQLite and a typed fake console.

Use the actual offline CLIs, browser confirmation, private API and shared worker.
Never edit policy/queue tables to shortcut migration, consent, resume or results.
No environment file, SSH, Docker, lab volume or real device is accessed.
"""

import asyncio
import json
import re
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address

import httpx
import pytest

from ftd_shun_manager import (
    maintenance,
    managed_maintenance,
    managed_shuns,
    protected_policy,
    store,
    web,
)
from ftd_shun_manager.agent_client import AgentClient, AgentUnavailable
from ftd_shun_manager.agent_protocol import AdditionResult, ObservedShun
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.operation_queue import OperationQueue, stamp

IP = IPv4Address("198.51.100.252")
ACTOR = {"subject": "synthetic-operator", "display_name": "Synthetic operator", "roles": ["Operator"]}


class Console:
    version = 3

    def __init__(self, agent, device):
        self.agent, self.device = agent, device
        self.initial_snapshot = self.snapshot()

    def snapshot(self):
        return [ObservedShun(ip, "management") for ip in sorted(self.agent.entries[self.device])]

    def add_shun(self, ip):
        created = ip not in self.agent.entries[self.device]
        self.agent.commands.append(("ADD", self.device, ip))
        self.agent.entries[self.device].add(ip)
        if self.device in self.agent.lose_add_reply:
            raise AgentUnavailable("Synthetic reply lost after possible ADD")
        return AdditionResult(created, "management" if created else None)

    def remove_shun(self, ip):
        present = ip in self.agent.entries[self.device]
        self.agent.commands.append(("REMOVE", self.device, ip))
        self.agent.entries[self.device].discard(ip)
        if self.device in self.agent.lose_remove_reply:
            raise AgentUnavailable("Synthetic reply lost after possible REMOVE")
        return present

    def finish(self):
        return self.snapshot()

    def abort(self):
        self.agent.active = None


class DeviceState(AgentClient):
    def __init__(self):
        self.entries = {1: set(), 2: set()}
        self.commands, self.lose_add_reply, self.active = [], set(), None
        self.lose_remove_reply = set()

    def open_cycle(self, device):
        assert self.active is None, "Only one console session may run at a time"
        self.active = device
        return Console(self, device)

    def list_shuns(self, *args):
        pytest.fail("Lifecycle must use the shared cycle, not a separate reader")

    def remove_shun(self, *args):
        pytest.fail("Lifecycle must use the shared cycle, not a separate writer")


class Lifecycle:
    def __init__(self, tmp_path, monkeypatch, capsys):
        self.root, self.capsys = tmp_path, capsys
        self.clock = datetime.now(UTC) + timedelta(seconds=1)
        self.agent, self.calls = DeviceState(), []
        self.backups = tmp_path / "backups"
        self.backups.mkdir(mode=0o700)
        self.backup_count = 0
        self.store = store.Store(tmp_path / "synthetic.db")
        inventory = tmp_path / "synthetic.json"
        inventory.write_text(json.dumps([{"id": device, "hostname": f"synthetic-{device}", "management_ip": f"192.0.2.{device}",
            "ssh_host_key": "ssh-ed25519 AAAA", "allowed_interfaces": ["management"],
            "addition_profile": "fpr1010-766-single-vf-management-v1"} for device in (1, 2)]))
        monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
        monkeypatch.setattr(OperationQueue, "_now", lambda _: self.clock)
        for module in (store, managed_shuns, protected_policy):
            monkeypatch.setattr(module, "now", lambda: stamp(self.clock))
        lifecycle = self
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls.fromtimestamp(lifecycle.clock.timestamp(), tz)
        for module in (maintenance, managed_maintenance):
            monkeypatch.setattr(module, "datetime", Clock)
        self.settings = replace(Settings.from_environment(), database_path=self.store.path, device_inventory_path=inventory,
            agent_mode="socket", development_auth=False, agent_cycles_enabled=True, large_snapshots_enabled=True,
            import_admission_enabled=False, import_execution_enabled=False, managed_restoration_enabled=False,
            managed_removal_worker_enabled=True, managed_removal_admission_enabled=True, managed_policy_admission_enabled=True)
        self.restart(execute=False)
        monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(
            transport=httpx.MockTransport(self.internal), base_url="http://synthetic-api"))
        self.web = web.create_app(self.settings)

    def restart(self, *, execute):
        # ASGITransport does not run lifespan; no background task is running
        # during offline CLI controls. A sweep is explicitly driven below.
        self.api = create_app(replace(self.settings, import_execution_enabled=execute,
                                     managed_restoration_enabled=execute), self.store, self.agent)
        self.sync = self.api.state.synchronizer

    def internal(self, request):
        self.calls.append(request)
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api), base_url="http://synthetic-api") as client:
                response = await client.request(request.method, request.url.path, content=request.content, headers=request.headers)
                return httpx.Response(response.status_code, content=response.content, headers=response.headers)
        return asyncio.run(send())

    async def api_request(self, method, path, **kwargs):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api), base_url="http://synthetic-api") as client:
            return await client.request(method, path, **kwargs)

    def browser(self):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.web), base_url="https://synthetic.test",
                                headers={"Remote-User": ACTOR["subject"], "Remote-Name": ACTOR["display_name"],
                                         "Remote-Groups": "ftd-shun-operators"})

    def cli(self, module, action, *, write=False, frozen=None):
        args = [action, "--database", str(self.store.path), "--actor", "synthetic-maintenance", "--confirm-offline"]
        if write:
            self.backup_count += 1
            args += ["--backup", str(self.backups / f"step-{self.backup_count}.sqlite3"), "--confirm-reviewed"]
        if frozen:
            args += ["--reviewed-at", frozen["reviewed_at"], "--review-digest", frozen["confirmation_digest"]]
        self.capsys.readouterr()
        assert module.main(args) == 0
        return json.loads(self.capsys.readouterr().out.splitlines()[-1])

    def initialize(self):
        assert not managed_shuns.ManagedShuns(self.store).snapshot_if_present()["initialized"]
        self.cli(maintenance, "suspend", write=True)
        review = self.cli(managed_maintenance, "review-initialize")
        assert review["ready"] and not review["targets"]
        self.cli(managed_maintenance, "initialize", write=True, frozen=review)
        self.cli(maintenance, "resume-mutations", write=True)
        self.restart(execute=False)
        assert not self.sync.queue.mutations_suspended()
        assert managed_shuns.ManagedShuns(self.store).snapshot_if_present()["restoration_suspended"]

    async def grant(self, devices=(1,)):
        async with self.browser() as client:
            await client.get("/managed-shuns/bulk")
            csrf = client.cookies.get("ftd_shun_csrf")
            page = await client.post("/managed-shuns/bulk-review", data={"csrf": csrf, "text": f"shun {IP} # Synthetic lifecycle",
                "device_ids": [str(device) for device in devices], "label": "Synthetic lifecycle", "reason": "Explicit recurring consent"})
            assert page.status_code == 200, page.text
            token = re.search(r'name="review" value="([^"]+)"', page.text)[1]
            saved = await client.post("/managed-shuns/bulk-confirm", data={"csrf": csrf, "review": token,
                "confirm_count": str(len(devices)), "maintain_present": "yes"})
            assert saved.status_code == 200 and "Standing batch policy recorded" in saved.text, saved.text
        return next(request for request in reversed(self.calls) if request.url.path.endswith("/maintain-batch"))

    def resume(self):
        self.clock += timedelta(seconds=1)
        review = self.cli(managed_maintenance, "review-resume")
        assert review["ready"], review["blockers"]
        self.cli(managed_maintenance, "resume-policy", write=True, frozen=review)
        self.clock += timedelta(seconds=61)
        self.restart(execute=True)

    def close_window(self):
        self.cli(maintenance, "suspend", write=True)
        self.cli(maintenance, "resume-mutations", write=True)
        self.settings = replace(self.settings, managed_policy_admission_enabled=False,
            managed_removal_admission_enabled=False, managed_removal_worker_enabled=False)
        self.restart(execute=False)
        assert not self.sync.queue.mutations_suspended()
        assert managed_shuns.ManagedShuns(self.store).snapshot_if_present()["restoration_suspended"]

    async def sweep(self, seconds=0):
        self.clock += timedelta(seconds=seconds)
        await self.sync._sweep()
        assert self.agent.active is None

    async def cleanup(self, scope):
        async with self.browser() as client:
            await client.get("/managed-shuns")
            csrf = client.cookies.get("ftd_shun_csrf")
            fields = {"csrf": csrf, "reason": "Finish synthetic lifecycle"}
            fields.update({"target": f"1:{IP}"} if scope == "device" else {"ip": str(IP)})
            page = await client.post("/managed-shuns/removal-review" if scope == "device" else "/managed-shuns/fleet-removal-review", data=fields)
            assert page.status_code == 200, page.text
            token = re.search(r'name="review" value="([^"]+)"', page.text)[1]
            accepted = await client.post("/managed-shuns/removal-confirm", data={"csrf": csrf, "review": token, "confirm_ip": str(IP)})
            assert accepted.status_code == 200, accepted.text

    def entries(self):
        return managed_shuns.ManagedShuns(self.store).snapshot_if_present()["entries"]

    def jobs(self):
        with self.store._connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM operation_jobs ORDER BY rowid")]

    def verify(self):
        with self.store._connection() as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
            assert db.execute("SELECT COUNT(*) FROM manual_import_batches").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM shun_import_origins").fetchone()[0] == 0
            assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='managed_incident_closures'").fetchone()
            rows = db.execute("SELECT actor_subject,actor_roles_json FROM operation_requests WHERE source='trusted_policy'").fetchall()
            assert all(row[0] in {"system:managed-shun-policy", "system:trusted-ip-policy"} and json.loads(row[1]) == [] for row in rows)
        for path in self.backups.iterdir():
            assert path.stat().st_mode & 0o777 == 0o600
            with sqlite3.connect(path) as db:
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.fixture
def lifecycle(tmp_path, monkeypatch, capsys):
    return Lifecycle(tmp_path, monkeypatch, capsys)


@pytest.mark.parametrize("scope,devices", [("device", (1,)), ("fleet", (1, 2))])
def test_migration_browser_consent_restoration_restart_and_final_cleanup(lifecycle, scope, devices):
    lab = lifecycle
    lab.initialize()
    async def scenario():
        original = await lab.grant(devices)
        await lab.sweep(61)
        assert not lab.jobs() and not lab.agent.commands  # Explicit policy resume still required.
        identities = [(row["intent_id"], row["generation"], row["authorization_request_id"]) for row in lab.entries()]
        lab.resume()
        assert [(row["intent_id"], row["generation"], row["authorization_request_id"]) for row in lab.entries()] == identities
        await lab.sweep()
        assert {job["state"] for job in lab.jobs()} == {"QUEUED"} and not lab.agent.commands
        await lab.sweep(59)
        assert not lab.agent.commands
        lab.restart(execute=True)
        await lab.sweep(2)
        assert all(lab.agent.entries[device] == {IP} for device in devices)
        assert len(lab.agent.commands) == len(devices) and all(job["state"] == "VERIFIED" for job in lab.jobs())
        # A fake device loses its shuns, representing disappearance, not proof of reboot.
        for device in devices:
            lab.agent.entries[device].clear()
        await lab.sweep(61)
        assert not any(job["state"] == "QUEUED" for job in lab.jobs())
        await lab.sweep(240)
        assert sum(job["state"] == "QUEUED" for job in lab.jobs()) == len(devices)
        await lab.sweep(61)
        assert len(lab.agent.commands) == 2 * len(devices)
        assert all(lab.agent.entries[device] == {IP} for device in devices)
        await lab.cleanup(scope)
        assert all(not row["enabled"] for row in lab.entries())
        assert all(lab.agent.entries[device] == {IP} for device in devices)  # Admission is not execution.
        await lab.sweep(61)
        assert all(not lab.agent.entries[device] for device in devices)
        assert len(lab.agent.commands) == 3 * len(devices)
        lab.restart(execute=True)
        await lab.sweep(3601)
        assert len(lab.agent.commands) == 3 * len(devices) and not lab.sync._has_pending()
        replay = await lab.api_request("POST", original.url.path, content=original.content, headers=original.headers)
        assert replay.status_code == 200 and replay.json()["replayed"]
        assert all(not row["enabled"] for row in lab.entries())
        assert all(job["state"] == "VERIFIED" for job in lab.jobs())
        events = lab.store.list_events()
        assert any(row["event_type"] == "MANAGED_POLICY_RESUMED" for row in events)
        assert any(row["event_type"] == "SHUN_REMOVED_BY_UI" for row in events)
        lab.close_window()
        await lab.sweep(61)
        assert all(not row["enabled"] for row in lab.entries())
        assert len(lab.agent.commands) == 3 * len(devices) and not lab.sync._has_pending()
    asyncio.run(scenario())
    lab.verify()


def test_protection_permanently_retires_and_release_never_restores_old_policy(lifecycle):
    lab = lifecycle
    lab.initialize()
    async def scenario():
        await lab.grant()
        lab.resume()
        await lab.sweep()
        assert lab.jobs()[0]["state"] == "QUEUED"
        response = await lab.api_request("POST", f"/api/v1/protected-ips/{IP}/add", json={
            "actor": ACTOR, "revision": lab.sync.policy.revision(), "name": "Synthetic office", "enabled": True,
            "managed_revision": managed_shuns.ManagedShuns(lab.store).snapshot()["revision"]})
        assert response.status_code == 200, response.text
        assert lab.jobs()[0]["state"] == "CANCELLED" and not lab.entries()[0]["enabled"]
        lab.restart(execute=True)
        await lab.sweep(361)
        assert not lab.agent.commands and len(lab.jobs()) == 1
        body = {"actor": ACTOR, "revision": lab.sync.policy.revision(), "enabled": False}
        response = await lab.api_request("POST", f"/api/v1/protected-ips/{IP}/edit", json=body)
        assert response.status_code == 200, response.text
        await lab.sweep(61)
        assert not lab.agent.commands and len(lab.jobs()) == 1
        # Only a genuinely new explicit consent may authorize another generation.
        await lab.grant()
        await lab.sweep(61)
        await lab.sweep(61)
        assert lab.agent.commands == [("ADD", 1, IP)]
        # Protection also retires/removes a newly maintained observed shun.
        body.update(managed_revision=managed_shuns.ManagedShuns(lab.store).snapshot()["revision"])
        body.update(revision=lab.sync.policy.revision(), enabled=True)
        assert (await lab.api_request("POST", f"/api/v1/protected-ips/{IP}/edit", json=body)).status_code == 200
        await lab.sweep(61)
        assert lab.agent.commands[-1] == ("REMOVE", 1, IP) and not lab.agent.entries[1]
        await lab.sweep(3601)
        assert not lab.entries()[0]["enabled"] and len(lab.agent.commands) == 2
    asyncio.run(scenario())
    lab.verify()


def test_lost_add_reply_survives_new_observations_restart_and_blocks_resume(lifecycle):
    lab = lifecycle
    lab.initialize()
    async def scenario():
        await lab.grant()
        lab.resume()
        await lab.sweep()
        lab.agent.lose_add_reply.add(1)
        await lab.sweep(61)
        assert lab.agent.entries[1] == {IP} and lab.jobs()[0]["state"] == "UNVERIFIED"
        lab.agent.lose_add_reply.clear()
        lab.restart(execute=True)
        await lab.sweep(361)
        assert lab.jobs()[0]["state"] == "UNVERIFIED"
        lab.agent.entries[1].clear()
        await lab.sweep(3601)
        assert lab.agent.commands == [("ADD", 1, IP)] and len(lab.jobs()) == 1
        assert lab.entries()[0]["restoration_attention"]
    asyncio.run(scenario())
    lab.cli(maintenance, "suspend", write=True)
    report = lab.cli(managed_maintenance, "attention")
    assert report["retained_case_count"] == 1
    lab.cli(maintenance, "resume-mutations", write=True)
    review = lab.cli(managed_maintenance, "review-resume")
    assert not review["ready"] and any("uncertain" in reason for reason in review["blockers"])
    assert lab.jobs()[0]["state"] == "UNVERIFIED"
    lab.verify()


@pytest.mark.parametrize("scope,devices", [("device", (1,)), ("fleet", (1, 2))])
def test_cleanup_lost_reply_never_reenables_policy_or_claims_verified_removal(lifecycle, scope, devices):
    lab = lifecycle
    lab.initialize()
    async def scenario():
        await lab.grant(devices)
        lab.resume()
        await lab.sweep()
        await lab.sweep(61)
        await lab.cleanup(scope)
        lab.agent.lose_remove_reply.add(1)
        await lab.sweep(61)
        assert all(not row["enabled"] for row in lab.entries())
        failed = [job for job in lab.jobs() if job["action"] == "REMOVE" and job["device_id"] == 1]
        assert len(failed) == 1 and failed[0]["state"] == "UNVERIFIED"
        lab.agent.lose_remove_reply.clear()
        lab.restart(execute=True)
        await lab.sweep(3601)
        assert all(not lab.agent.entries[device] for device in devices)
        assert len(lab.agent.commands) == 2 * len(devices) and not lab.sync._has_pending()
        removed = [job for job in lab.jobs() if job["action"] == "REMOVE"]
        assert {job["device_id"]: job["state"] for job in removed} == {
            device: "RECONCILED_ABSENT" if device == 1 else "VERIFIED" for device in devices}
        history = [row for row in lab.store.list_events() if row["device_id"] == 1]
        assert any(row["event_type"] == "SHUN_OPERATION_UNVERIFIED" for row in history)
        assert not any(row["event_type"] == "SHUN_REMOVED_BY_UI" for row in history)
    asyncio.run(scenario())
    lab.verify()


def test_controller_disabled_restart_holds_existing_job_without_renewing_authority(lifecycle):
    lab = lifecycle
    lab.initialize()
    async def scenario():
        await lab.grant()
        lab.resume()
        await lab.sweep()
        queued = lab.jobs()
        with lab.store._connection() as db:
            requests = [tuple(row) for row in db.execute("SELECT id,requested_at,expires_at FROM operation_requests")]
        lab.restart(execute=False)
        await lab.sweep(61)
        assert lab.jobs() == queued and not lab.agent.commands
        with lab.store._connection() as db:
            assert [tuple(row) for row in db.execute("SELECT id,requested_at,expires_at FROM operation_requests")] == requests
        lab.restart(execute=True)
        await lab.sweep(61)
        assert lab.agent.commands == [("ADD", 1, IP)] and lab.jobs()[0]["state"] == "VERIFIED"
        assert lab.jobs()[0]["id"] == queued[0]["id"]
    asyncio.run(scenario())
    lab.verify()
