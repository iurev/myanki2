#!/usr/bin/env python3
"""Independently re-transcribe generated English clips (faster-whisper,
English) and compare against the intended text. The TTS endpoint used by
tesouro_en_tts.py returns no transcript of its own, so this is the only
cross-check that the clip actually says what it's supposed to.
"""
from __future__ import annotations

import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DECK_YAML = ROOT / "tesouro-listening.yaml"
AUDIO_DIR = ROOT / "tesouro" / "audio-en"

THRESHOLD = 0.9


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return " ".join(t.strip(".,!?;:\"'()").lower() for t in text.split())


def load_cards() -> list[dict]:
    with DECK_YAML.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg["cards"]


def english_text(card: dict) -> str:
    return card["back"].split("<br>", 1)[1].strip()


def main() -> None:
    chapter_filter = sys.argv[1] if len(sys.argv) > 1 else None
    cards = load_cards()
    if chapter_filter:
        cards = [c for c in cards if f"chapter{int(chapter_filter):02d}" in c["tags"]]

    from faster_whisper import WhisperModel

    model = WhisperModel("large-v3", device="cuda", compute_type="float16")

    flagged = []
    for card in cards:
        cid = card["id"]
        text = english_text(card)
        clip = AUDIO_DIR / f"{cid}.mp3"
        if not clip.is_file():
            flagged.append((cid, text, "", 0.0, "MISSING FILE"))
            continue
        segments, _info = model.transcribe(str(clip), language="en", word_timestamps=False)
        heard = " ".join(seg.text.strip() for seg in segments)
        ratio = SequenceMatcher(None, normalize(text), normalize(heard)).ratio()
        status = "ok" if ratio >= THRESHOLD else "FLAG"
        if status == "FLAG":
            flagged.append((cid, text, heard, ratio, "LOW SIMILARITY"))
        print(f"  [{status}] {cid} ratio={ratio:.2f}  expected={text!r}  heard={heard!r}")

    print(f"\n{len(cards) - len(flagged)}/{len(cards)} passed threshold {THRESHOLD}")
    if flagged:
        print(f"FLAGGED ({len(flagged)}):")
        for cid, text, heard, ratio, reason in flagged:
            print(f"  {cid} [{reason}] ratio={ratio:.2f} expected={text!r} heard={heard!r}")


if __name__ == "__main__":
    main()
