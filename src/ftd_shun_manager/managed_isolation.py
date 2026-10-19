"""Validate retained abandonment, never resolve outcomes or release pair latches."""

import json
from datetime import datetime, timedelta
from ipaddress import IPv4Address

from .managed_abandonment import _evidence, _input
from .managed_closures import decision, present
from .managed_restoration import ACTOR, validate_binding


def isolated_incidents(db, now):
    """Exact closed incidents eligible for a separate unrelated-policy resume."""
    if not db.in_transaction or not present(db):
        raise ValueError("Unrelated-policy resume requires an existing closure ledger and transaction.")
    incidents = []
    try:
        for row in db.execute("SELECT * FROM managed_incident_closures ORDER BY attempt_id"):
            receipt = decision(db, row["attempt_id"])
            evidence = json.loads(row["evidence_json"])
            result = json.loads(row["result_json"])
            request = json.loads(row["request_json"])
            current = _evidence(db, row["attempt_id"])
            attempt, target = current["attempt"], current["current_target"]
            old_target = evidence["current_target"]
            issued, closed = datetime.fromisoformat(row["reviewed_at"]), datetime.fromisoformat(row["closed_at"])
            inputs = _input(row["id"], "restoration:" + row["attempt_id"],
                            row["actor_subject"].removeprefix("maintenance:"), row["reason"], issued)
            digest = request["confirmation_digest"]
            if (inputs["actor_subject"] != row["actor_subject"]
                    or closed.utcoffset() != timedelta(0) or not issued <= closed <= now
                    or closed - issued >= timedelta(minutes=5)
                    or not isinstance(digest, str) or len(digest) != 64
                    or any(char not in "0123456789abcdef" for char in digest)
                    or request != {**inputs, "confirmation_digest": digest, "confirm_ip": target["ip"]}
                    or evidence["attempt"] != attempt or target["enabled"] != 0
                    or row["device_id"] != target["device_id"]):
                raise ValueError
            # Explicit pair/identity checks, including later-generation retirement.
            if (str(IPv4Address(row["ip"])) != target["ip"]
                    or row["retired_intent_id"] != target["intent_id"]
                    or row["retired_generation"] != target["generation"]
                    or type(result["managed_revision"]) is not int or result["managed_revision"] < 1):
                raise ValueError
            expected_result = {
                "operation_id": row["id"], "case_id": "restoration:" + row["attempt_id"],
                "decision": "ABANDON_MAINTENANCE", "device_id": target["device_id"], "ip": target["ip"],
                "retired_intent_id": target["intent_id"], "retired_generation": target["generation"],
                "retired_now": bool(old_target["enabled"]), "managed_revision": result["managed_revision"],
                "closed_at": row["closed_at"], "outcome_unchanged": attempt["state"], "replayed": False,
            }
            expected_target = dict(old_target)
            if old_target["enabled"]:
                expected_target.update(enabled=0, revision=result["managed_revision"],
                                       updated_at=row["closed_at"], retired_at=row["closed_at"])
            if result != expected_result or target != expected_target or receipt["outcome_unchanged"] != attempt["state"]:
                raise ValueError
            # Pruning is not success; a retained/reappeared mismatched job cannot be exempted.
            old_job = evidence["job"]
            if old_job is not None and any(old_job[key] != value for key, value in {
                    "id": attempt["job_id"], "device_id": attempt["device_id"], "ip": attempt["ip"],
                    "action": "ADD", "state": attempt["state"]}.items()):
                raise ValueError
            if current["job"] is not None and current["job"] != evidence["job"]:
                raise ValueError
            delegation = db.execute("SELECT * FROM operation_requests WHERE id=?", (attempt["id"],)).fetchone()
            links = db.execute("SELECT * FROM operation_links WHERE request_id=? OR job_id=?",
                               (attempt["id"], attempt["job_id"])).fetchall()
            if delegation is not None:
                expected_payload = {"scope": "managed_restoration", "intent_id": attempt["intent_id"],
                                    "generation": attempt["generation"], "targets": [[attempt["device_id"], attempt["ip"]]]}
                if (delegation["source"] != "trusted_policy" or delegation["actor_subject"] != ACTOR
                        or json.loads(delegation["actor_roles_json"]) != [] or delegation["state"] == "ACTIVE"
                        or json.loads(delegation["payload_json"]) != expected_payload
                        or delegation["requested_at"] != attempt["requested_at"]
                        or datetime.fromisoformat(delegation["expires_at"]) - datetime.fromisoformat(delegation["requested_at"]) != timedelta(seconds=900)):
                    raise ValueError
            if current["job"] is not None and (delegation is not None or links):
                validate_binding(db, {**attempt, "ip": IPv4Address(attempt["ip"]).packed},
                                 {**current["job"], "ip": IPv4Address(attempt["ip"]).packed})
            elif links:
                raise ValueError("Pruned system job has inconsistent request links.")
            incidents.append({"case_id": "restoration:" + row["attempt_id"], "decision_id": row["id"],
                              "device_id": target["device_id"], "ip": target["ip"], "outcome": attempt["state"],
                              "job_id": attempt["job_id"], "job_retained": current["job"] is not None,
                              "delegation_retained": delegation is not None,
                              "retired_intent_id": target["intent_id"], "retired_generation": target["generation"]})
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ValueError("Abandonment evidence is inconsistent; unrelated-policy resume refused.") from error
    return incidents
