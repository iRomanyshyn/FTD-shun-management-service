"""Fixed local JSON bridge to Debian's native libloc Python bindings.

Executed by /usr/bin/python3 in the optional worker, never by Web/API/agent.
"""

import json
import sys


def main():
    import location

    request = json.load(sys.stdin)
    ips = request['ips']
    if type(ips) is not list or len(ips) > 1000:
        raise ValueError('Bounded IP batch required.')
    db = location.Database(request['database'])
    rows = {}
    for ip in ips:
        network = db.lookup(ip)
        if network is None:
            rows[ip] = None
            continue
        asn = network.asn or None
        autonomous_system = db.get_as(asn) if asn else None
        rows[ip] = {'prefix': str(network), 'country': network.country_code or None,
                    'asn': asn, 'organization': autonomous_system.name if autonomous_system else None}
    print(json.dumps({'created_at': db.created_at, 'rows': rows}))


if __name__ == '__main__':
    main()
