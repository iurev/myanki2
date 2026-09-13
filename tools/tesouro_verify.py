#!/usr/bin/env python3
"""Independently re-transcribe cut Tesouro clips and compare against the
known-correct sentence text. This is the cross-check pass: alignment and
verification use separate whisper invocations (fresh audio read, no shared
state) so a boundary bug in one doesn't silently pass the other.

Flags anything below the similarity threshold for manual/LLM review instead
of trusting the cutter blindly.
"""
from __future__ import annotations

import csv
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALIGNMENT_CSV = ROOT / "tesouro" / "alignment-ch01-10.csv"
AUDIO_DIR = ROOT / "tesouro" / "audio"

THRESHOLD = 0.97


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    toks = [
        p.strip(".,!?;:—–\"'()…").lower()
        for w in text.split()
        for p in w.split("-")
    ]
    # Word-initial 'h' is silent in Portuguese (Hei/Ei, etc).
    toks = [t[1:] if len(t) > 1 and t[0] == "h" else t for t in toks]
    return " ".join(t for t in toks if t)


def load_targets(chapter: int) -> list[tuple[str, str]]:
    rows = []
    with ALIGNMENT_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if int(row["chapter"]) == chapter:
                rows.append((row["id"], row["text"]))
    return rows


def main() -> None:
    chapter = int(sys.argv[1])
    targets = load_targets(chapter)

    from faster_whisper import WhisperModel

    model = WhisperModel("large-v3", device="cuda", compute_type="float16")

    flagged = []
    for i, (sid, text) in enumerate(targets):
        clip = AUDIO_DIR / f"ch{chapter:02d}" / f"{sid}.mp3"
        if not clip.is_file():
            flagged.append((sid, text, "", 0.0, "MISSING FILE"))
            continue
        # Give Whisper the preceding sentence as narrative context (not the
        # current one -- that would be circular). Short isolated utterances
        # otherwise have measurably worse ASR accuracy than the same words
        # heard in the original full-chapter pass, which caused false
        # mismatch flags on lines like "Está partido." heard as "Está a
        # partir..." when transcribed with zero context.
        prev_text = targets[i - 1][1] if i > 0 else None
        segments, _info = model.transcribe(
            str(clip), language="pt", word_timestamps=False, initial_prompt=prev_text
        )
        heard = " ".join(seg.text.strip() for seg in segments)
        ratio = SequenceMatcher(None, normalize(text), normalize(heard)).ratio()
        status = "ok" if ratio >= THRESHOLD else "FLAG"
        if status == "FLAG":
            flagged.append((sid, text, heard, ratio, "LOW SIMILARITY"))
        print(f"  [{status}] {sid} ratio={ratio:.2f}  expected={text!r}  heard={heard!r}")

    print(f"\nchapter {chapter}: {len(targets) - len(flagged)}/{len(targets)} passed threshold {THRESHOLD}")
    if flagged:
        print(f"FLAGGED ({len(flagged)}):")
        for sid, text, heard, ratio, reason in flagged:
            print(f"  {sid} [{reason}] ratio={ratio:.2f} expected={text!r} heard={heard!r}")


if __name__ == "__main__":
    main()
