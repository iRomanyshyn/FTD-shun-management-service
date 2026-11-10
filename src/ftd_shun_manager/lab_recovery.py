"""Explicit trusted-host helper for the known single-device desk lab, not Web IPC."""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from .maintenance import _actor

# Trusted bundled code, not user text/CLI. Values travel as a JSON argv element.
CONTROL = r'''
import hashlib,json,sqlite3,sys
from contextlib import closing
from pathlib import Path
from uuid import uuid4
from ftd_shun_manager.bulk_policy import _state
from ftd_shun_manager.device_reconciliation import inspect,reconcile
from ftd_shun_manager.maintenance import checked_offline
p=json.loads(sys.argv[1]); original=Path('/var/lib/ftd-shun-manager/managed-v2.db')
base=original.parent/('recovery-assistance-'+p['run_id'])
def checked(path):
    review=inspect(path,p['device'],extended_v6=p['extended'])
    if review['epoch']!=p['epoch']: raise ValueError('Held epoch changed; review again.')
    return review
def apply(path,name):
    review=checked(path)
    return checked_offline(path,base/name,lambda db,store:reconcile(db,store,p['device'],str(uuid4()),
        p['actor'],review['reviewed_at'],review['review_digest'],offline=True,extended_v6=p['extended']))
def compare(before,after):
    tables=('devices','protected_policy','protected_ips','managed_bulk_registry','managed_shun_requests',
      'managed_shun_targets','managed_bulk_manifests','managed_bulk_members','operation_jobs','operation_requests','managed_bulk_attempts')
    with closing(sqlite3.connect(before.as_uri()+'?mode=ro',uri=True)) as a, closing(sqlite3.connect(after.as_uri()+'?mode=ro',uri=True)) as b:
        b.row_factory=sqlite3.Row; a.execute('BEGIN'); b.execute('BEGIN')
        def digest(db,table):
            rows=sorted(json.dumps(tuple(r),default=lambda v:v.hex()) for r in db.execute('SELECT * FROM '+table))
            return hashlib.sha256(('\n'.join(rows)).encode()).digest()
        if any(digest(a,t)!=digest(b,t) for t in tables): raise ValueError('Original data changed; retain backup and stop.')
        old=dict(a.execute('SELECT id,receipt_json FROM managed_bulk_device_recovery')) if a.execute("SELECT 1 FROM sqlite_master WHERE name='managed_bulk_device_recovery'").fetchone() else {}
        new=dict(b.execute('SELECT id,receipt_json FROM managed_bulk_device_recovery'))
        if len(new)!=len(old)+1 or any(new.get(k)!=v for k,v in old.items()): raise ValueError('Original receipts changed.')
        if b.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or b.execute('PRAGMA foreign_key_check').fetchall(): raise ValueError('Integrity check failed.')
        _state(b)
        fence=b.execute('SELECT state,epoch,owner FROM managed_bulk_device_executors WHERE device_id=?',(p['device'],)).fetchone()
        if tuple(fence)!=('IDLE',p['epoch'],None): raise ValueError('Actual same-epoch release is missing.')
if p['mode']=='rehearse':
    base.mkdir(mode=0o700)
    copy=base/'rehearsal.db'
    with closing(sqlite3.connect(original.as_uri()+'?mode=ro',uri=True)) as a, closing(sqlite3.connect(copy)) as b:a.backup(b)
    copy.chmod(0o600); receipt=apply(copy,'before-rehearsal.db'); compare(base/'before-rehearsal.db',copy)
else:
    if not (base/'before-rehearsal.db').is_file(): raise ValueError('Rehearsal is missing.')
    receipt=apply(original,'before-live-reconciliation.db'); compare(base/'before-live-reconciliation.db',original)
print(json.dumps(receipt),flush=True)
'''


