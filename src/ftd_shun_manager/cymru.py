"""Bounded advisory Team Cymru DNS lookups; no policy or page-triggered work."""

import asyncio
import re
from datetime import date
from ipaddress import IPv4Address, IPv4Network

from .rdap import clean, public_ip

PROFILE = 'team-cymru-dns-v1'
SOURCE = 'https://www.team-cymru.com/ip-asn-mapping'
REGISTRIES = {'arin', 'ripencc', 'apnic', 'lacnic', 'afrinic'}


def optional(value):
    return None if value in ('', 'NA') else value


def country(value):
    value = optional(value)
    if value is not None and re.fullmatch('[A-Z]{2}', value) is None:
        raise ValueError('Invalid registration country.')
    return value


def registry(value):
    value = optional(value)
    if value is not None and value not in REGISTRIES:
        raise ValueError('Invalid routing registry.')
    return value


def allocated(value):
    value = optional(value)
    if value is not None and (date.fromisoformat(value).isoformat() != value):
        raise ValueError('Invalid allocation date.')
    return value


def fields(text):
    if type(text) is not str or len(text.encode('utf-8')) > 512 or any(not c.isprintable() for c in text):
        raise ValueError('Invalid routing response.')
    parts = [part.strip() for part in text.split('|', 4)]
    if len(parts) != 5:
        raise ValueError('Incomplete routing response.')
    return parts


def origin(text, ip):
    numbers, prefix, cc, rir, when = fields(text)
    if not re.fullmatch(r'[0-9]+(?: [0-9]+){0,15}', numbers):
        raise ValueError('Invalid origin ASNs.')
    value = {'provider': PROFILE, 'source': SOURCE, 'network': prefix,
             'asns': sorted({int(n) for n in numbers.split()}), 'organization': None,
             'registration_country': country(cc), 'registry': registry(rir), 'allocated_at': allocated(when)}
    return checked_context(value, ip)


def checked_context(value, ip):
    if (type(value) is not dict or set(value) != {'provider', 'source', 'network', 'asns',
            'organization', 'registration_country', 'registry', 'allocated_at'}
            or value['provider'] != PROFILE or value['source'] != SOURCE or not public_ip(ip)):
        raise ValueError('Invalid Cymru context.')
    if type(value['network']) is not str:
        raise ValueError('Invalid routing prefix.')
    network = IPv4Network(value['network'], strict=True)
    if str(network) != value['network'] or ip not in network:
        raise ValueError('Foreign routing prefix.')
    asns = value['asns']
    if (type(asns) is not list or not 1 <= len(asns) <= 16
            or any(type(n) is not int or not 1 <= n <= 2**32 - 1 for n in asns)
            or asns != sorted(set(asns))):
        raise ValueError('Invalid routing ASNs.')
    for field, validate in (('registration_country', country), ('registry', registry), ('allocated_at', allocated)):
        if validate(value[field]) != value[field]:
            raise ValueError('Noncanonical routing field.')
    name = value['organization']
    if name is not None and (type(name) is not str or not 1 <= len(name) <= 96
                            or any(not c.isprintable() for c in name)):
        raise ValueError('Invalid routing name.')
    return value


class CymruDNS:
    def __init__(self, resolver=None):
        # Keep dnspython out of Web/API/agent imports and ordinary images.
        if resolver is None:
            import dns.asyncresolver
            import dns.resolver

            resolver = dns.asyncresolver.Resolver()
            resolver.cache = dns.resolver.LRUCache(max_size=4096)
        self.resolver = resolver

    async def _txt(self, name, semaphore):
        import dns.exception
        import dns.resolver

        async with semaphore:
            try:
                answer = await self.resolver.resolve(name, 'TXT', search=False, lifetime=4)
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                return []
            except (dns.exception.DNSException, OSError) as error:
                raise ValueError('Routing DNS unavailable.') from error
            if len(answer) > 8:
                raise ValueError('Too many routing records.')
            rows = []
            for record in answer:
                raw = b''.join(record.strings)
                if len(raw) > 512:
                    raise ValueError('Oversized routing record.')
                rows.append(raw.decode('utf-8'))
            return rows

    async def _lookup(self, ips):
        semaphore = asyncio.Semaphore(8)

        async def mapping(ip):
            name = '.'.join(reversed(str(ip).split('.'))) + '.origin.asn.cymru.com.'
            try:
                rows = await self._txt(name, semaphore)
                if not rows:
                    return None, 'not_mapped'
                values = [origin(row, ip) for row in rows]
                # Several routes may cover an IP. Select the most specific, and
                # combine its origin ASNs only when registry metadata agrees.
                length = max(IPv4Network(v['network']).prefixlen for v in values)
                selected = [v for v in values if IPv4Network(v['network']).prefixlen == length]
                value = selected[0]
                if any({k: v for k, v in item.items() if k != 'asns'} !=
                       {k: v for k, v in value.items() if k != 'asns'} for item in selected):
                    raise ValueError('Conflicting routing records.')
                value['asns'] = sorted({n for item in selected for n in item['asns']})
                return checked_context(value, ip), None
            except (ValueError, TypeError, AttributeError, UnicodeError):
                return None, 'lookup_failed'

        mapped = await asyncio.gather(*(mapping(ip) for ip in ips))
        numbers = sorted({n for value, _ in mapped if value for n in value['asns']})

        async def description(number):
            try:
                rows = await self._txt(f'AS{number}.asn.cymru.com.', semaphore)
                if len(rows) != 1:
                    return None
                actual, cc, rir, when, name = fields(rows[0])
                if actual != str(number):
                    raise ValueError('Foreign ASN response.')
                country(cc), registry(rir), allocated(when)
                return clean(optional(name))
            except (ValueError, TypeError, AttributeError, UnicodeError):
                return None

        # Bound name amplification even for many-origin prefixes. A partial name
        # lookup retains the useful prefix/ASNs and schedules a bounded retry.
        queried = numbers[:500]
        names = dict(zip(queried, await asyncio.gather(*(description(n) for n in queried)), strict=True))
        result = {}
        for ip, (value, reason) in zip(ips, mapped, strict=True):
            if value:
                value['organization'] = clean('; '.join(dict.fromkeys(names[n] for n in value['asns'] if names.get(n))))
                reason = None if all(names.get(n) for n in value['asns']) else 'name_unavailable'
            result[str(ip)] = (value, reason)
        return result

    def lookup_many(self, ips):
        if (type(ips) is not list or not 1 <= len(ips) <= 500 or len(set(ips)) != len(ips)
                or any(type(ip) is not IPv4Address or not public_ip(ip) for ip in ips)):
            raise ValueError('Select at most 500 distinct public IPv4 addresses.')

        async def bounded():
            return await asyncio.wait_for(self._lookup(ips), timeout=30)

        try:
            return asyncio.run(bounded())
        except TimeoutError:
            return {str(ip): (None, 'lookup_failed') for ip in ips}
