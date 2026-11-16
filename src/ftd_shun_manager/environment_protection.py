"""Read-only deployment protection, independent of editable exact-IP policy."""

from dataclasses import dataclass
from functools import lru_cache
from ipaddress import IPv4Address, IPv4Network
from os import environ

VARIABLE = 'FTD_SHUN_ENV_PROTECTED_NETWORKS'
ACTOR = 'system:environment-ip-policy'


@lru_cache(maxsize=16384)
def _rule(networks, ip):
    return next((str(network) for network in networks if ip in network), None)


@dataclass(frozen=True)
class EnvironmentProtection:
    networks: tuple[IPv4Network, ...] = ()

    @classmethod
    def parse(cls, text: str):
        if not text.strip():
            return cls()
        parts = text.split(',')
        if len(parts) > 64:
            raise ValueError(f'{VARIABLE}: use at most 64 exact IPv4 addresses or canonical IPv4 CIDRs.')
        networks = []
        for part in parts:
            value = part.strip()
            try:
                network = IPv4Network(value, strict=True)
                if not value or (str(network) if '/' in value else str(network.network_address)) != value:
                    raise ValueError('Noncanonical address or network.')
            except ValueError as error:
                raise ValueError(f'{VARIABLE}: use comma-separated exact IPv4 addresses or canonical IPv4 CIDRs.') from error
            networks.append(network)
        return cls(tuple(sorted(set(networks), key=lambda network: (int(network.network_address), network.prefixlen))))

    @classmethod
    def from_environment(cls):
        return cls.parse(environ.get(VARIABLE, ''))

    def rule(self, ip: IPv4Address | str) -> str | None:
        return _rule(self.networks, IPv4Address(ip)) if self.networks else None

    def contains(self, ip: IPv4Address) -> bool:
        return self.rule(ip) is not None

    def sql_contains(self, value) -> int:
        # SQL guards always receive the same canonical packed IPv4 type as policy.
        if not isinstance(value, bytes) or len(value) != 4:
            raise ValueError('Environment protection requires a packed IPv4 address.')
        return int(self.contains(IPv4Address(value)))

    def install(self, db) -> None:
        db.create_function('env_protected_ip', 1, self.sql_contains, deterministic=True)

    def metadata(self) -> dict:
        return {'variable': VARIABLE, 'networks': [str(network) for network in self.networks]}
