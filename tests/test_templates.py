import pytest

from ftd_shun_manager.web import Identity, templates


@pytest.mark.parametrize("current_appearance", [None, "2026-10-16T11:00:00Z"])
def test_active_shun_with_trusted_ip_is_visibly_marked(current_appearance) -> None:
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
                **({"active_since_at": current_appearance} if current_appearance else {}),
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
    assert "Observed since" in html
    observed_since = current_appearance or "2026-10-14T10:00:00Z"
    assert f'<td><time class="local-timestamp" datetime="{observed_since}">{observed_since}</time></td>' in html


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


@pytest.mark.parametrize("state", ["Ready", "Invalid", "Unsupported", "Ambiguous", "Protected", "Already shunned", "Duplicate"])
def test_preview_status_badges_keep_text_labels_in_rows_and_full_list_counts(state):
    row = {"ip": "198.51.100.10", "status": state, "protected": state == "Protected",
           "source_lines": [1], "devices": [], "reason": "Fixture only", "excerpt": "198.51.100.10"}
    preview = {"rows": [row], "page_rows": [row], "ips": [row["ip"]], "ignored_lines": 0,
               "counts": {state: 1}, "candidate_pairs": 0, "policy_revision": 1,
               "devices": [], "page": 1, "pages": 1, "first_row": 1, "last_row": 1}
    html = templates.get_template("import-preview.html").render(
        identity=Identity("viewer", "Viewer", ("Viewer",)), csrf_token="token",
        refresh={"devices": {}}, preview=preview, devices=[], selected_devices=[], source_text="",
    )
    assert f'<span class="preview-state-badge" data-preview-status="{state}">{state}: 1</span>' in html
    assert f'<strong class="preview-state-badge" data-preview-status="{state}">{state}</strong>' in html
    assert f'data-preview-state="{state}"' in html
    assert "Preview only — device additions are unavailable." in html
