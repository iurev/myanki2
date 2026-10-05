#!/usr/bin/env python3
"""Set the level of every English clip, per clip, by measured loudness.

The pristine Gemini output is kept in `audio-en-original/`; each level change is
rendered from that copy, so corrections cannot stack and any level can be redone
from scratch. Loudness is measured with ffmpeg's EBU R128 meter (LUFS) rather
than peak or RMS, because a clip's silence does not count towards it: two clips
of the same speech can differ by several dB of RMS just from the length of the
pause around them.

Nothing is uploaded until every clip has been rendered and re-measured; the run
aborts rather than shipping a clip whose level it could not confirm.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import statistics
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / "tesouro" / "full-book-local"
ORIGINAL = LOCAL / "audio-en-original"
SHIPPED = LOCAL / "audio-en"
STATE = LOCAL / "english-gain.json"
INVENTORY = LOCAL / "text-inventory.json"
LUFS_TOLERANCE = 0.3
# The same gain carried through PCM is exact to three decimals; encoding the
# result to MP3 moves the measured RMS by up to about 0.1 dB. Anything under
# that is the encoder, not the gain applied.
APPLIED_GAIN_TOLERANCE = 0.15


def invoke(action: str, **params):
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request("http://127.0.0.1:56666", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = json.loads(response.read())
    if payload.get("error"):
        raise RuntimeError(f"{action}: {payload['error']}")
    return payload["result"]


def pristine_source(sid: str) -> Path:
    """The untouched Gemini output for a clip.

    Only clips that have been re-levelled have a copy in `audio-en-original/`;
    for every other clip the shipped file is still pristine.
    """
    kept = ORIGINAL / f"{sid}.mp3"
    return kept if kept.is_file() else SHIPPED / f"{sid}.mp3"


def keep_pristine(path: Path) -> Path:
    """Park the untouched take in `audio-en-original/` before it is overwritten."""
    kept = ORIGINAL / path.name
    if not kept.is_file() and path.parent != ORIGINAL:
        kept.write_bytes(path.read_bytes())
    return kept if kept.is_file() else path


def rms_db(path: Path) -> float:
    """Overall RMS level. Unlike LUFS this is exactly linear, so it can prove
    that a render applied the gain it was asked to apply. astats is used over
    volumedetect because it reports more than one decimal place."""
    output = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "astats=metadata=0:reset=0",
         "-f", "null", "-"],
        capture_output=True, text=True, check=True).stderr
    for line in output.splitlines():
        if "RMS level dB" in line:
            return float(line.split("RMS level dB:")[1].strip())
    raise RuntimeError(f"no RMS measurement for {path}")


def measure(path: Path) -> dict:
    """Loudness, true peak and duration of a clip."""
    output = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, check=True).stderr
    match = re.search(r'\{[^{}]*"input_i"[^{}]*\}', output, re.S)
    if not match:
        raise RuntimeError(f"no loudness measurement for {path}")
    reading = json.loads(match.group(0))
    if reading.get("input_i") in (None, "-inf"):
        raise RuntimeError(f"silent clip: {path}")
    duration = float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        text=True).strip())
    return {"lufs": float(reading["input_i"]), "true_peak": float(reading["input_tp"]),
            "duration": round(duration, 3)}


def render(source: Path, target: Path, gain: float) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source),
                    "-af", f"volume={gain}", "-codec:a", "libmp3lame", "-qscale:a", "0", str(target)], check=True)


def normalize(record: dict, target: float) -> dict:
    """Level one clip to the target loudness, in a single render.

    The gain comes from one measurement of the pristine take. Integrated LUFS is
    not stable enough on one- to two-second clips to iterate on: a clipped
    sentence has only a handful of gating blocks, and scaling it can flip which
    of them the relative gate keeps, so the reading does not move with the gain.
    The render itself is measured back instead: RMS is exactly linear, so the
    RMS difference proves the gain landed, and the loudness reading is reported
    for the record rather than chased.
    """
    sid = record["id"]
    pristine = keep_pristine(pristine_source(sid))
    target_path = SHIPPED / f"{sid}.mp3"
    before = measure(pristine)
    gain = 10 ** ((target - before["lufs"]) / 20)
    render(pristine, target_path, gain)
    after = measure(target_path)
    applied_db = rms_db(target_path) - rms_db(pristine)
    expected_db = 20 * __import__("math").log10(gain)
    drift = after["lufs"] - target
    problem = None
    if abs(applied_db - expected_db) > APPLIED_GAIN_TOLERANCE:
        problem = f"{sid}: render applied {applied_db:+.2f} dB, asked for {expected_db:+.2f} dB"
    elif abs(after["duration"] - before["duration"]) > 0.05:
        problem = f"{sid}: duration changed {before['duration']} -> {after['duration']}"
    elif after["true_peak"] > -1.0:
        problem = f"{sid}: true peak {after['true_peak']:.2f} dBTP is too close to full scale"
    elif abs(drift) > 1.0:
        problem = f"{sid}: landed at {after['lufs']:.2f} LUFS, {drift:+.2f} from target"
    return {"id": sid, "gain": round(gain, 6), "applied_db": round(applied_db, 2),
            "lufs_before": round(before["lufs"], 2), "lufs_after": round(after["lufs"], 2),
            "drift": round(drift, 2), "true_peak": round(after["true_peak"], 2),
            "duration": after["duration"], "problem": problem}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", default="", help="comma separated card ids; default is the whole book")
    parser.add_argument("--gain", type=float, default=None, help="flat linear gain; 0.7 is 30%% quieter")
    parser.add_argument("--db", type=float, default=None, help="flat level change in dB; overrides --gain")
    parser.add_argument("--target-lufs", type=float, default=None, help="level each clip to this loudness")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--upload", action="store_true", help="push the rendered clips to Anki")
    parser.add_argument("--upload-only", action="store_true", help="push the files already on disk, without rendering")
    args = parser.parse_args()

    records = json.loads(INVENTORY.read_text())
    if args.ids:
        wanted = set(filter(None, args.ids.split(",")))
        records = [r for r in records if r["id"] in wanted]
    if args.upload_only:
        uploaded = []
        for record in records:
            path = SHIPPED / f"{record['id']}.mp3"
            invoke("storeMediaFile", filename=f"tesouro_en_{record['id']}.mp3",
                   data=base64.b64encode(path.read_bytes()).decode())
            uploaded.append(record["id"])
        print(json.dumps({"uploaded": len(uploaded), "first": uploaded[:3], "last": uploaded[-3:]}))
        return
    ORIGINAL.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.is_file() else {}

    if args.target_lufs is not None:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            report = list(pool.map(lambda record: normalize(record, args.target_lufs), records))
    else:
        gain = args.gain if args.gain is not None else 0.7
        if args.db is not None:
            gain = 10 ** (args.db / 20)

        def flat(record: dict) -> dict:
            sid = record["id"]
            pristine = keep_pristine(pristine_source(sid))
            target_path = SHIPPED / f"{sid}.mp3"
            before = measure(pristine)
            render(pristine, target_path, gain)
            after = measure(target_path)
            drift = after["lufs"] - (before["lufs"] + 20 * __import__("math").log10(gain))
            return {"id": sid, "gain": round(gain, 6), "lufs_before": round(before["lufs"], 2),
                    "lufs_after": round(after["lufs"], 2), "drift": round(drift, 2),
                    "true_peak": round(after["true_peak"], 2), "duration": after["duration"],
                    "problem": None if abs(drift) <= LUFS_TOLERANCE else f"{sid}: flat gain drifted {drift:+.2f} LU"}

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            report = list(pool.map(flat, records))

    problems = [row["problem"] for row in report if row["problem"]]
    for row in report:
        state[row["id"]] = {"gain": row["gain"], "target_lufs": args.target_lufs,
                            "lufs_before": row["lufs_before"], "lufs_after": row["lufs_after"],
                            "true_peak": row["true_peak"], "source": "audio-en-original"}
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    levels = [row["lufs_after"] for row in report]
    drifts = [abs(row["drift"]) for row in report]
    print(json.dumps({
        "clips": len(report),
        "target_lufs": args.target_lufs,
        "lufs_after_median": round(statistics.median(levels), 2),
        "lufs_after_min": round(min(levels), 2),
        "lufs_after_max": round(max(levels), 2),
        "worst_drift": round(max(drifts), 2),
        "gain_median_db": round(20 * __import__("math").log10(statistics.median([row["gain"] for row in report])), 2),
        "problems": problems[:20],
        "problem_count": len(problems),
    }, ensure_ascii=False, indent=2))
    if problems:
        raise SystemExit(1)

    if args.upload:
        for row in report:
            path = SHIPPED / f"{row['id']}.mp3"
            invoke("storeMediaFile", filename=f"tesouro_en_{row['id']}.mp3",
                   data=base64.b64encode(path.read_bytes()).decode())
        print(json.dumps({"uploaded": len(report)}))


if __name__ == "__main__":
    main()
