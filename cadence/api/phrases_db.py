"""
DynamoDB helpers for phrase management and audit logging.
Supports LOCAL_MODE (in-memory dict) when USE_LOCAL_DB=true.
"""

import os
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from decimal import Decimal
from copy import deepcopy

# ── Configuration ──────────────────────────────────────────────
PHRASES_TABLE = os.environ.get("PHRASES_TABLE", "KeystrokePhrases")
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "KeystrokeAuditLog")
REGION = os.environ.get("AWS_REGION", "us-east-1")
USE_LOCAL = os.environ.get("USE_LOCAL_DB", "false").lower() == "true"

# ── In-memory stores for local dev ─────────────────────────────
_local_phrases: Dict[str, Dict[str, Any]] = {}
_local_audit: List[Dict[str, Any]] = []

_phrases_table = None
_audit_table = None


def _get_phrases_table():
    global _phrases_table
    if _phrases_table is None:
        import boto3
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        _phrases_table = dynamodb.Table(PHRASES_TABLE)
    return _phrases_table


def _get_audit_table():
    global _audit_table
    if _audit_table is None:
        import boto3
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        _audit_table = dynamodb.Table(AUDIT_TABLE)
    return _audit_table


def _to_dynamo(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dynamo(i) for i in obj]
    return obj


def _from_dynamo(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        if obj == int(obj):
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_dynamo(i) for i in obj]
    return obj


# ── Default Phrases (seed data) ───────────────────────────────
DEFAULT_PHRASES = [
    {"phrase_id": "phrase_1", "text": "password123", "category": "password-style", "order": 1, "max_attempts": 1},
    {"phrase_id": "phrase_2", "text": "admin123", "category": "password-style", "order": 2, "max_attempts": 1},
    {"phrase_id": "phrase_3", "text": "welcome123", "category": "password-style", "order": 3, "max_attempts": 1},
    {"phrase_id": "phrase_4", "text": "login2026", "category": "password-style", "order": 4, "max_attempts": 1},
    {"phrase_id": "phrase_5", "text": "secure@123", "category": "mixed-string", "order": 5, "max_attempts": 1},
]


# ── Phrase CRUD ────────────────────────────────────────────────