class LabRecovery:
    def __init__(self, root, device, epoch, actor, *, extended=False, run=subprocess.run):
        self.root = Path(root).resolve(strict=True)
        if type(device) is not int or not 1 <= device <= 65535 or type(epoch) is not int or not 1 <= epoch < 2**63:
            raise ValueError('Use an exact positive device ID and held epoch.')
        if type(extended) is not bool:
            raise ValueError('Extended recovery needs a literal explicit selection.')
        _actor(actor)
        paths = ['deploy/compose.yml', 'deploy/compose.local-lab.yml', 'deploy/compose.managed-lab.yml']
        if not all((self.root / path).is_file() for path in ['.env', *paths]):
            raise ValueError('Run from the known lab checkout with .env and all three overlays.')
        self.dc = ['docker', 'compose', '--env-file', str(self.root / '.env')]
        for path in paths:
            self.dc += ['-f', str(self.root / path)]
        self.device, self.epoch, self.actor, self.extended, self.run = device, epoch, actor, extended, run

    def command(self, args, *, source=None, timeout=60):
        result = self.run(args, input=source, text=True, capture_output=True, check=True,
                          timeout=timeout, cwd=self.root)
        return result.stdout.strip()

    def recover(self):
        ids = {service: self.command(self.dc + ['ps', '-q', service]) for service in ('api', 'web', 'agent')}
        if any(not value or '\n' in value for value in ids.values()):
            raise ValueError('One running API, Web and agent are required; no service was stopped.')
        inventory_code = "import sqlite3,json; d=sqlite3.connect('file:/var/lib/ftd-shun-manager/managed-v2.db?mode=ro',uri=True); print(json.dumps(d.execute('SELECT id,hostname FROM devices ORDER BY id').fetchall()))"
        inventory = json.loads(self.command(self.dc + ['exec', '-T', 'api', 'python', '-c', inventory_code]))
        if inventory != [[self.device, 'fpr1010-lab']]:
            raise ValueError('This helper only supports the known single-device fpr1010-lab; nothing was stopped.')
        inspect_args = ['ftd-shun-device-reconciliation', 'inspect', '--database', '/var/lib/ftd-shun-manager/managed-v2.db', '--device', str(self.device)]
        if self.extended:
            inspect_args.append('--extended-v6')
        review = json.loads(self.command(self.dc + ['exec', '-T', 'api', *inspect_args]))
        if review['epoch'] != self.epoch:
            raise ValueError('Held epoch changed; nothing was stopped. Review current recovery status.')
        image = json.loads(self.command(['docker', 'inspect', '--format',
            '{"id":{{json .Image}},"ref":{{json .Config.Image}}}', ids['api']]))
        def check_image():
            actual = self.command(['docker', 'image', 'inspect', '--format', '{{.Id}}', image['ref']])
            if actual != image['id']:
                raise ValueError('API image tag changed; use matching images, not an unreviewed pending build.')
        check_image()
        evidence = Path(tempfile.mkdtemp(prefix='ftd-lab-recovery-'))
        def retain(name, value):
            path = evidence / name
            path.write_text(value)
            path.chmod(0o600)
        retain('review.json', json.dumps(review))
        retain('containers.json', json.dumps(ids))
        retain('failure.log', self.command(self.dc + ['logs', '--timestamps', '--tail=300', 'api', 'agent']))
        print(f'Private failure evidence: {evidence}', flush=True)
        print('Stopping lab API/Web, then agent. Failures leave services stopped for review.', flush=True)
        self.command(self.dc + ['stop', '-t', '300', 'web', 'api'], timeout=340)
        self.command(self.dc + ['stop', '-t', '300', 'agent'], timeout=340)
        for ident in ids.values():
            state = json.loads(self.command(['docker', 'inspect', '--format', '{{json .State}}', ident]))
            if state.get('Status') != 'exited' or state.get('ExitCode') != 0:
                raise ValueError('Actual clean executor exits are required; recovery refused, services remain stopped.')
        params = {'device': self.device, 'epoch': self.epoch, 'actor': self.actor,
                  'extended': self.extended, 'run_id': str(uuid4())}
        for mode in ('rehearse', 'apply'):
            check_image()
            payload = json.dumps({**params, 'mode': mode})
            try:
                receipt = json.loads(self.command(self.dc + ['run', '--rm', '--no-deps', '-T', 'api',
                    'python', '-', payload], source=CONTROL, timeout=180))
            except subprocess.CalledProcessError as error:
                retain(mode + '-failure.txt', error.stderr or str(error))
                raise
            if (receipt['epoch'] != self.epoch or receipt['jobs_retried'] != 0
                    or receipt['original_outcomes_unchanged'] is not True):
                raise ValueError('Unexpected recovery receipt; services remain stopped.')
            retain(mode + '.json', json.dumps(receipt))
            print(json.dumps({'stage': mode, 'receipt': receipt['operation_id'],
                              'backup': receipt['backup']}), flush=True)
        self.command(self.dc + ['start', 'agent'])
        self.command(self.dc + ['start', 'api', 'web'])
        return {'receipt': receipt['operation_id'], 'backup': receipt['backup'],
                'status': 'restarted_pending_fresh_read', 'old_jobs_retried': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Trusted-host recovery for the known desk lab; stops API/Web/agent, retains unknowns, then restarts.')
    parser.add_argument('--directory', type=Path, default=Path.cwd())
    parser.add_argument('--device', type=int, required=True)
    parser.add_argument('--expect-epoch', type=int, required=True)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--extended-v6', action='store_true')
    parser.add_argument('--confirm-lab', action='store_true')
    args = parser.parse_args(argv)
    if not args.confirm_lab:
        parser.error('Explicit --confirm-lab is required; this command stops the known lab services.')
    try:
        result = LabRecovery(args.directory, args.device, args.expect_epoch, args.actor, extended=args.extended_v6).recover()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)
        parser.exit(2, f'Recovery stopped: {detail}. Inspect retained evidence; do not clear holds or restore stale data.\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
