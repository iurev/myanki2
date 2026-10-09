#!/usr/bin/env python3
"""Generate the English audio for the A Cidadela Misteriosa cards.

The text sent to the model is the book's own embedded English translation,
passed through byte-for-byte: no rewriting, no stripping of parentheses, quotes
or any other symbol. The translator's parenthetical glosses are read out as
ordinary text, as asked. Each clip is written separately so the Portuguese and
English audio stay two independent files.

The request shape, the voice and the PCM-to-MP3 step come from the Tesouro TTS
tool, which is the tested implementation of all three; only the paths and the
inventory are this book's.

    python3 tools/cidadela_en_tts.py --limit 3     # try a few first
    python3 tools/cidadela_en_tts.py               # the rest
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tesouro_en_tts_api import MODEL, VOICE, synthesize  # noqa: E402 - tested request shape, reused

INVENTORY = ROOT / "cidadela" / "work" / "text-inventory.json"
OUT = ROOT / "cidadela" / "audio-en"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--record", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    records = json.loads(INVENTORY.read_text())
    if args.record:
        wanted = set(args.record)
        records = [row for row in records if row["id"] in wanted]
    if args.limit:
        records = records[: args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    state_path = args.out.parent / "english-tts-state.json"
    state = json.loads(state_path.read_text()) if state_path.is_file() else {}
    lock = threading.Lock()
    counter = {"done": 0, "skipped": 0}

    def produce(record: dict) -> None:
        sid = record["id"]
        mp3 = args.out / f"{sid}.mp3"
        if mp3.is_file() and sid in state and state[sid]["english_text"] == record["english_text"]:
            with lock:
                counter["skipped"] += 1
            return
        pcm, content_type, generation_id = synthesize(record["english_text"])
        rate = re.search(r"rate=(\d+)", content_type)
        channels = re.search(r"channels=(\d+)", content_type)
        if not rate or not channels:
            raise RuntimeError(f"{sid}: unexpected content type {content_type!r}")
        pcm_path = args.out / f".{sid}.{os.getpid()}.{threading.get_ident()}.pcm"
        pcm_path.write_bytes(pcm)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", rate.group(1),
             "-ac", channels.group(1), "-i", str(pcm_path), "-codec:a", "libmp3lame", "-qscale:a", "2", str(mp3)],
            check=True)
        pcm_path.unlink()
        duration = float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)],
            text=True).strip())
        with lock:
            state[sid] = {"chapter": record["chapter"], "english_text": record["english_text"],
                          "model": MODEL, "voice": VOICE, "duration": round(duration, 3),
                          "bytes": mp3.stat().st_size, "generation_id": generation_id}
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            counter["done"] += 1
            print(json.dumps({"id": sid, "duration": round(duration, 3), "done": counter["done"]}), flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(produce, records))
    print(json.dumps({"generated": counter["done"], "reused": counter["skipped"], "total": len(records)}))


if __name__ == "__main__":
    main()
