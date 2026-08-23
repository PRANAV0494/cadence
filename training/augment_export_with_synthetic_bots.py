"""
Idempotently augment keystroke_export_20260513.csv with:
  - session_label: human | bot_synthetic | bot_real (add bot_real rows manually later)
  - bot_profile: constant_delay | fast_burst | random_delay_band | paste_heavy | (empty for humans)

Removes previous synthetic_bot_* rows on each run, then re-appends fresh multi-profile bots.
Preserves rows labeled bot_real.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from synthetic_bot_profiles import FEATURE_COLUMNS, PROFILE_NAMES, features_for_profile

CSV_PATH = Path(__file__).resolve().parent / "keystroke_export_20260513.csv"
ROWS_PER_PROFILE = 75  # 4 * 75 = 300 synthetic bots


def main() -> None:
    rng = np.random.default_rng(42)
    df = pd.read_csv(CSV_PATH, low_memory=False)

    real_mask = (
        df.get("session_label", pd.Series("", index=df.index))
        .astype(str)
        .str.strip()
        .str.lower()
        .eq("bot_real")
    )
    df_real = df.loc[real_mask].copy()

    name = df.get("username", pd.Series("", index=df.index)).astype(str)
    synth_user_mask = name.str.startswith("synthetic_bot_")
    df = df.loc[~synth_user_mask & ~real_mask].copy()

    if "session_label" not in df.columns:
        df["session_label"] = "human"
    df["session_label"] = df["session_label"].fillna("human").astype(str).str.strip()
    low = df["session_label"].str.lower()
    df.loc[low.isin(["", "nan"]), "session_label"] = "human"
    df.loc[low.eq("human"), "session_label"] = "human"

    if "bot_profile" not in df.columns:
        df["bot_profile"] = np.nan
    if "dataset_note" not in df.columns:
        df["dataset_note"] = np.nan
    df["dataset_note"] = df["dataset_note"].astype("object")

    df.loc[df["session_label"].str.lower().eq("human"), "dataset_note"] = (
        "Real human capture from keystroke collection app."
    )

    X_h = df[FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")

    synth_frames: list[dict] = []
    for prof in PROFILE_NAMES:
        feats = features_for_profile(prof, ROWS_PER_PROFILE, X_h, rng)
        for i in range(len(feats)):
            row = {c: np.nan for c in df.columns}
            row.update(feats.iloc[i].to_dict())
            row["username"] = f"synthetic_bot_{prof}_{i:03d}"
            row["session_id"] = str(uuid.uuid4())
            row["attempt_number"] = 1
            row["phrase_id"] = f"synth_{prof}"
            row["phrase_version"] = 1
            row["phrase_text_masked"] = "SYN****TH"
            row["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            row["backspace_count"] = 0
            row["paste_detected"] = prof == "paste_heavy"
            row["session_label"] = "bot_synthetic"
            row["bot_profile"] = prof
            row["dataset_note"] = (
                "Synthetic multi-profile bot-like timing for ML experiments only; "
                "not validated against real automation. Append rows with session_label=bot_real for credibility."
            )
            synth_frames.append(row)

    synth_df = pd.DataFrame(synth_frames, columns=df.columns)
    out = pd.concat([df, df_real, synth_df], axis=0, ignore_index=True)

    out.to_csv(CSV_PATH, index=False, encoding="utf-8")
    print("Wrote:", CSV_PATH)
    print("Humans:", (out["session_label"].str.lower() == "human").sum())
    print("bot_synthetic:", (out["session_label"].str.lower() == "bot_synthetic").sum())
    print("bot_real:", (out["session_label"].str.lower() == "bot_real").sum())
    print("bot_profile value counts (bots only):")
    m = out["session_label"].str.lower().isin(["bot_synthetic", "bot_real"])
    print(out.loc[m, "bot_profile"].value_counts(dropna=False))


if __name__ == "__main__":
    main()
