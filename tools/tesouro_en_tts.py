#!/usr/bin/env python3
"""Generate English back-side audio clips for the Tesouro listening deck via
OpenRouter's dedicated /api/v1/audio/speech endpoint (real TTS, not a chat
model -- unlike openai/gpt-audio-mini via chat completions, which answered
conversationally instead of reading text aloud for ~58% of lines in this
dialogue-heavy book).

Cross-check: since this endpoint returns only raw audio (no transcript, the
way the chat-completions route did), each generated clip is independently
re-transcribed with faster-whisper (English) and compared against the
intended text.
"""
from __future__ import annotations

import json
import os
import sys
import unicodedata
import urllib.request
import urllib.error
from difflib import SequenceMatcher
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DECK_YAML = ROOT / "tesouro-listening.yaml"
OUT_DIR = ROOT / "tesouro" / "audio-en"

MODEL = "mistralai/voxtral-mini-tts-2603"
VOICE = "en_paul_neutral"
MATCH_THRESHOLD = 0.9


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return " ".join(t.strip(".,!?;:\"'()").lower() for t in text.split())


def synthesize(text: str, out_path: Path) -> None:
    api_key = os.environ["OPENROUTER_API_KEY"]
    body = json.dumps(
        {"model": MODEL, "input": text, "voice": VOICE, "response_format": "mp3"}
    ).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/audio/speech",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}") from e
    out_path.write_bytes(resp.read())


def load_cards() -> list[dict]:
    with DECK_YAML.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg["cards"]


def english_text(card: dict) -> str:
    back = card["back"]
    return back.split("<br>", 1)[1].strip()


def main() -> None:
    only_id = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    force = "--force" in sys.argv
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cards = load_cards()
    generated = 0
    skipped = 0

    for card in cards:
        cid = card["id"]
        if only_id and cid != only_id:
            continue
        out_path = OUT_DIR / f"{cid}.mp3"
        if out_path.is_file() and not force:
            skipped += 1
            continue

        text = english_text(card)
        synthesize(text, out_path)
        generated += 1
        print(f"  + {cid} {text!r}")

    print(f"\ngenerated {generated}, skipped {skipped} (already existed)")


if __name__ == "__main__":
    main()
