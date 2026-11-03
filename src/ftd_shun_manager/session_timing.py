"""Bounded diagnostic wall times, never execution or success evidence."""

from time import monotonic


class SessionTiming:
    # Fixed labels only: do not log arguments, IP lists, actors or CLI output.
    LOCAL_PHASES = frozenset({'renew', 'claim_next_mutation', 'claim_addition', 'claim_removal',
                             'finish_addition', 'finish_removal', '_publish_snapshot',
                             '_discover_snapshot', 'cancel_obsolete_policy'})

    def __init__(self):
        self.started = monotonic()
        self.local_seconds = 0.0
        self.local_calls = 0
        self.rpc_seconds = 0.0
        self.rpc_calls = 0
        self.phases = {}

    def local(self, function, seconds):
        name = getattr(function, '__name__', '')
        phase = name if name in self.LOCAL_PHASES else 'other'
        self.phases[phase] = self.phases.get(phase, 0.0) + seconds
        self.local_seconds += seconds
        self.local_calls += 1

    def rpc(self, seconds):
        self.rpc_seconds += max(0.0, seconds)
        self.rpc_calls += 1

    def report(self):
        return {'elapsed_seconds': round(monotonic() - self.started, 3),
                'local_seconds': round(self.local_seconds, 3), 'local_calls': self.local_calls,
                'agent_seconds': round(self.rpc_seconds, 3), 'agent_calls': self.rpc_calls,
                'local_phases_seconds': {key: round(value, 3) for key, value in self.phases.items()}}
