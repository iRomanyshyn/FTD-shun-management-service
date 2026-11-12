"""Select canonical IPs from displayed rows, never a full import manifest."""

from ipaddress import IPv4Address

MAX_DISPLAY_IPS = 1000  # Whole Protected-IP list; ordinary tables remain paginated.


def displayed_ips(context, target=None):
    found = {}

    def add(value):
        try:
            if value is not None:
                found[str(IPv4Address(value))] = None
        except (ValueError, TypeError):
            pass

    def rows(value):
        if not isinstance(value, (list, tuple)):
            return
        for row in value[:MAX_DISPLAY_IPS]:
            if len(found) >= MAX_DISPLAY_IPS:
                break
            add(row.get('ip') if isinstance(row, dict) else getattr(row, 'ip', None))

    add(target)
    for key in ('shuns', 'search_results', 'recent_events', 'events', 'page_targets'):
        rows(context.get(key))
    # Named, bounded presentation collections only. Never traverse .rows/.ips
    # on a large parsed input, canonical authority, or arbitrary context objects.
    for root, keys in (('managed', ('entries',)), ('policy', ('entries',)),
                       ('preview', ('page_rows',)), ('draft', ('targets', 'report_rows')),
                       ('receipt', ('targets',)), ('report', ('targets', 'report_rows')),
                       ('cancellation', ('targets',)), ('status', ('targets',)),
                       ('handoffs', ('items',)), ('fleet_cleanup', ('items',))):
        value = context.get(root)
        for key in keys:
            rows(value.get(key) if isinstance(value, dict) else getattr(value, key, None))
    review = context.get('review')
    targets = getattr(review, 'targets', None) if 'page_targets' not in context else None
    if isinstance(targets, (list, tuple)) and len(targets) <= MAX_DISPLAY_IPS:
        for pair in targets[:MAX_DISPLAY_IPS]:
            if len(found) >= MAX_DISPLAY_IPS:
                break
            if isinstance(pair, (tuple, list)) and len(pair) == 2:
                add(pair[1])
    queue = (context.get('refresh') or {}).get('queue') or {}
    rows(queue.get('items'))
    rows(queue.get('attention_items'))
    return list(found)[:MAX_DISPLAY_IPS]
