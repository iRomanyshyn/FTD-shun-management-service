"""Explicit developer API composition; no environment selector or migration."""

import re

from .agent_client import UnixAgentClient
from .bulk_policy import _state
from .continuous_dispatch import ContinuousDispatcher
from .operation_queue import QueueConflict
from .protected_policy import ProtectedPolicy


class ContinuousApiRuntime:
    """Restricted existing-profile API, not general v2 write-workflow activation."""

    def __init__(self, settings, store, dispatcher, agent=None, *, ready_removal_admission_enabled=False,
                 ordered_removal_admission_enabled=False):
        if type(dispatcher) is not ContinuousDispatcher:
            raise ValueError('An explicit continuous dispatcher is required.')
        self.settings, self.store, self.dispatcher = settings, store, dispatcher
        if type(ready_removal_admission_enabled) is not bool:
            raise ValueError('Ready removal admission capability must be a literal boolean.')
        self.ready_removal_admission_enabled = ready_removal_admission_enabled
        self.ordered_removal_admission_enabled = ordered_removal_admission_enabled
        self._started = False
        self._validate(agent)
        if getattr(dispatcher, '_api_application_bound', False):
            raise QueueConflict('This dispatcher is already bound to an API application.')
        dispatcher._api_application_bound = True
        self.policy = ProtectedPolicy(store, initialize_queue=False)
        self.queue = dispatcher.runner.queue
        from .bulk_ordered_waits import BulkOrderedWaits
        from .bulk_policy import BulkPolicies
        from .bulk_policy_views import BulkPolicyViews
        from .bulk_removals import BulkRemovals, BulkRemovalScopes

        self.policy_views = BulkPolicyViews(store)
        self.policy_revocation = BulkPolicies(store, clock=self.queue._now)
        self.removal_scopes = BulkRemovalScopes(store)
        self.ready_removals = BulkRemovals(store, self.queue)
        self.ordered_removals = BulkOrderedWaits(store, self.queue)
        # Legacy routes are explicitly refused before handler dispatch.
        self.managed_removals = None

    def _validate(self, agent=None):
        if type(self.ready_removal_admission_enabled) is not bool:
            raise ValueError('Ready removal admission capability must be a literal boolean.')
        if type(self.ordered_removal_admission_enabled) is not bool:
            raise ValueError('Ordered removal admission capability must be a literal boolean.')
        settings, service = self.settings, self.dispatcher
        runner, config = service.runner, service.runner.configuration
        if (runner.store is not self.store or settings.database_path != self.store.path
                or (agent is not None and agent is not runner.agent)):
            raise ValueError('API, dispatcher, agent and database must share the exact existing composition.')
        if (settings.agent_mode != 'socket' or settings.agent_cycles_enabled is not True
                or settings.large_snapshots_enabled is not True or not runner.enabled
                or settings.device_inventory_path is not None or settings.development_auth is not False
                or runner.settled_cycles_required is not True):
            raise ValueError('Continuous API requires socket/cycles/large reads and an already loaded fixed inventory.')
        if (type(settings.poll_interval_seconds) is not int or not 60 <= settings.poll_interval_seconds <= 86400
                or type(settings.interactive_refresh_min_interval_seconds) is not int
                or settings.interactive_refresh_min_interval_seconds < 60):
            raise ValueError('Continuous API retains the baseline/manual read-spacing floors.')
        gates = (settings.import_admission_enabled, settings.import_execution_enabled,
                 settings.managed_policy_admission_enabled, settings.managed_removal_admission_enabled,
                 settings.managed_restoration_enabled, settings.managed_removal_worker_enabled)
        if (any(value is not False for value in gates) or config['bulk_dispatch_enabled'] is not False
                or config['import_execution_enabled'] is not False or config['addition_device_ids']):
            raise ValueError('This API profile cannot enable ADD, legacy admission or managed controllers.')
        if (config['operation_timeout_seconds'] != settings.agent_timeout_seconds + 5
                or config['poll_interval_seconds'] != settings.poll_interval_seconds
                or config['interactive_min_interval_seconds'] != settings.interactive_refresh_min_interval_seconds
                or service.maintenance.history_retention_days != settings.history_retention_days):
            raise ValueError('Continuous controller deadlines, read spacing and retention must match API settings.')
        if isinstance(runner.agent, UnixAgentClient) and (
                runner.agent.socket_path != settings.agent_socket or runner.agent.timeout_seconds != settings.agent_timeout_seconds + 5
                or runner.agent.large_snapshots is not True or runner.agent.settled_cycles is not True
                or runner.agent.additions_enabled is not False or runner.agent.addition_device_ids != frozenset()):
            raise ValueError('Continuous API requires a matching strict large-read transport with an explicit empty ADD scope.')
        if (service._task is not None or runner._round is not None or runner._service_active
                or runner._broken or service.maintenance.status()['running'] or service.maintenance.status()['broken']):
            raise QueueConflict('API must exclusively own an inactive, unbroken continuous lifecycle.')
        if not self.store.path.is_file():
            raise QueueConflict('Continuous API requires existing storage; nothing was initialized.')
        runner._configured_devices()  # Exact optional profile/scope/settlement/capacity; no migration.
        if self.ordered_removal_admission_enabled:
            if service.ordered_promotion_enabled is not True:
                raise ValueError('Ordered API admission requires the separate owning promotion capability.')
            service.ordered_promoter.require_storage()  # Existing exact storage; never migrate.
        with self.store._connection() as db:
            db.execute('BEGIN')
            marker = db.execute('SELECT legacy_imported FROM protected_policy WHERE id=1').fetchone()
            if marker is None or marker[0] != 1:
                raise QueueConflict('Existing Protected IP migration must already be complete; startup will not import environment policy.')
            # Exercise actual base read contracts without ALTER/backfill/DDL.
            db.execute('SELECT occurrence_id,last_changed_at FROM shun_state LIMIT 0')
            db.execute('SELECT batch_id,job_id,occurrence_id,verified_at FROM shun_import_origins LIMIT 0')
        self.managed_metadata()

    def managed_metadata(self):
        """Version-aware metadata; never pretend v2 is a missing legacy registry."""
        with self.store._connection() as db:
            db.execute('BEGIN')
            state = _state(db)
            if state is None:
                raise QueueConflict('Existing version-2 policy is required.')
            return {'managed_policy_available': True, 'managed_policy_initialized': True,
                    'managed_policy_revision': state['revision'], 'managed_policy_format': 2}

    def supports(self, method, path):
        if method == 'GET':
            return bool(path in {'/api/v1/status', '/api/v1/shuns', '/api/v1/import-devices',
                                 '/api/v1/history', '/api/v1/history-page', '/api/v1/search', '/api/v1/protected-ips',
                                 '/api/v2/managed-shuns/page'}
                        or re.fullmatch(r'/api/v1/(?:shuns|history)/[^/]+', path)
                        or re.fullmatch(r'/api/v2/managed-removal-scope/[^/]+', path)
                        or re.fullmatch(r'/api/v2/managed-ordered-removal-scope/[^/]+', path)
                        or re.fullmatch(r'/api/v2/managed-ordered-removals/[0-9a-f-]{36}', path))
        if method == 'POST':
            return bool(path in {'/api/v1/refresh-hint', '/api/v1/import-preview',
                                 '/api/v2/managed-shuns/selection', '/api/v2/managed-shuns/retire',
                                 '/api/v2/managed-imports/prepare', '/api/v2/managed-imports/preparations',
                                 '/api/v2/managed-imports/preparation', '/api/v2/managed-imports/proposal',
                                 '/api/v2/managed-imports/cancel-preparation'}
                        or (self.ready_removal_admission_enabled is True and path in {
                            '/api/v2/managed-removals/device', '/api/v2/managed-removals/fleet'})
                        or (self.ordered_removal_admission_enabled is True and path in {
                            '/api/v2/managed-ordered-removals/device', '/api/v2/managed-ordered-removals/fleet'})
                        or re.fullmatch(r'/api/v2/managed-ordered-removals/[0-9a-f-]{36}/cancel', path)
                        or re.fullmatch(r'/api/v1/protected-ips/[^/]+/(?:add|edit|delete)', path))
        return False

    async def start(self):
        if self._started:
            raise QueueConflict('This API lifecycle is already running.')
        self._validate()
        await self.dispatcher.start()
        self._started = True

    async def stop(self):
        try:
            await self.dispatcher.stop()
        finally:
            self._started = False

    def status(self):
        self.managed_metadata()  # Drift is unavailable state, never a legacy/empty fallback.
        return {**self.dispatcher.refresh_status(), 'runtime_mode': 'continuous-observation',
                'manual_mutations_available': False, 'managed_workflows_available': False,
                'managed_policy_view_available': True, 'managed_policy_retirement_available': True,
                'ready_removal_review_available': True,
                'ready_removal_admission_enabled': self.ready_removal_admission_enabled,
                'ordered_removal_review_available': True,
                'bulk_import_preparation_available': True,
                'ordered_removal_admission_enabled': self.ordered_removal_admission_enabled,
                'ordered_removal_promotion_enabled': self.dispatcher.ordered_promotion_enabled is True}

    def request_activity(self):
        self.dispatcher.request_activity()
        return self.status()

    def note_state_change(self):
        self.dispatcher.note_state_change()
