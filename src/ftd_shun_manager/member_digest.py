"""Exact canonical source hashing with bounded formatting reuse, not authority caching."""

from .import_preparations import _feed, _json, _member


class MemberDigest:
    """One streaming verification, at most ten common JSON framing templates.

    Only unobserved PROPOSE_ADD rows without predecessors share framing. Every
    literal member/IP still contributes its complete length-prefixed JSON bytes.
    Other shapes retain the general canonical encoder, including its escaping.
    No manifest summary, membership or validation result is cached.
    """

    _FIELDS = frozenset({'device_id', 'ip', 'classification', 'managed_enabled', 'observed_at',
                         'previous_intent_id', 'previous_generation', 'previous_authorization_request_id'})

    def __init__(self, digest):
        self.digest = digest
        self._templates = {}

    def feed(self, row):
        value = _member(row)
        device = value['device_id']
        common = (value.keys() == self._FIELDS and type(device) is int and 1 <= device <= 65535
                  and value['classification'] == 'PROPOSE_ADD'
                  and value['managed_enabled'] is False and value['observed_at'] is None
                  and all(value[key] is None for key in ('previous_intent_id', 'previous_generation',
                                                        'previous_authorization_request_id')))
        template = self._templates.get(device) if common else None
        if common and template is None and len(self._templates) < 10:
            # The IP is already a canonical IPv4 literal, which needs no JSON
            # escaping. All other fields use the original canonical encoder.
            raw = _json({**value, 'ip': ''}).encode('utf-8')
            before, after = raw.split(b'"ip":""')
            template = self._templates[device] = (before + b'"ip":"', b'"' + after)
        if template is None:
            _feed(self.digest, value)
            return
        raw = template[0] + value['ip'].encode('ascii') + template[1]
        self.digest.update(len(raw).to_bytes(4, 'big'))
        self.digest.update(raw)
