"""Diagnostic timing has bounded labels and cannot replace operation evidence."""

import asyncio
from types import SimpleNamespace

import pytest

from ftd_shun_manager import parallel_synchronizer, session_timing
from ftd_shun_manager.parallel_synchronizer import _DeviceWorker
from ftd_shun_manager.session_timing import SessionTiming


def test_timing_is_detached_bounded_and_never_logs_function_arguments(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(session_timing, 'monotonic', lambda: clock[0])
    timing = SessionTiming()
    for i in range(100):
        timing.local(SimpleNamespace(__name__=f'sensitive-{i}'), 0.01)
    timing.rpc(3)
    clock[0] += 5
    report = timing.report()
    assert report == {'elapsed_seconds': 5, 'local_seconds': 1, 'local_calls': 100,
                      'agent_seconds': 3, 'agent_calls': 1, 'local_phases_seconds': {'other': 1}}
    report['local_phases_seconds']['other'] = 999
    assert timing.report()['local_phases_seconds']['other'] == 1


@pytest.mark.parametrize('failed', [False, True])
def test_agent_duration_excludes_local_lease_renewal_even_on_failure(monkeypatch, failed):
    clock = [0.0]
    monkeypatch.setattr(session_timing, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(parallel_synchronizer, 'monotonic', lambda: clock[0])

    def renew(*args):
        clock[0] += 2

    def rpc():
        clock[0] += 3
        if failed:
            raise OSError('Synthetic transport failure')
        return 'done'

    worker = object.__new__(_DeviceWorker)
    worker._timing = SessionTiming()
    worker.queue = SimpleNamespace(renew=renew)
    worker.agent = SimpleNamespace(open_cycle=lambda: None)
    worker.device_id, worker.instance_id, worker._lease_seconds = 1, 'private-owner', 100
    worker._rpc_calls, worker._read_session, worker.rpc_failed = 0, None, False
    worker.clock = lambda: clock[0]
    if failed:
        with pytest.raises(OSError, match='transport'):
            asyncio.run(worker._agent_call(rpc))
        assert worker.rpc_failed
    else:
        assert asyncio.run(worker._agent_call(rpc)) == 'done'
    report = worker._timing.report()
    assert report['local_seconds'] == 2 and report['agent_seconds'] == 3
    assert report['elapsed_seconds'] == 5
    assert report['local_calls'] == report['agent_calls'] == 1
    assert report['local_phases_seconds'] == {'renew': 2}
