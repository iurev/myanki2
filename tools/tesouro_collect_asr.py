#!/usr/bin/env python3
import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def request_transcription(audio: Path, model: str, verbose: bool) -> dict:
    body = {
        "model": model,
        "input_audio": {"data": base64.b64encode(audio.read_bytes()).decode(), "format": "mp3"},
        "language": "pt",
    }
    if verbose:
        body.update({"response_format": "verbose_json", "timestamp_granularities": ["word", "segment"], "temperature": 0})
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/audio/transcriptions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"},
    )
    for attempt in range(6):
        try:
            return json.load(urllib.request.urlopen(request, timeout=60))
        except urllib.error.HTTPError as error:
            if attempt == 5:
                raise
            time.sleep(5 * (attempt + 1) if error.code == 429 else 2 ** attempt)
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("--deepgram-ids", default="")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    manifest = json.loads((args.package / "manifest.json").read_text())
    providers = [
        ("stt-unprompted", "openai/whisper-large-v3", True),
        ("stt-chirp", "google/chirp-3", False),
    ]
    deepgram_ids = set(filter(None, args.deepgram_ids.split(",")))
    if deepgram_ids:
        providers.append(("stt-deepgram", "deepgram/nova-3", True))
    for directory, model, verbose in providers:
        output = args.package / directory
        output.mkdir(exist_ok=True)

        def run(item: dict) -> None:
            saved = output / f"{item['id']}.json"
            if saved.is_file():
                return
            result = request_transcription(args.package / f"{item['id']}.mp3", model, verbose)
            saved.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(model, item["id"], result.get("text", ""), flush=True)

        pending = [item for item in manifest
                   if not (model == "deepgram/nova-3" and item["id"] not in deepgram_ids)]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(run, pending))


if __name__ == "__main__":
    main()
