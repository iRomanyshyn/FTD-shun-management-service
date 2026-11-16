"""Real Web responses keep the browser policy on pages, assets and handled errors."""

import asyncio
from pathlib import Path

import httpx
import pytest

from ftd_shun_manager.config import Settings
from ftd_shun_manager.security_headers import authentication_origin, browser_headers
from ftd_shun_manager.web import create_app


@pytest.mark.parametrize('host', ['auth.example.test', 'auth.example.test:8443', '[::1]:443'])
def test_form_policy_allows_the_exact_signin_origin_without_inline_execution(host):
    headers = browser_headers(host)
    directives = dict(item.strip().split(' ', 1) for item in headers['Content-Security-Policy'].split(';'))
    assert directives['form-action'] == "'self' https://" + host
    assert directives['script-src'] == directives['style-src'] == directives['connect-src'] == "'self'"
    assert directives['frame-ancestors'] == directives['base-uri'] == directives['object-src'] == "'none'"
    assert 'unsafe-inline' not in headers['Content-Security-Policy']
    assert 'unsafe-eval' not in headers['Content-Security-Policy']
    assert headers['X-Frame-Options'] == 'DENY' and headers['X-Content-Type-Options'] == 'nosniff'
    # HTTPS transport policy belongs at the real TLS terminator, not spoofable proxy headers.
    assert 'Strict-Transport-Security' not in headers


@pytest.mark.parametrize('host', ['https://auth.example', 'user:password@auth.example',
    'auth.example/path', 'auth.example?x=1', 'auth.example#x', 'auth.example;bad',
    'auth.example\r\nX-Test: bad', 'auth.example:65536', 'auth.example:0', '[bad]'])
def test_bad_auth_authority_cannot_inject_or_relax_policy(host):
    with pytest.raises(ValueError, match='AUTH_HOST'):
        authentication_origin(host)


@pytest.mark.parametrize('path,code', [('/healthz', 200), ('/static/freshness.js', 200),
    ('/', 401), ('/not-a-route', 404), ('/shuns/not-an-ip', 422)])
def test_actual_web_response_has_security_headers_and_keeps_status(monkeypatch, path, code):
    monkeypatch.setenv('AUTH_HOST', 'auth.example.test')
    app = create_app(Settings.from_environment())

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://workspace.test') as client:
            response = await client.get(path)
            assert response.status_code == code
            for name, value in browser_headers('auth.example.test').items():
                assert response.headers[name] == value
            if not path.startswith('/static/'):
                assert response.headers['cache-control'] == 'no-store'
    asyncio.run(scenario())


def test_edge_and_bff_use_the_same_csp_without_overriding_authelia_policy():
    root = Path(__file__).resolve().parents[1]
    snippet = (root / 'deploy/caddy/security-headers.caddy').read_text()
    csp = snippet.split('>Content-Security-Policy "', 1)[1].split('"', 1)[0]
    assert csp.replace('{$AUTH_HOST}', 'auth.example.test') == browser_headers('auth.example.test')['Content-Security-Policy']
    for name in ('Caddyfile', 'Caddyfile.local-lab'):
        config = (root / 'deploy/caddy' / name).read_text()
        auth, workspace = config.split('https://{$AUTH_HOST}', 1)[1].split('https://{$FTD_SHUN_HOST}', 1)
        assert 'workspace_security' not in auth and 'import workspace_security' in workspace
        assert 'import authentication_errors' in auth and 'import workspace_errors' in workspace
        assert 'includeSubDomains' not in config and 'preload' not in config
