import asyncio
import json
from dataclasses import replace
from ipaddress import IPv4Address
from urllib.parse import urlencode

import httpx
import pytest

from ftd_shun_manager import web
from ftd_shun_manager.api import create_app
from ftd_shun_manager.config import Settings
from ftd_shun_manager.import_preview import (
    MAX_FORM_BYTES,
    MAX_LINES,
    MAX_ROWS,
    MAX_TEXT_BYTES,
    classify_targets,
    paginate_preview,
    parse_blocklist,
    summarize_preview,
)
from ftd_shun_manager.protected_policy import ProtectedPolicy
from ftd_shun_manager.store import Device, Store


@pytest.mark.parametrize("source", ["198.51.100.10", "Denied source 198.51.100.10 today",
    "src=198.51.100.10", "(198.51.100.10)", "[198.51.100.10]", '"198.51.100.10"',
    "2026-10-15T10:20:30.123Z source: 198.51.100.10", "10:20:30.123 src=198.51.100.10"])
def test_parser_accepts_single_exact_ip_and_unambiguous_context(source):
    parsed = parse_blocklist(source)
    assert parsed["ips"] == ["198.51.100.10"]
    assert parsed["rows"][0]["status"] == "Ready"


def test_lists_comments_duplicate_sources_and_context_are_retained():
    parsed = parse_blocklist("# ignore 192.0.2.8\n // ignore 192.0.2.9\n\n198.51.100.10,203.0.113.20 # office\n198.51.100.10;192.0.2.30\n")
    assert parsed["ips"] == ["198.51.100.10", "203.0.113.20", "192.0.2.30"]
    assert parsed["ignored_lines"] == 3
    assert [r["status"] for r in parsed["rows"]] == ["Ready", "Ready", "Duplicate", "Ready"]
    assert parsed["rows"][0]["source_lines"] == [4, 5]
    assert parsed["rows"][1]["source_lines"] == [4], "A sibling token must not share a mutable source-lines list"
    assert parsed["rows"][0]["comment"] == "office"
    assert "192.0.2.8" not in parsed["ips"]
    assert parse_blocklist("198.51.100.10 # never include 192.0.2.99")["ips"] == ["198.51.100.10"]


@pytest.mark.parametrize("source", ["198.51.100.0/24", "198.51.100.10 / 24",
    "198.51.100.10-198.51.100.20", "198.51.100.10 - 20", "198.51.100.10–198.51.100.20",
    "198.51.100.10:443", "198.51.100.10 : 443", "https://198.51.100.10/path",
    "198.51.100.10/path", "2001:db8::1", "::ffff:198.51.100.10", "[::ffff:198.51.100.10]:22"])
def test_unsupported_tokens_never_produce_a_truncated_ipv4(source):
    parsed = parse_blocklist(source)
    assert parsed["ips"] == []
    assert parsed["rows"][0]["status"] == "Unsupported"


@pytest.mark.parametrize("source", ["999.51.100.10", "198.51.100.10.2", "198.51.100.10.",
    "prefix198.51.100.10suffix", "198.051.100.10", "198.51.100", "not an IP"])
def test_invalid_tokens_never_produce_a_substring_candidate(source):
    parsed = parse_blocklist(source)
    assert parsed["ips"] == [] and parsed["rows"][0]["status"] == "Invalid"


@pytest.mark.parametrize("source", ["src 198.51.100.10 dst 203.0.113.20",
    "src=198.51.100.10,dst=203.0.113.20", "198.51.100.10 #comment\nFrom 203.0.113.20 to 192.0.2.1"])
def test_free_text_with_multiple_candidates_is_ambiguous(source):
    parsed = parse_blocklist(source)
    assert parsed["rows"][-1]["status"] == "Ambiguous"
    assert "203.0.113.20" not in parsed["ips"]


