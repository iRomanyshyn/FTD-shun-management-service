"""Recovery assistance never gives Web host privileges or replays unknown work."""

import asyncio
import json
import subprocess
import sys
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from test_bulk_policy import dump
from test_device_reconciliation import (
    bulk,
    cancellation_controls,
    dispatch,
    held,
    journal,
    leases,
    waits,
)

from ftd_shun_manager import web
from ftd_shun_manager.config import Settings
from ftd_shun_manager.lab_recovery import CONTROL, LabRecovery
from ftd_shun_manager.queue_recovery import report

assert all((bulk, cancellation_controls, dispatch, held, journal, leases, waits))


def test_report_is_bound_readonly_and_never_releases_original_hold(bulk, held):
    store = bulk[0].store
    before = dump(store)
    result = report(store, now=bulk[1][0])
    device = next(row for row in result['devices'] if row['id'] == 1)
    assert device['state'] == 'ATTENTION' and device['epoch'] == held[0].epoch
    assert device['eligible'] and device['unknown'] == 1 and device['claims'] == 2
    assert not device['lab_assistance']  # Multi-device synthetic scope is not the known desk lab.
    assert result['execution_available'] is False and result['host_assistance_required']
    assert dump(store) == before


def test_real_control_rehearses_then_preserves_original_unknown_on_copy(bulk, held, tmp_path):
    store = bulk[0].store
    code = CONTROL.replace('/var/lib/ftd-shun-manager/managed-v2.db', str(store.path))
    params = {'device': 1, 'epoch': held[0].epoch, 'actor': 'synthetic-assistance',
              'extended': False, 'run_id': str(uuid4())}
    original = dump(store)
    receipts = []
    for mode in ('rehearse', 'apply'):
        result = subprocess.run([sys.executable, '-', json.dumps({**params, 'mode': mode})],
                                input=code, text=True, capture_output=True, check=True)
        receipt = json.loads(result.stdout)
        assert receipt['jobs_retried'] == 0 and receipt['original_outcomes_unchanged'] is True
        receipts.append(receipt['operation_id'])
        if mode == 'rehearse':
            assert dump(store) == original
    assert receipts[0] != receipts[1]
    with store._connection() as db:
        assert db.execute('SELECT state FROM operation_jobs WHERE id=?', (held[1]['id'],)).fetchone()[0] == 'UNVERIFIED'


@pytest.fixture
def lab_root(tmp_path):
    (tmp_path / 'deploy').mkdir()
    for path in ('.env', 'deploy/compose.yml', 'deploy/compose.local-lab.yml', 'deploy/compose.managed-lab.yml'):
        (tmp_path / path).touch()
    return tmp_path


@pytest.mark.parametrize('fault', [None, 'inventory', 'epoch', 'image', 'stop', 'timeout', 'exit', 'rehearse', 'apply'])
def test_host_order_and_failure_refusal(lab_root, fault):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        output = ''
        if 'stop' in args and fault in ('stop', 'timeout'):
            if fault == 'timeout':
                raise subprocess.TimeoutExpired(args, 340)
            raise subprocess.CalledProcessError(2, args)
        if 'ps' in args:
            output = 'container-' + args[-1]
        elif '-c' in args:
            output = json.dumps([[1, 'unknown-production-host' if fault == 'inventory' else 'fpr1010-lab']])
        elif 'inspect' in args and args[0] != 'docker':
            pytest.fail('Unexpected command')
        elif 'ftd-shun-device-reconciliation' in args:
            output = json.dumps({'epoch': 10 if fault == 'epoch' else 9})
        elif args[:3] == ['docker', 'image', 'inspect']:
            output = 'sha256:changed' if fault == 'image' else 'sha256:original'
        elif args[:2] == ['docker', 'inspect'] and '.Config.Image' in args[3]:
            output = json.dumps({'id': 'sha256:original', 'ref': 'deploy-api'})
        elif args[:2] == ['docker', 'inspect']:
            output = json.dumps({'Status': 'exited', 'ExitCode': 137 if fault == 'exit' else 0})
        elif 'run' in args:
            assert kwargs['input'] == CONTROL
            mode = json.loads(args[-1])['mode']
            if fault == mode:
                raise subprocess.CalledProcessError(2, args)
            output = json.dumps({'epoch': 9, 'operation_id': str(uuid4()), 'backup': '/private/backup.db',
                                 'jobs_retried': 0, 'original_outcomes_unchanged': True})
        return SimpleNamespace(stdout=output)

    helper = LabRecovery(lab_root, 1, 9, 'real-operator', run=run)
    if fault:
        with pytest.raises((ValueError, subprocess.SubprocessError)):
            helper.recover()
        assert not any('start' in call for call in calls)
        if fault in ('inventory', 'epoch', 'image'):
            assert not any('stop' in call for call in calls)
        if fault in ('exit', 'stop', 'timeout'):
            assert not any('run' in call for call in calls)
    else:
        result = helper.recover()
        assert result['status'] == 'restarted_pending_fresh_read'
        assert result['old_jobs_retried'] == 0
        stops = [call[-2:] for call in calls if 'stop' in call]
        assert stops == [['web', 'api'], ['300', 'agent']]
        assert calls[-2][-2:] == ['start', 'agent'] and calls[-1][-3:] == ['start', 'api', 'web']


def test_bff_requires_identity_and_only_reads_report(tmp_path, monkeypatch):
    requests = []
    value = {'supported': True, 'devices': [{'id': 1, 'hostname': 'fpr1010-lab', 'state': 'ATTENTION',
             'epoch': 42, 'claims': 13, 'unknown': 13, 'extended_v6': False, 'eligible': True, 'lab_assistance': True}]}

    def send(request):
        requests.append(request)
        assert request.method == 'GET' and request.url.path == '/api/v1/queue-recovery'
        return httpx.Response(200, json=value)

    monkeypatch.setattr(web, 'api_client', lambda _: httpx.Client(transport=httpx.MockTransport(send), base_url='http://internal'))
    settings = replace(Settings.from_environment(), database_path=tmp_path / 'absent.db',
                       device_inventory_path=None, development_auth=False)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.create_app(settings)), base_url='https://lab.test') as client:
            assert (await client.get('/queue-recovery')).status_code == 401 and not requests
            client.headers['Remote-User'] = "operator'; echo unwanted"
            response = await client.get('/queue-recovery')
            assert response.status_code == 200 and 'not a one-click browser recovery' in response.text
            assert '--expect-epoch 42' in response.text and 'Host-assisted recovery' in response.text
            result = await client.get('/queue-recovery?download=true')
            assert result.status_code == 200 and 'attachment' in result.headers['content-disposition']
            assert result.json() == value
            assert (await client.post('/queue-recovery')).status_code == 405
        assert not settings.database_path.exists()
    asyncio.run(scenario())
