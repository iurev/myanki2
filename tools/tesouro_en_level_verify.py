#!/usr/bin/env python3
"""Verify the re-levelled English clips before they go anywhere.

Reads the clips that will be uploaded and checks them against the pristine
Gemini takes: how loud each one now is, that its length is unchanged, that no
clip is pushed towards full scale, and that the speech still transcribes to the
same words. Reports the spread of levels before and after, since the point of
the exercise was to make every card sit at the same loudness.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / "tesouro" / "full-book-local"
SHIPPED = LOCAL / "audio-en"
ORIGINAL = LOCAL / "audio-en-original"
INVENTORY = LOCAL / "text-inventory.json"

sys.path.insert(0, str(ROOT / "tools"))
from tesouro_en_gain import measure, pristine_source  # noqa: E402
from tesouro_en_verify_api import normalize, transcribe  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asr", type=int, default=20, help="how many clips to transcribe again")
    parser.add_argument("--target-lufs", type=float, default=-26.3)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    records = json.loads(INVENTORY.read_text())
    problems: list[str] = []

    def check(record: dict) -> dict:
        sid = record["id"]
        shipped, pristine = SHIPPED / f"{sid}.mp3", pristine_source(sid)
        if not shipped.is_file():
            problems.append(f"{sid}: not rendered")
            return {}
        after, before = measure(shipped), measure(pristine)
        return {"id": sid, "lufs_before": before["lufs"], "lufs_after": after["lufs"],
                "true_peak": after["true_peak"],
                "duration_delta": round(after["duration"] - before["duration"], 3)}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = [row for row in pool.map(check, records) if row]

    for row in rows:
        if abs(row["duration_delta"]) > 0.05:
            problems.append(f"{row['id']}: length changed by {row['duration_delta']} s")
        if row["true_peak"] > -1.0:
            problems.append(f"{row['id']}: true peak {row['true_peak']:.2f} dBTP")
        if abs(row["lufs_after"] - args.target_lufs) > 1.0:
            problems.append(f"{row['id']}: {row['lufs_after']:.2f} LUFS is far from target")

    # The point of the pass: one level for the whole deck instead of a spread.
    lufs = [row["lufs_after"] for row in rows]
    before = [row["lufs_before"] for row in rows]
    summary = {
        "clips": len(rows),
        "loudness_before": {"median": round(statistics.median(before), 2),
                            "min": round(min(before), 2), "max": round(max(before), 2),
                            "spread": round(max(before) - min(before), 2)},
        "loudness_after": {"median": round(statistics.median(lufs), 2),
                           "min": round(min(lufs), 2), "max": round(max(lufs), 2),
                           "spread": round(max(lufs) - min(lufs), 2)},
        "loudest_after": max(lufs), "quietest_after": min(lufs),
        "max_duration_delta": max(abs(row["duration_delta"]) for row in rows),
        "max_true_peak": round(max(row["true_peak"] for row in rows), 2),
    }

    # A level change must not change the words.
    sample = [record["id"] for record in records[:: max(1, len(records) // args.asr)]][: args.asr]
    speech_dir = LOCAL / "stt-en-level"
    speech_dir.mkdir(parents=True, exist_ok=True)

    def respoken(sid: str) -> tuple[str, float]:
        fresh = normalize(transcribe(SHIPPED / f"{sid}.mp3", speech_dir / f"{sid}.json",
                                     "openai/whisper-large-v3").get("text", ""))
        cached = json.loads((LOCAL / "stt-en-unprompted" / f"{sid}.json").read_text())
        earlier = normalize(cached.get("text", ""))
        if not fresh or not earlier:
            return sid, 0.0
        overlap = len(set(fresh) & set(earlier)) / max(1, len(set(earlier)))
        return sid, overlap

    with ThreadPoolExecutor(max_workers=4) as pool:
        speech = list(pool.map(respoken, sample))
    worst = min(speech, key=lambda pair: pair[1])
    summary["speech_check"] = {"clips": len(speech), "worst_id": worst[0],
                               "worst_word_overlap": round(worst[1], 3),
                               "min_overlap": round(min(o for _, o in speech), 3)}
    for sid, overlap in speech:
        if overlap < 0.8:
            problems.append(f"{sid}: words changed, only {overlap:.2f} of the earlier words heard")

    summary["problems"] = problems
    summary["problem_count"] = len(problems)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
