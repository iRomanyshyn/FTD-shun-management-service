"""Bounded advisory RDAP client; fixed registries, no arbitrary referrals."""

import json
import re
from ipaddress import IPv4Address, IPv4Network
from time import monotonic
from urllib.parse import urlsplit

import httpx

BOOTSTRAP = 'https://data.iana.org/rdap/ipv4.json'
REGISTRIES = {'rdap.arin.net': 'ARIN', 'rdap.db.ripe.net': 'RIPE NCC',
              'rdap.apnic.net': 'APNIC', 'rdap.lacnic.net': 'LACNIC', 'rdap.afrinic.net': 'AFRINIC'}
MAX_BYTES = 512 * 1024


def public_ip(ip):
    return type(ip) is IPv4Address and ip.is_global and not ip.is_multicast and not ip.is_reserved


class LookupUnavailable(ValueError):
    def __init__(self, reason, cooldown=60):
        super().__init__(reason)
        self.reason, self.cooldown = reason, cooldown


def clean(value, limit=96):
    if type(value) is not str:
        return None
    return ' '.join(''.join(char for char in value if char.isprintable()).split())[:limit] or None


def registry_url(url, ip=None):
    if type(url) is not str or len(url) > 256:
        raise LookupUnavailable('invalid_registry')
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise LookupUnavailable('invalid_registry') from error
    if (parts.scheme != 'https' or parts.hostname not in REGISTRIES or parts.username or parts.password
            or port not in (None, 443) or parts.query or parts.fragment or '%' in parts.path
            or '..' in parts.path or not parts.path.startswith('/')):
        raise LookupUnavailable('invalid_registry')
    if ip is None:
        if parts.path not in ('/', '/rdap/', '/registry/'):
            raise LookupUnavailable('invalid_registry')
    elif parts.path not in tuple(prefix + str(ip) for prefix in ('/ip/', '/rdap/ip/', '/registry/ip/')):
        raise LookupUnavailable('invalid_referral')
    return url


def services(value):
    if type(value) is not dict or type(value.get('services')) is not list or not 1 <= len(value['services']) <= 512:
        raise LookupUnavailable('invalid_bootstrap')
    result = []
    for entry in value['services']:
        if (type(entry) is not list or len(entry) != 2 or type(entry[0]) is not list
                or type(entry[1]) is not list or not entry[1] or not 1 <= len(entry[0]) <= 512):
            raise LookupUnavailable('invalid_bootstrap')
        urls = []
        for url in entry[1]:
            # Ignore historical HTTP alternatives, never use them as fallback.
            if type(url) is str and url.startswith('https://'):
                urls.append(registry_url(url))
        if not urls:
            raise LookupUnavailable('invalid_bootstrap')
        for prefix in entry[0]:
            try:
                if type(prefix) is not str:
                    raise ValueError('CIDR must be text')
                network = IPv4Network(prefix, strict=True)
            except (ValueError, TypeError) as error:
                raise LookupUnavailable('invalid_bootstrap') from error
            result.append((network, urls[0]))
    if len(result) > 1024:
        raise LookupUnavailable('invalid_bootstrap')
    return result


def registration(value, ip, source):
    registry_url(source, ip)
    if type(value) is not dict or value.get('objectClassName') != 'ip network' or value.get('ipVersion') != 'v4':
        raise LookupUnavailable('invalid_response')
    try:
        first, last = IPv4Address(value['startAddress']), IPv4Address(value['endAddress'])
        if not first <= ip <= last:
            raise ValueError('Foreign address range')
    except (KeyError, ValueError, TypeError) as error:
        raise LookupUnavailable('foreign_network') from error
    country = value.get('country')
    country = country.upper() if type(country) is str and re.fullmatch('[A-Za-z]{2}', country) else None
    organization = None
    entities = value.get('entities', [])
    if type(entities) is list:
        for entity in entities[:32]:
            if (type(entity) is not dict or type(entity.get('roles')) is not list
                    or 'registrant' not in entity['roles']):
                continue
            card = entity.get('vcardArray')
            if type(card) is not list or len(card) != 2 or type(card[1]) is not list:
                continue
            fields = {field[0]: field[3] for field in card[1][:64]
                      if type(field) is list and len(field) == 4 and type(field[0]) is str}
            org = fields.get('org')
            if type(org) is list:
                org = org[0] if org else None
            organization = clean(org) or (clean(fields.get('fn')) if fields.get('kind') == 'org' else None)
            if organization:
                break
    return {'country': country, 'network': clean(value.get('name')), 'organization': organization,
            'range_start': str(first), 'range_end': str(last), 'source': source,
            'registry': REGISTRIES[urlsplit(source).hostname]}


class RdapClient:
    def __init__(self, *, client=None):
        self.bootstrap = None
        self.client = client or httpx.Client(trust_env=False, follow_redirects=False,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
            headers={'User-Agent': 'FTD-Shun-Manager-IP-Context', 'Accept-Encoding': 'identity'})

    def close(self):
        self.client.close()

    def _json(self, url, deadline, *, redirect=False):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise LookupUnavailable('timeout')
        try:
            with self.client.stream('GET', url, timeout=min(2, remaining),
                    headers={'Accept': 'application/rdap+json, application/json', 'Accept-Encoding': 'identity'}) as response:
                if response.status_code == 429:
                    retry = response.headers.get('retry-after', '')
                    raise LookupUnavailable('throttled', min(86400, max(60, int(retry))) if retry.isdigit() else 300)
                if redirect and response.status_code in (301, 302, 303, 307, 308):
                    return None, response.headers.get('location')
                if response.status_code != 200:
                    raise LookupUnavailable('registry_unavailable', 300)
                if response.headers.get('content-encoding', 'identity') != 'identity':
                    raise LookupUnavailable('encoded_response')
                if response.headers.get('content-type', '').split(';')[0] not in ('application/json', 'application/rdap+json'):
                    raise LookupUnavailable('invalid_response')
                raw = bytearray()
                for chunk in response.iter_bytes(16384):
                    if len(raw) + len(chunk) > MAX_BYTES:
                        raise LookupUnavailable('response_too_large')
                    raw.extend(chunk)
                    if monotonic() > deadline:
                        raise LookupUnavailable('timeout')
                return json.loads(raw.decode('utf-8')), None
        except (httpx.HTTPError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
            raise LookupUnavailable('registry_unavailable') from error

    def lookup(self, ip, bootstrap=None):
        if not public_ip(ip):
            raise LookupUnavailable('special_use_address')
        deadline = monotonic() + 8
        if bootstrap is None:
            bootstrap, _ = self._json(BOOTSTRAP, deadline)
        available = services(bootstrap)
        self.bootstrap = bootstrap
        choices = [(network.prefixlen, url) for network, url in available if ip in network]
        if not choices:
            raise LookupUnavailable('no_registry')
        url = max(choices)[1] + 'ip/' + str(ip)
        visited = set()
        for _ in range(3):
            registry_url(url, ip)
            if url in visited:
                break
            visited.add(url)
            value, location = self._json(url, deadline, redirect=True)
            if location is None:
                return registration(value, ip, url), bootstrap
            url = registry_url(location, ip)
        raise LookupUnavailable('referral_limit')
