#!/usr/bin/env python3
"""Generate the English audio for every Tesouro card with Gemini Flash TTS.

The text sent to the model is the book's own embedded English translation,
passed through byte-for-byte: no rewriting, no stripping of parentheses,
quotes or any other symbol. Each clip is written separately so the Portuguese
and English audio stay as two independent files.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "google/gemini-3.8-flash-tts"
VOICE = "Algieba"
INVENTORY = ROOT / "tesouro" / "full-book-local" / "text-inventory.json"


def synthesize(text: str) -> tuple[bytes, str, str]:
    body = {"model": MODEL, "input": text, "voice": VOICE, "response_format": "pcm"}
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/audio/speech",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"},
    )
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return response.read(), response.headers.get("Content-Type", ""), response.headers.get("X-Generation-Id", "")
        except Exception as error:  # transient upstream failures are common on TTS
            last_error = error
            time.sleep(2 ** attempt)
    raise RuntimeError(f"TTS failed for {text[:40]!r}: {last_error}")


def generation_cost(generation_id: str) -> float | None:
    if not generation_id:
        return None
    request = urllib.request.Request(
        f"https://openrouter.ai/api/v1/generation?id={generation_id}",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
    )
    try:
        payload = json.load(urllib.request.urlopen(request, timeout=60)).get("data", {})
        return payload.get("total_cost")
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "tesouro" / "full-book-local" / "audio-en")
    parser.add_argument("--record", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    records = json.loads(INVENTORY.read_text())
    if args.record:
        wanted = set(args.record)
        records = [r for r in records if r["id"] in wanted]
    if args.limit:
        records = records[: args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    state_path = args.out.parent / "english-tts-state.json"
    state = json.loads(state_path.read_text()) if state_path.is_file() else {}

    state_lock = threading.Lock()
    counter = {"done": 0}

    def produce(record: dict) -> None:
        sid = record["id"]
        mp3 = args.out / f"{sid}.mp3"
        if mp3.is_file() and sid in state:
            return
        pcm, content_type, generation_id = synthesize(record["english_text"])
        rate = re.search(r"rate=(\d+)", content_type)
        channels = re.search(r"channels=(\d+)", content_type)
        if not rate or not channels:
            raise RuntimeError(f"{sid}: unexpected content type {content_type!r}")
        # Unique temp names: several workers write into the same directory.
        pcm_path = args.out / f".{sid}.{os.getpid()}.{threading.get_ident()}.pcm"
        pcm_path.write_bytes(pcm)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", rate.group(1),
             "-ac", channels.group(1), "-i", str(pcm_path), "-codec:a", "libmp3lame", "-qscale:a", "2", str(mp3)],
            check=True,
        )
        pcm_path.unlink()
        duration = float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)],
            text=True).strip())
        with state_lock:
            state[sid] = {
                "chapter": record["chapter"],
                "english_text": record["english_text"],
                "model": MODEL, "voice": VOICE,
                "duration": round(duration, 3), "bytes": mp3.stat().st_size,
                "generation_id": generation_id,
            }
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            counter["done"] += 1
            print(json.dumps({"id": sid, "duration": round(duration, 3), "done": counter["done"]}), flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(produce, records))


if __name__ == "__main__":
    main()
