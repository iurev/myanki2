#!/usr/bin/env python3
"""Re-record English clips whose audio does not say its sentence.

The expressive TTS model sometimes performs a line instead of reading it: for
"David laughs." it laughed, and the transcript came back as "Ha ha ha ha.".
Nothing about the text is wrong, so the retake loop asks the model again and
keeps a take only when both providers transcribe the sentence that was asked
for. Every attempt's transcript is printed, so an accepted take is evidence and
not a silent retry.

The accepted take is written both as the shipped clip and as the pristine copy
the gain tool levels from.

    python3 tools/cidadela_en_retake.py --id cm0209
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tesouro_en_tts_api import synthesize  # noqa: E402 - tested request shape, reused
from tesouro_en_verify_api import fuzzy_fraction, normalize  # noqa: E402 - same word comparison as the verifier

INVENTORY = ROOT / "cidadela" / "work" / "text-inventory.json"
SHIPPED = ROOT / "cidadela" / "audio-en"
PRISTINE = ROOT / "cidadela" / "audio-en-original"
STATE = ROOT / "cidadela" / "english-tts-state.json"
PROVIDERS = (("whisper", "openai/whisper-large-v3"), ("chirp", "google/chirp-3"))
MAX_ATTEMPTS = 8


def transcribe(audio: Path, model: str) -> str:
    body = {"model": model, "input_audio": {"data": base64.b64encode(audio.read_bytes()).decode(), "format": "mp3"},
            "language": "en"}
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/audio/transcriptions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request, timeout=180)).get("text", "").strip()


def says_the_sentence(heard: str, expected: list[str]) -> tuple[bool, dict]:
    """Does this take read the sentence, rather than act it out?

    The bar is the verifier's: at least 85% of the expected words, in order,
    recognisably present. A laugh contains none of "david laughs" and cannot
    pass it.
    """
    words = normalize(heard)
    fuzzy = fuzzy_fraction(expected, words)
    return fuzzy >= 0.85, {"heard": heard, "fuzzy": round(fuzzy, 3), "words": words}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", action="append", required=True, dest="ids")
    parser.add_argument("--attempts", type=int, default=MAX_ATTEMPTS)
    args = parser.parse_args()

    records = {row["id"]: row for row in json.loads(INVENTORY.read_text())}
    state = json.loads(STATE.read_text()) if STATE.is_file() else {}
    PRISTINE.mkdir(parents=True, exist_ok=True)
    report = []
    for sid in args.ids:
        record = records[sid]
        expected = normalize(record["english_text"])
        entry = {"id": sid, "english_text": record["english_text"], "attempts": []}
        for attempt in range(1, args.attempts + 1):
            pcm, content_type, generation_id = synthesize(record["english_text"])
            rate = re.search(r"rate=(\d+)", content_type)
            channels = re.search(r"channels=(\d+)", content_type)
            if not rate or not channels:
                raise RuntimeError(f"{sid}: unexpected content type {content_type!r}")
            with tempfile.TemporaryDirectory() as temporary:
                pcm_path = Path(temporary) / "take.pcm"
                pcm_path.write_bytes(pcm)
                mp3 = Path(temporary) / "take.mp3"
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", rate.group(1),
                                "-ac", channels.group(1), "-i", str(pcm_path), "-codec:a", "libmp3lame",
                                "-qscale:a", "2", str(mp3)], check=True)
                readings = {name: says_the_sentence(transcribe(mp3, model), expected) for name, model in PROVIDERS}
                duration = float(subprocess.check_output(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)],
                    text=True).strip())
                accepted = all(ok for ok, _ in readings.values())
                entry["attempts"].append({"take": attempt, "generation_id": generation_id,
                                          "duration": round(duration, 3),
                                          **{name: notes for name, (_, notes) in readings.items()},
                                          "accepted": accepted})
                print(json.dumps({"id": sid, "take": attempt, "duration": round(duration, 3),
                                  **{name: notes["heard"] for name, (_, notes) in readings.items()},
                                  "accepted": accepted}, ensure_ascii=False), flush=True)
                if accepted:
                    SHIPPED.mkdir(parents=True, exist_ok=True)
                    (SHIPPED / f"{sid}.mp3").write_bytes(mp3.read_bytes())
                    (PRISTINE / f"{sid}.mp3").write_bytes(mp3.read_bytes())
                    state[sid] = {"chapter": record["chapter"], "english_text": record["english_text"],
                                  "model": "google/gemini-3.8-flash-tts", "voice": "Algieba",
                                  "duration": round(duration, 3), "bytes": mp3.stat().st_size,
                                  "generation_id": generation_id, "retake": attempt}
                    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
                    entry["accepted_take"] = attempt
                    break
        else:
            raise SystemExit(f"{sid}: no take in {args.attempts} attempts said the sentence; see the transcripts above")
        report.append(entry)

    (ROOT / "cidadela" / "english-retakes.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"retaken": [entry["id"] for entry in report],
                      "takes": {entry["id"]: entry["accepted_take"] for entry in report}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
