"""Presentation-only restoration semantics; no API, storage or device access."""

import pytest

from ftd_shun_manager.web import Identity, templates


def entry(**changes):
    return {'device_id': 1, 'hostname': 'Fixture FTD', 'ip': '198.51.100.253',
            'enabled': False, 'device_enabled': True, 'observed_present': False, 'protected': False,
            'generation': 1, 'pending_jobs': 0, 'attention': False, 'missing_unknown_job': False,
            'last_attempt_state': 'VERIFIED', 'last_attempt_generation': 1,
            'last_verified_application_at': '2026-10-30T12:52:19Z',
            'actor_display_name': 'Fixture operator', 'actor_subject': 'fixture',
            'authorized_at': '2026-10-30T12:45:57Z', 'label': 'Fixture only', 'reason': ''} | changes


def render(entries, *, page=1, pages=1, total=None):
    return templates.env.get_template('bulk-managed-shuns.html').render(
        identity=Identity('fixture', 'Fixture operator', ('Operator',)), csrf_token='fixture',
        active_page='managed', auto_request=False,
        refresh={'runtime_mode': 'continuous-managed', 'devices': {}},
        managed={'changed': False, 'initialized': True, 'entries': entries, 'revision': 7,
                 'total': len(entries) if total is None else total, 'limit': 200000,
                 'restoration_suspended': False, 'attempt_ledger_initialized': True,
                 'page': page, 'pages': pages})


def test_quiet_retired_rules_are_collapsed_history_not_current_block_or_removal_policy():
    html = render([entry()])
    assert 'aria-label="Managed policy"' not in html
    assert '<details id="managed-restoration-off-history" class="managed-history">' in html
    assert 'Auto-restore off — history (1 on this page)' in html
    assert 'No auto-restoring rules or active items on this page.' in html
    assert 'not automatic unblocking' in html
    assert 'does not remove an existing block or automatically remove a later block' in html
    assert 'Past verified addition:' in html and 'not mean the address is blocked now' in html
    assert 'Last verified ADD:' not in html and 'Presence alone does not prove' not in html
    assert 'No pending operations.' in html and '198.51.100.253' in html
    assert 'data-auto-restore="off">Auto-restore off' in html


@pytest.mark.parametrize('changes', [
    {'enabled': True}, {'observed_present': True}, {'attention': True},
    {'missing_unknown_job': True}, {'pending_jobs': 1},
    {'last_attempt_state': 'FAILED'}, {'last_attempt_state': 'UNVERIFIED'},
    {'last_attempt_state': 'QUEUED'}, {'last_attempt_state': 'RUNNING'},
    {'last_attempt_state': 'UNKNOWN_FUTURE_STATE'}, {'pending_jobs': False},
    {'observed_present': None}, {'attention': None}, {'missing_unknown_job': None},
])
def test_active_present_held_pending_or_incomplete_rules_are_never_hidden(changes):
    html = render([entry(**changes)])
    assert 'aria-label="Managed policy"' in html
    assert 'id="managed-restoration-off-history"' not in html
    assert 'data-managed-target="1:198.51.100.253"' in html
    if changes.get('last_attempt_state') in ('FAILED', 'UNVERIFIED'):
        assert 'Past addition failed or has an unknown outcome — needs attention' in html
    if changes.get('observed_present') is True:
        assert 'Auto-restore is off, but the block is still observed' in html
    if changes == {'pending_jobs': False}:
        assert 'Operation status unavailable' in html and 'No pending operations.' not in html


@pytest.mark.parametrize('missing', ['enabled', 'observed_present', 'attention',
                                     'missing_unknown_job', 'pending_jobs', 'last_attempt_state'])
def test_missing_status_is_not_treated_as_quiet_history(missing):
    target = entry()
    del target[missing]
    html = render([target])
    assert 'aria-label="Managed policy"' in html
    assert 'id="managed-restoration-off-history"' not in html


def test_page_scope_and_original_pagination_are_honest_with_mixed_history():
    html = render([entry(enabled=True), entry(ip='198.51.100.254',
        label='<img src=x onerror=alert(1)>')], page=2, pages=3, total=201)
    current, history = html.split('<details id="managed-restoration-off-history"', 1)
    assert 'data-managed-target="1:198.51.100.253"' in current
    assert 'data-managed-target="1:198.51.100.254"' not in current
    assert 'data-managed-target="1:198.51.100.254"' in history
    assert '1 on this page' in history and 'Page 2 of 3' in history
    assert 'including collapsed history' in history
    assert 'href="/managed-shuns?page=1&amp;revision=7"' in history
    assert 'href="/managed-shuns?page=3&amp;revision=7"' in history
    assert '&lt;img src=x onerror=alert(1)&gt;' in history and '<img src=x' not in html
