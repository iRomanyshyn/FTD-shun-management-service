"""Explicit button consent over the original CSRF-bound, frozen review."""


def confirmed(fields, ip, action):
    if 'confirm_action' in fields:
        # Reject ambiguous mixed/new/old submissions. Old open tabs may still
        # submit their original correctly typed IP, without a new action field.
        return fields['confirm_action'] == [action] and 'confirm_ip' not in fields
    return fields.get('confirm_ip') == [str(ip)]