def test_parser_limits_and_bounded_excerpt_comments():
    for text in ["x" * (MAX_TEXT_BYTES + 1), "ї" * (MAX_TEXT_BYTES // 2 + 1),
                 "\n" * (MAX_LINES + 1), "198.51.100.10 " * (MAX_ROWS + 1)]:
        with pytest.raises(ValueError):
            parse_blocklist(text)
    row = parse_blocklist("198.51.100.10 # " + "x" * 500)["rows"][0]
    assert len(row["comment"]) == len(row["excerpt"]) == 200
    assert parse_blocklist("# comment\n// comment\n")["rows"] == []


def test_maximum_length_hostile_tokens_do_not_extract_substrings():
    for text in ["9" * MAX_TEXT_BYTES, "9" * (MAX_TEXT_BYTES - 1) + ".",
                 "(" * (MAX_TEXT_BYTES // 2 - 8) + "1.2.3.4" + ")" * (MAX_TEXT_BYTES // 2 - 8)]:
        parsed = parse_blocklist(text)
        assert parsed["ips"] == [] and len(parsed["rows"]) == 1


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.delenv("FTD_SHUN_TRUSTED_AUTO_REMOVE_IPS", raising=False)
    store = Store(tmp_path / "state.db")
    store.initialize()
    for identity in [1, 2, 3]:
        store.upsert_device(Device(identity, f"lab-{identity}", IPv4Address(f"192.0.2.{identity}"), identity != 3), "ssh-ed25519 AAAA")
    policy = ProtectedPolicy(store)
    policy.change("add", IPv4Address("198.51.100.10"), 0, "fixture", "Fixture", ())
    store.record_observed_shun(1, IPv4Address("203.0.113.20"), "outside")
    config = replace(Settings.from_environment(), database_path=store.path, device_inventory_path=None,
                     agent_mode="disabled", development_auth=False)
    return store, policy, config


def test_classification_uses_enabled_devices_protection_and_actual_pair_count(fixture):
    store, policy, _ = fixture
    parsed = parse_blocklist("198.51.100.10\n203.0.113.20\n192.0.2.30\n192.0.2.30")
    snapshot = classify_targets(store, [IPv4Address(ip) for ip in parsed["ips"]], [1, 2])
    result = summarize_preview(parsed, snapshot)
    assert snapshot["can_execute"] is False and snapshot["preview_only"] is True
    assert result["counts"] == {"Protected": 1, "Ready": 2, "Duplicate": 1}
    assert result["candidate_pairs"] == 3  # one absent device for .20, two for .30
    assert result["policy_revision"] == policy.revision()
    already = summarize_preview(parse_blocklist("203.0.113.20"), classify_targets(store, [IPv4Address("203.0.113.20")], [1]))
    assert already["counts"] == {"Already shunned": 1} and already["candidate_pairs"] == 0
    assert policy.queue.status()["counts"] == {}


def test_preview_validation_limits_and_no_stale_policy_cache(fixture):
    store, policy, _ = fixture
    ip = IPv4Address("198.51.100.10")
    for ids in [[], [1, 1], [3], [999], list(range(1, 66))]:
        with pytest.raises(ValueError):
            classify_targets(store, [ip], ids)
    with pytest.raises(ValueError):
        classify_targets(store, [ip, ip], [1])
    many = [IPv4Address(0xC0000200 + index) for index in range(MAX_ROWS)]
    with pytest.raises(ValueError, match="100,000"):
        classify_targets(store, many, list(range(1, 12)))
    with pytest.raises(ValueError, match="10,000"):
        classify_targets(store, [*many, IPv4Address("198.51.100.99")], [1])
    policy.change("edit", ip, policy.revision(), "fixture", "Fixture", (), enabled=False)
    assert classify_targets(store, [ip], [1])["addresses"][0]["protected"] is False


def test_api_preview_reads_only_typed_local_state_without_agent_or_queue(fixture):
    store, _, config = fixture
    app = create_app(config, store)
    before = store.list_events()

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
            devices = (await client.get("/api/v1/import-devices")).json()
            assert set(devices[0]) == {"id", "hostname", "enabled"}
            for payload in [{"ips": ["198.51.100.10/24"], "device_ids": [1]}, {"ips": [], "device_ids": []},
                            {"ips": ["198.51.100.10"], "device_ids": [3]}, {"ips": ["shun 198.51.100.10"], "device_ids": [1]}]:
                assert (await client.post("/api/v1/import-preview", json=payload)).status_code == 422
            response = await client.post("/api/v1/import-preview", json={"ips": ["198.51.100.10"], "device_ids": [1]})
            assert response.status_code == 200 and response.json()["can_execute"] is False
            assert response.json()["addresses"][0]["protected"] is True
            assert response.headers["cache-control"] == "no-store"
            assert (await client.post("/api/v1/imports/queue", json={})).status_code == 404
            assert store.list_events() == before
            assert app.state.synchronizer.queue.status()["counts"] == {}
    asyncio.run(scenario())


def test_bff_preview_auth_csrf_escaping_raw_text_is_not_forwarded(fixture, monkeypatch):
    store, _, config = fixture
    api = create_app(config, store)
    status = next(route for route in api.routes if route.path == "/api/v1/status")
    captured = []

    def internal(request):
        captured.append(request)
        if request.url.path == "/api/v1/status":
            return httpx.Response(200, json=asyncio.run(status.endpoint()))
        if request.url.path == "/api/v1/import-devices":
            return httpx.Response(200, json=[{"id": d.id, "hostname": d.hostname, "enabled": d.enabled} for d in store.list_devices()])
        assert request.url.path == "/api/v1/import-preview"
        payload = json.loads(request.content)
        try:
            return httpx.Response(200, json=classify_targets(store, [IPv4Address(ip) for ip in payload["ips"]], payload["device_ids"]))
        except ValueError as error:
            return httpx.Response(422, json={"detail": str(error)})

    monkeypatch.setattr(web, "api_client", lambda _: httpx.Client(transport=httpx.MockTransport(internal), base_url="http://internal"))

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.create_app(config)), base_url="https://lab.test") as client:
            assert (await client.get("/imports")).status_code == 401
            assert (await client.post("/imports", data={"text": "198.51.100.10"})).status_code == 401
            assert not captured
            client.headers["Remote-User"] = "unmapped-user"
            page = await client.get("/imports")
            assert page.status_code == 200 and 'data-auto-request="false"' in page.text
            token = client.cookies.get("ftd_shun_csrf")
            source = '198.51.100.10 # </textarea><script>alert(1)</script>\n203.0.113.20'
            data = {"csrf": token, "text": source, "device_ids": "1", "label": "<b>Batch</b>"}
            for csrf in ["", "invalid", "поганий"]:
                assert (await client.post("/imports", data={**data, "csrf": csrf})).status_code == 403
            captured.clear()
            response = await client.post("/imports", data=data)
            assert response.status_code == 200 and "Protected: 1" in response.text and "Already shunned: 1" in response.text
            assert "&lt;script&gt;" in response.text and "<script>alert(1)</script>" not in response.text
            assert "Preview only" in response.text and "Creation interface scope: not yet validated" in response.text
            assert response.headers["cache-control"] == "no-store"
            forwarded = json.loads(next(r for r in captured if r.method == "POST").content)
            assert forwarded == {"ips": ["198.51.100.10", "203.0.113.20"], "device_ids": [1]}
            assert not any("refresh-hint" in r.url.path for r in captured)
            no_devices = await client.post("/imports", data={"csrf": token, "text": "192.0.2.10"})
            assert no_devices.status_code == 422 and "Nothing was queued" in no_devices.text
            assert 'maxlength="65536"' not in page.text
            for oversized in ["x" * (MAX_TEXT_BYTES + 1), "ї" * (MAX_TEXT_BYTES // 2 + 1)]:
                captured.clear()
                rejected = await client.post("/imports", data={**data, "text": oversized})
                assert rejected.status_code == 413 and "text/html" in rejected.headers["content-type"]
                assert "Paste at most 1 MiB" in rejected.text and oversized in rejected.text
                assert not any(r.method == "POST" for r in captured), "Oversize text must not be classified or queued"
            for invalid_page in ["0", "101", "9999", "invalid", "１"]:
                rejected = await client.post("/imports", data={**data, "page": invalid_page})
                assert rejected.status_code == 422 and "Select a preview page" in rejected.text
            long_source = "\r\n".join(f"shun {IPv4Address(0xC6120000 + index)}" for index in range(7307))
            for selected_page, row_count in [("1", 100), ("2", 100), ("74", 7), ("100", 7)]:
                response = await client.post("/imports", data={**data, "text": long_source, "page": selected_page})
                assert response.status_code == 200
                assert "7307 rows · 7307 unique IPv4 addresses" in response.text
                assert "7307 candidate device/IP pairs" in response.text
                assert response.text.count("data-preview-state=") == row_count
                assert "shun 198.18.28.138" in response.text, "The final source line must survive every form render"
                assert f"Page {min(int(selected_page), 74)} of 74" in response.text
            assert api.state.synchronizer.queue.status()["counts"] == {}
    asyncio.run(scenario())


def test_preview_body_limits_include_chunked_encoding_and_repeated_fields(fixture, monkeypatch):
    _, _, config = fixture
    monkeypatch.setattr(web, "api_client", lambda _: pytest.fail("Rejected bodies must not reach the API"))

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.create_app(config)), base_url="https://lab.test", headers={"Remote-User": "user"}) as client:
            client.cookies.set("ftd_shun_csrf", "token")
            for body, expected in [("x" * (MAX_FORM_BYTES + 1), 413),
                                   ("csrf=token&csrf=token&text=198.51.100.10", 422), ("csrf=token&subject=forged", 422)]:
                assert (await client.post("/imports", content=body, headers={"Content-Type": "application/x-www-form-urlencoded"})).status_code == expected
            assert (await client.post("/imports", json={"text": "198.51.100.10"})).status_code == 415

            async def oversized():
                for _ in range(5):
                    yield b"x" * (MAX_FORM_BYTES // 4)
            assert (await client.post("/imports", content=oversized(), headers={"Content-Type": "application/x-www-form-urlencoded"})).status_code == 413
    asyncio.run(scenario())


def test_maximum_batch_is_classified_whole_and_paginated_without_loss(fixture):
    store, policy, _ = fixture
    source = "\n".join(f"shun {IPv4Address(0xC6120000 + index)}" for index in range(MAX_ROWS))
    before = store.list_events()
    parsed = parse_blocklist(source)
    classified = classify_targets(store, [IPv4Address(ip) for ip in parsed["ips"]], [1, 2])
    result = summarize_preview(parsed, classified)
    assert result["candidate_pairs"] == 2 * MAX_ROWS and result["counts"] == {"Ready": MAX_ROWS}
    pages = [paginate_preview(result, index) for index in range(1, 101)]
    assert all(len(page["page_rows"]) == 100 for page in pages)
    assert [row["ip"] for page in pages for row in page["page_rows"]] == parsed["ips"]
    assert pages[-1]["first_row"] == 9901 and pages[-1]["last_row"] == MAX_ROWS
    assert store.list_events() == before and policy.queue.status()["counts"] == {}


def test_largest_utf8_form_encoding_with_metadata_fits_request_cap():
    source = "ї" * (MAX_TEXT_BYTES // 2)
    body = urlencode({"csrf": "x" * 43, "text": source, "label": "ї" * 100, "reason": "ї" * 500})
    assert len(body.encode("ascii")) <= MAX_FORM_BYTES
    assert parse_blocklist(source)["rows"][0]["status"] == "Invalid"
