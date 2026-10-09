#!/usr/bin/env python3
"""Verify the A Cidadela Misteriosa English clips with the Tesouro verifier.

`tesouro_en_verify_api.py` transcribes each English clip with two unprompted
providers and asks whether they reproduce the sentence, tolerate a dropped
parenthetical, count fuzzy-matched words and refuse a clip that the weaker
provider hears as a different sentence. This file points it at this book.

    python3 tools/cidadela_en_verify.py --audio cidadela/audio-en --record cm0209
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tesouro_en_verify_api  # noqa: E402 - the tested implementation, reused

tesouro_en_verify_api.INVENTORY = ROOT / "cidadela" / "work" / "text-inventory.json"
# This book has no English exceptions yet. An empty map means every clip has to
# convince both providers on its own.
tesouro_en_verify_api.EXCEPTIONS = {}

EN_AUDIO = ROOT / "cidadela" / "audio-en"
PRISTINE = ROOT / "cidadela" / "audio-en-original"


def drop_retaken_transcripts() -> list[str]:
    """Forget cached transcripts of clips that have since been recorded again.

    The shared verifier keeps one transcript per note id, so it would judge a
    retaken clip on the audio it used to be. A clip was recorded again exactly
    when its pristine copy (which the gain stage levels from and never rewrites)
    is newer than the cached transcript; the gain stage itself rewrites every
    shipped clip, so its timestamps cannot tell them apart.
    """
    dropped = []
    for name in ("stt-en-unprompted", "stt-en-chirp"):
        for cache in sorted((EN_AUDIO.parent / name).glob("*.json")):
            take = PRISTINE / f"{cache.stem}.mp3"
            if take.is_file() and cache.stat().st_mtime < take.stat().st_mtime:
                cache.unlink()
                dropped.append(f"{name}/{cache.name}")
    return dropped


if __name__ == "__main__":
    dropped = drop_retaken_transcripts()
    if dropped:
        print(json.dumps({"dropped_retaken_transcripts": dropped}, ensure_ascii=False))
    sys.argv = [sys.argv[0], *sys.argv[1:]]
    tesouro_en_verify_api.main()
