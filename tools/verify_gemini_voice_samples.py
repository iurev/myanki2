#!/usr/bin/env python3
import base64
import json
import os
import re
import unicodedata
import time
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "tesouro" / "gemini-voice-samples"


def normalize(text: str) -> str:
    text = "".join(char for char in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(char) != "Mn")
    return " ".join(re.sub(r"[^a-z]+", " ", text).split())


def main() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    expected = normalize(manifest["text"])
    results = []
    output = ROOT / "stt-whisper"
    output.mkdir(exist_ok=True)
    for sample in manifest["samples"]:
        audio = ROOT / sample["file"]
        saved = output / f"{sample['voice']}.json"
        if saved.is_file():
            response = json.loads(saved.read_text())
        else:
            body = {
                "model": "openai/whisper-large-v3",
                "input_audio": {"data": base64.b64encode(audio.read_bytes()).decode(), "format": "mp3"},
                "language": "en",
                "response_format": "verbose_json",
                "timestamp_granularities": ["word", "segment"],
                "temperature": 0,
            }
            request = urllib.request.Request(
                "https://openrouter.ai/api/v1/audio/transcriptions",
                data=json.dumps(body).encode(),
                headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"},
            )
            for attempt in range(4):
                try:
                    response = json.load(urllib.request.urlopen(request, timeout=60))
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(2**attempt)
            saved.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
        heard = normalize(response["text"])
        ratio = SequenceMatcher(None, expected, heard, autojunk=False).ratio()
        row = {"voice": sample["voice"], "heard": response["text"].strip(), "similarity": round(ratio, 3), "status": "PASS" if ratio >= 0.9 else "FAIL"}
        results.append(row)
        print(json.dumps(row, ensure_ascii=False))
    (ROOT / "verification.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    if any(row["status"] == "FAIL" for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
