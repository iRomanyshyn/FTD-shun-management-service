"""Render Compose using synthetic values; never read the operator's private .env."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(tmp_path, overlays=(), extra=''):
    if not shutil.which('docker') or subprocess.run(['docker', 'compose', 'version'], capture_output=True, check=False).returncode:
        pytest.skip('Docker Compose CLI is required; no daemon/device is used.')
    fixture = tmp_path / 'compose.env'
    fixture.write_text('''FTD_SHUN_HOST=workspace.example.test
AUTH_HOST=auth.example.test
AUTH_COOKIE_DOMAIN=example.test
PUBLISH_ADDRESS=127.0.0.1
AUTHELIA_SESSION_SECRET=synthetic-session-secret-never-real
AUTHELIA_STORAGE_ENCRYPTION_KEY=synthetic-storage-secret-never-real
FTD_SHUN_SSH_USERNAME=synthetic-ssh-user
UNRELATED_PRIVATE_MARKER=must-not-reach-any-container
''' + extra)
    # Explicit env-file supplies all fixture values, never the real root .env.
    command = ['docker', 'compose', '--env-file', str(fixture), '-f', str(ROOT / 'deploy/compose.yml')]
    for overlay in overlays:
        command += ['-f', str(ROOT / 'deploy' / overlay)]
    command += ['config', '--format', 'json']
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('FTD_SHUN_', 'AUTH_', 'AUTHELIA_', 'PUBLISH_ADDRESS', 'UNRELATED_PRIVATE_MARKER'))}
    result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)['services']


def test_base_has_explicit_environment_boundaries():
    config = yaml.safe_load((ROOT / 'deploy/compose.yml').read_text())
    for service in config['services'].values():
        assert 'env_file' not in service
    assert 'FTD_SHUN_SSH_USERNAME' not in config['services']['api']['environment']
    assert 'FTD_SHUN_ENV_PROTECTED_NETWORKS' not in config['services']['web']['environment']
    for name, service in config['services'].items():
        if name != 'authelia':
            assert not any(key.startswith('AUTHELIA_') for key in service.get('environment', {}))


@pytest.mark.parametrize('overlays', [(), ('compose.local-lab.yml','compose.managed-lab.yml','compose.ip-context.lab.yml'),
    ('compose.managed-lab.yml','compose.deferred-lab.yml','compose.agent-journal.lab.yml')])
def test_rendered_services_receive_only_their_own_secrets_and_keep_guards(tmp_path, overlays):
    services = render(tmp_path, overlays, 'FTD_SHUN_ENV_PROTECTED_NETWORKS=10.0.0.0/8\n')
    for name, service in services.items():
        environment = service.get('environment', {})
        assert 'UNRELATED_PRIVATE_MARKER' not in environment
        if name != 'authelia':
            assert not any(key.startswith('AUTHELIA_') for key in environment)
            assert 'synthetic-session-secret-never-real' not in json.dumps(service)
            assert 'synthetic-storage-secret-never-real' not in json.dumps(service)
        if name != 'agent':
            assert 'FTD_SHUN_SSH_USERNAME' not in environment
    assert services['api']['environment']['FTD_SHUN_ENV_PROTECTED_NETWORKS'] == '10.0.0.0/8'
    assert services['agent']['environment']['FTD_SHUN_ENV_PROTECTED_NETWORKS'] == '10.0.0.0/8'
    assert set(services['caddy']['environment']) == {'AUTH_HOST', 'FTD_SHUN_HOST'}
    assert services['authelia']['environment']['AUTHELIA_SESSION_SECRET'] == 'synthetic-session-secret-never-real'
    assert services['web']['network_mode'] == services['api']['network_mode'] == 'none'
    assert not services['web'].get('secrets') and not services['api'].get('secrets')
    if 'compose.agent-journal.lab.yml' not in overlays:
        assert services['agent']['environment'].get('FTD_SHUN_AGENT_PENDING_JOURNAL_DIRECTORY') is None


def test_optional_agent_value_and_per_device_overlay_keep_their_original_semantics(tmp_path):
    services = render(tmp_path, extra='FTD_SHUN_AGENT_PENDING_JOURNAL_DIRECTORY=/private/agent-journal\n')
    assert services['agent']['environment']['FTD_SHUN_AGENT_PENDING_JOURNAL_DIRECTORY'] == '/private/agent-journal'
    services = render(tmp_path, ('compose.per-device-credentials.yml',), 'FTD_SHUN_SSH_USERNAME=\n')
    agent = services['agent']
    assert agent['environment']['FTD_SHUN_SSH_CREDENTIALS_MODE'] == 'per-device'
    assert not agent.get('secrets')
