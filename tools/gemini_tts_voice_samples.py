#!/usr/bin/env python3
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

MODEL = "google/gemini-3.8-flash-tts"
TEXT = "That’s why you, João, can’t leave here either,” says the woman."
VOICES = ["Kore", "Aoede", "Leda", "Sulafat", "Zephyr", "Puck", "Charon", "Orus", "Achernar", "Gacrux"]
OUTPUT = Path(__file__).resolve().parent.parent / "tesouro" / "gemini-voice-samples"


def generate(voice: str) -> dict:
    body = {"model": MODEL, "input": TEXT, "voice": voice, "response_format": "pcm"}
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/audio/speech",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                pcm = response.read()
                content_type = response.headers.get("Content-Type", "")
                generation_id = response.headers.get("X-Generation-Id")
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2**attempt)
    rate_match = re.search(r"rate=(\d+)", content_type)
    channels_match = re.search(r"channels=(\d+)", content_type)
    if not rate_match or not channels_match:
        raise RuntimeError(f"unexpected content type: {content_type}")
    pcm_path = OUTPUT / f".{voice}.pcm"
    mp3_path = OUTPUT / f"ts0303-{voice}.mp3"
    pcm_path.write_bytes(pcm)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", rate_match.group(1),
        "-ac", channels_match.group(1), "-i", str(pcm_path), "-codec:a", "libmp3lame", "-qscale:a", "2", str(mp3_path),
    ], check=True)
    pcm_path.unlink()
    duration = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3_path),
    ], text=True))
    return {"voice": voice, "file": mp3_path.name, "duration": round(duration, 3), "bytes": mp3_path.stat().st_size, "generation_id": generation_id}


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = []
    for voice in VOICES:
        result = generate(voice)
        results.append(result)
        print(json.dumps(result))
    (OUTPUT / "manifest.json").write_text(json.dumps({"model": MODEL, "text": TEXT, "samples": results}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
