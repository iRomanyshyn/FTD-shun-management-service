"""Operator history omits coordination, not failures or original evidence."""

INTERNAL_EVENTS = (
    'DEVICE_LEASE_CLAIMED', 'DEVICE_LEASE_RELEASED',
    'MANAGED_BULK_ATTEMPT_QUEUED', 'MANAGED_BULK_ATTEMPT_RUNNING',
    'SHUN_OPERATION_QUEUED', 'SHUN_OPERATION_RUNNING', 'SHUN_ADDITION_ACKNOWLEDGED',
)


def history_filter(alias=''):
    """Only fixed SQL aliases are accepted; event values remain parameters."""
    if alias not in ('', 'e.'):
        raise ValueError('Unsupported history alias.')
    return alias + 'event_type NOT IN (' + ','.join('?' for _ in INTERNAL_EVENTS) + ')'
