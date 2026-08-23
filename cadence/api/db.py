"""
DynamoDB helpers for storing and retrieving keystroke session data.
Supports LOCAL_MODE (in-memory dict) when USE_LOCAL_DB=true.
"""

import os
import json
from typing import Dict, Any, List, Optional
from decimal import Decimal
from copy import deepcopy

# ── Configuration ──────────────────────────────────────────────
TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "KeystrokeSessions")
REGION = os.environ.get("AWS_REGION", "us-east-1")
USE_LOCAL = os.environ.get("USE_LOCAL_DB", "false").lower() == "true"

# ── In-memory store for local dev ──────────────────────────────
_local_store: List[Dict[str, Any]] = []

# Lazy-initialised DynamoDB resource
_table = None


def _get_table():
    global _table
    if _table is None:
        import boto3
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        _table = dynamodb.Table(TABLE_NAME)
    return _table


# ── Helpers ────────────────────────────────────────────────────
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


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


# ── CRUD ───────────────────────────────────────────────────────
def store_session(
    username: str,
    session_id: str,
    attempt_number: int,
    phrase_id: str,
    timestamp: str,
    features: Dict[str, Any],
    phrase_version: int = 1,
    backspace_count: int = 0,
    paste_detected: bool = False,
    raw_event_count: int = 0,
) -> None:
    """Write a single attempt record."""
    sort_key = f"{session_id}#{attempt_number}#{phrase_id}"

    item = {
        "username": username,
        "sort_key": sort_key,
        "session_id": session_id,
        "attempt_number": attempt_number,
        "phrase_id": phrase_id,
        "phrase_version": phrase_version,
        "timestamp": timestamp,
        "features": features,
        "backspace_count": backspace_count,
        "paste_detected": paste_detected,
        "raw_event_count": raw_event_count,
    }

    if USE_LOCAL:
        _local_store.append(deepcopy(item))
    else:
        item["features"] = _to_dynamo(features)
        _get_table().put_item(Item=item)


def get_all_sessions(limit: int = 500) -> List[Dict[str, Any]]:
    if USE_LOCAL:
        return deepcopy(_local_store[:limit])

    table = _get_table()
    items = []
    params: Dict[str, Any] = {"Limit": limit}
    response = table.scan(**params)
    items.extend(response.get("Items", []))

    while "LastEvaluatedKey" in response and len(items) < limit:
        params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        response = table.scan(**params)
        items.extend(response.get("Items", []))

    result = [_from_dynamo(item) for item in items]
    result.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return result


def get_sessions_by_username(username: str) -> List[Dict[str, Any]]:
    if USE_LOCAL:
        return [deepcopy(i) for i in _local_store if i["username"] == username]

    table = _get_table()
    from boto3.dynamodb.conditions import Key
    response = table.query(KeyConditionExpression=Key("username").eq(username))
    return [_from_dynamo(item) for item in response.get("Items", [])]


def get_sessions_by_session_id(session_id: str) -> List[Dict[str, Any]]:
    if USE_LOCAL:
        return [deepcopy(i) for i in _local_store if i["session_id"] == session_id]

    table = _get_table()
    from boto3.dynamodb.conditions import Key
    response = table.query(
        IndexName="SessionIndex",
        KeyConditionExpression=Key("session_id").eq(session_id),
    )
    return [_from_dynamo(item) for item in response.get("Items", [])]


def get_session_detail(username: str, sort_key: str) -> Optional[Dict[str, Any]]:
    if USE_LOCAL:
        for i in _local_store:
            if i["username"] == username and i["sort_key"] == sort_key:
                return deepcopy(i)
        return None

    table = _get_table()
    response = table.get_item(Key={"username": username, "sort_key": sort_key})
    item = response.get("Item")
    return _from_dynamo(item) if item else None


def get_dashboard_stats() -> Dict[str, Any]:
    all_items = get_all_sessions(limit=5000)

    usernames = set()
    session_ids = set()
    total_attempts = 0

    for item in all_items:
        usernames.add(item.get("username", ""))
        session_ids.add(item.get("session_id", ""))
        total_attempts += 1

    sorted_items = sorted(all_items, key=lambda x: x.get("timestamp", ""), reverse=True)
    latest = sorted_items[:10]

    return {
        "total_users": len(usernames),
        "total_sessions": len(session_ids),
        "total_attempts": total_attempts,
        "latest_submissions": latest,
    }


def query_sessions(
    username: Optional[str] = None,
    session_id: Optional[str] = None,
    phrase_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if username:
        items = get_sessions_by_username(username)
    elif session_id:
        items = get_sessions_by_session_id(session_id)
    else:
        items = get_all_sessions()

    if phrase_id:
        items = [i for i in items if i.get("phrase_id") == phrase_id]
    if date_from:
        items = [i for i in items if i.get("timestamp", "") >= date_from]
    if date_to:
        items = [i for i in items if i.get("timestamp", "") <= date_to]

    items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return items