def create_phrase(
    text: str,
    category: str = "password-style",
    order: int = 99,
    max_attempts: int = 1,
    admin_user: str = "admin",
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    phrase_id = f"phrase_{uuid.uuid4().hex[:8]}"

    item = {
        "phrase_id": phrase_id,
        "text": text,
        "version": 1,
        "active": True,
        "category": category,
        "order": order,
        "max_attempts": max_attempts,
        "created_at": now,
        "updated_at": now,
    }

    if USE_LOCAL:
        _local_phrases[phrase_id] = deepcopy(item)
    else:
        _get_phrases_table().put_item(Item=_to_dynamo(item))

    _log_audit(admin_user, "CREATE", phrase_id, None, item)
    return item


def update_phrase(
    phrase_id: str,
    text: Optional[str] = None,
    category: Optional[str] = None,
    order: Optional[int] = None,
    max_attempts: Optional[int] = None,
    active: Optional[bool] = None,
    admin_user: str = "admin",
) -> Optional[Dict[str, Any]]:
    if USE_LOCAL:
        current = _local_phrases.get(phrase_id)
        if not current:
            return None
        current = deepcopy(current)
    else:
        response = _get_phrases_table().get_item(Key={"phrase_id": phrase_id})
        current = response.get("Item")
        if not current:
            return None
        current = _from_dynamo(current)

    old_snapshot = dict(current)
    now = datetime.now(timezone.utc).isoformat()

    if text is not None and text != current.get("text"):
        current["text"] = text
        current["version"] = current.get("version", 1) + 1

    if category is not None:
        current["category"] = category
    if order is not None:
        current["order"] = order
    if max_attempts is not None:
        current["max_attempts"] = max_attempts
    if active is not None:
        current["active"] = active

    current["updated_at"] = now

    if USE_LOCAL:
        _local_phrases[phrase_id] = deepcopy(current)
    else:
        _get_phrases_table().put_item(Item=_to_dynamo(current))

    _log_audit(admin_user, "UPDATE", phrase_id, old_snapshot, current)
    return current


def delete_phrase(phrase_id: str, admin_user: str = "admin") -> bool:
    result = update_phrase(phrase_id, active=False, admin_user=admin_user)
    if result:
        _log_audit(admin_user, "DELETE", phrase_id, None, {"active": False})
    return result is not None


def hard_delete_phrase(phrase_id: str, admin_user: str = "admin") -> bool:
    if USE_LOCAL:
        current = _local_phrases.pop(phrase_id, None)
        if not current:
            return False
        _log_audit(admin_user, "HARD_DELETE", phrase_id, current, None)
        return True

    table = _get_phrases_table()
    response = table.get_item(Key={"phrase_id": phrase_id})
    current = response.get("Item")
    if not current:
        return False
    table.delete_item(Key={"phrase_id": phrase_id})
    _log_audit(admin_user, "HARD_DELETE", phrase_id, _from_dynamo(current), None)
    return True


def get_phrase(phrase_id: str) -> Optional[Dict[str, Any]]:
    if USE_LOCAL:
        item = _local_phrases.get(phrase_id)
        return deepcopy(item) if item else None

    table = _get_phrases_table()
    response = table.get_item(Key={"phrase_id": phrase_id})
    item = response.get("Item")
    return _from_dynamo(item) if item else None


def get_all_phrases(include_inactive: bool = False) -> List[Dict[str, Any]]:
    if USE_LOCAL:
        items = list(deepcopy(v) for v in _local_phrases.values())
    else:
        table = _get_phrases_table()
        response = table.scan()
        items = [_from_dynamo(i) for i in response.get("Items", [])]

    if not include_inactive:
        items = [i for i in items if i.get("active", True)]

    items.sort(key=lambda x: x.get("order", 99))
    return items


def get_active_phrases() -> List[Dict[str, Any]]:
    phrases = get_all_phrases(include_inactive=False)
    return [
        {
            "phrase_id": p["phrase_id"],
            "text": p["text"],
            "version": p.get("version", 1),
            "order": p.get("order", 99),
            "max_attempts": p.get("max_attempts", 1),
            "category": p.get("category", ""),
        }
        for p in phrases
    ]


def seed_default_phrases() -> int:
    existing = get_all_phrases(include_inactive=True)
    if existing:
        return 0

    count = 0
    for p in DEFAULT_PHRASES:
        now = datetime.now(timezone.utc).isoformat()
        item = {
            "phrase_id": p["phrase_id"],
            "text": p["text"],
            "version": 1,
            "active": True,
            "category": p["category"],
            "order": p["order"],
            "max_attempts": p["max_attempts"],
            "created_at": now,
            "updated_at": now,
        }

        if USE_LOCAL:
            _local_phrases[p["phrase_id"]] = deepcopy(item)
        else:
            _get_phrases_table().put_item(Item=_to_dynamo(item))

        count += 1

    return count


# ── Audit Logging ──────────────────────────────────────────────

def _log_audit(
    admin_user: str,
    action: str,
    phrase_id: str,
    old_value: Optional[Dict],
    new_value: Optional[Dict],
) -> None:
    try:
        now = datetime.now(timezone.utc).isoformat()
        log_id = f"{now}#{uuid.uuid4().hex[:8]}"

        item = {
            "log_id": log_id,
            "phrase_id": phrase_id,
            "action": action,
            "admin_user": admin_user,
            "timestamp": now,
        }
        if old_value:
            item["old_value"] = old_value
        if new_value:
            item["new_value"] = new_value

        if USE_LOCAL:
            _local_audit.append(deepcopy(item))
        else:
            if old_value:
                item["old_value"] = _to_dynamo(old_value)
            if new_value:
                item["new_value"] = _to_dynamo(new_value)
            _get_audit_table().put_item(Item=item)
    except Exception as e:
        print(f"Audit log error: {e}")


def get_audit_logs(phrase_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    if USE_LOCAL:
        items = deepcopy(_local_audit)
        if phrase_id:
            items = [i for i in items if i.get("phrase_id") == phrase_id]
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return items[:limit]

    from boto3.dynamodb.conditions import Key
    table = _get_audit_table()

    if phrase_id:
        response = table.query(
            IndexName="PhraseAuditIndex",
            KeyConditionExpression=Key("phrase_id").eq(phrase_id),
            Limit=limit,
            ScanIndexForward=False,
        )
    else:
        response = table.scan(Limit=limit)

    items = [_from_dynamo(i) for i in response.get("Items", [])]
    items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return items[:limit]
