"""Browser policy for the same-origin operator workspace and its sign-in redirect."""

import re
from ipaddress import IPv6Address
from urllib.parse import urlsplit


def authentication_origin(host: str | None) -> str | None:
    if not host:
        return None
    try:
        parsed = urlsplit('https://' + host)
        if (parsed.netloc != host or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment or not parsed.hostname):
            raise ValueError('Invalid authority.')
        if ':' in parsed.hostname:
            IPv6Address(parsed.hostname)
        elif not re.fullmatch(r'[A-Za-z0-9.-]+', parsed.hostname):
            raise ValueError('Invalid hostname.')
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError('Invalid port.')
    except ValueError as error:
        raise ValueError('AUTH_HOST must be a hostname or IP authority, optionally with a port.') from error
    return 'https://' + host


def browser_headers(auth_host: str | None = None) -> dict[str, str]:
    auth = authentication_origin(auth_host)
    form_action = "'self'" + (' ' + auth if auth else '')
    return {
        'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            f"form-action {form_action}; base-uri 'none'; object-src 'none'; frame-ancestors 'none'",
        'X-Frame-Options': 'DENY',
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'same-origin',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    }
