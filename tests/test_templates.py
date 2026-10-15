from ftd_shun_manager.web import Identity, templates


def test_active_shun_with_trusted_ip_is_visibly_marked() -> None:
    html = templates.get_template("index.html").render(
        identity=Identity("viewer", "Viewer", ("Viewer",)),
        csrf_token="token",
        shuns=[
            {
                "ip": "198.51.100.10",
                "device_hostname": "ftd-01",
                "interface": "outside",
                "first_seen_at": "2026-10-14T10:00:00Z",
                "last_seen_at": "2026-10-14T10:00:00Z",
                "device_id": 1,
            }
        ],
        refresh=None,
        trusted_policy_ips=frozenset({"198.51.100.10"}),
        search_query="",
        search_results=None,
        recent_events=[],
    )

    assert 'class="protected-shun"' in html
    assert "Protected IP" in html
    assert 'class="local-timestamp" datetime="2026-10-14T10:00:00Z"' in html


def test_search_results_distinguish_historical_protected_records() -> None:
    html = templates.get_template("index.html").render(
        identity=Identity("viewer", "Viewer", ("Viewer",)),
        csrf_token="token",
        shuns=[],
        refresh=None,
        trusted_policy_ips=frozenset(),
        search_query="198.51.100",
        search_results=[
            {
                "ip": "198.51.100.10",
                "active": False,
                "protected": True,
                "last_seen_at": "2026-10-14T10:00:00Z",
                "last_removed_at": "2026-10-14T10:01:00Z",
                "last_event_at": "2026-10-14T10:01:00Z",
                "device_count": 1,
            }
        ],
        recent_events=[],
    )

    assert "Historical — not currently shunned" in html
    assert "Protected IP" in html
    assert 'datetime="2026-10-14T10:01:00Z"' in html
