"""
CSV export utilities for admin data download.
Now includes phrase version and optional masked phrase text.
"""

import csv
import io
from typing import List, Dict, Any, Optional


def _flatten_features(features: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Recursively flatten nested feature dicts into dot-notation keys."""
    flat: Dict[str, Any] = {}
    for key, value in features.items():
        full_key = f"{prefix}{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten_features(value, f"{full_key}."))
        elif isinstance(value, list):
            flat[full_key] = ";".join(str(v) for v in value)
        else:
            flat[full_key] = value
    return flat


def _mask_phrase(text: str) -> str:
    """Mask a phrase for CSV export — show first 2 and last 2 chars."""
    if len(text) <= 4:
        return text
    return text[:2] + "*" * (len(text) - 4) + text[-2:]


def build_csv(
    records: List[Dict[str, Any]],
    phrase_lookup: Optional[Dict[str, str]] = None,
) -> str:
    """
    Convert a list of DynamoDB session records into a CSV string.

    Args:
        records: list of session records from DynamoDB
        phrase_lookup: optional dict mapping phrase_id -> phrase_text
    """
    if not records:
        return ""

    base_columns = [
        "username", "session_id", "attempt_number",
        "phrase_id", "phrase_version", "phrase_text_masked",
    ]
    feature_columns: set = set()

    rows: List[Dict[str, Any]] = []
    for record in records:
        row: Dict[str, Any] = {}
        for col in ["username", "session_id", "attempt_number", "phrase_id"]:
            row[col] = record.get(col, "")

        # Phrase version
        row["phrase_version"] = record.get("phrase_version", 1)

        # Phrase text (masked)
        pid = record.get("phrase_id", "")
        if phrase_lookup and pid in phrase_lookup:
            row["phrase_text_masked"] = _mask_phrase(phrase_lookup[pid])
        else:
            row["phrase_text_masked"] = ""

        row["timestamp"] = record.get("timestamp", "")

        # Flatten features
        features = record.get("features", {})
        flat = _flatten_features(features)
        feature_columns.update(flat.keys())
        row.update(flat)

        # Extra metadata
        row["backspace_count"] = record.get("backspace_count", 0)
        row["paste_detected"] = record.get("paste_detected", False)

        rows.append(row)

    sorted_feat_cols = sorted(feature_columns)
    all_columns = base_columns + ["timestamp", "backspace_count", "paste_detected"] + sorted_feat_cols

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=all_columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    return output.getvalue()
