#!/usr/bin/env python3
"""Record the two spelling voices of words2: one clip per letter, per animal.

Every card's spelling audio is a merge of these clips, so they are recorded once
(the same letter sounds the same in every word) and 29 letters and 26 animals
cover the whole deck. Both are English: the letters are the English letter names,
and the animals are the mnemonics deck's animal words, which are already how the
learner thinks about those keys.

A clip is only reused when the state says it was recorded for the same speech, so
rewording a letter re-records it and never leaves the old take behind.

--verify hears every clip again with a different model, told nothing about what
it should be, and prints what it heard next to the letter it stands for. It is
the only honest check for a set of clips whose whole job is to be recognised: the
mnemonics work turned up "A" being said as "Ah" and "A you", which no amount of
looking at the files would have caught.

    python3 tools/words2_sounds.py
    python3 tools/words2_sounds.py --verify
    python3 tools/words2_sounds.py --retake a --retake c_cedilla
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mnemonics_tts import (MODEL, SECOND_OPINION_MODEL, VERIFY_MODEL, VOICE, as_words,
                           duration, generation_cost, synthesize, transcribe)

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "cidadela" / "work" / "words2-spec.json"
OUT = ROOT / "cidadela" / "audio2"
STATE = ROOT / "cidadela" / "work" / "words2-sounds-state.json"

# What a transcriber may reasonably write down for each letter's name, since it
# hears a sound and guesses a spelling ("Ay" comes back as "A", "aye", "eh").
HEARD_AS = {
    "a": ["a", "ay", "aye", "ey", "eh"], "b": ["b", "bee", "be"],
    "c": ["c", "see", "sea", "si"], "d": ["d", "dee"], "e": ["e", "ee"],
    "f": ["f", "eff", "ef"], "g": ["g", "gee"], "h": ["h", "aitch", "haitch", "eitch"],
    "i": ["i", "eye", "aye"], "j": ["j", "jay"], "k": ["k", "kay"],
    "l": ["l", "ell", "el", "elle"], "m": ["m", "em"], "n": ["n", "en"],
    "o": ["o", "oh", "owe"], "p": ["p", "pee", "pea"], "q": ["q", "cue", "queue", "que"],
    "r": ["r", "arr", "are", "ar"], "s": ["s", "ess", "es"], "t": ["t", "tee", "tea"],
    "u": ["u", "you", "ewe", "yoo"], "v": ["v", "vee"], "w": ["w", "double you", "doubleyou", "double u"],
    "x": ["x", "ex"], "y": ["y", "why", "wye"], "z": ["z", "zed", "zee"],
}
MARKS = {"acute": ["acute", "a cute"], "tilde": ["tilde", "tilda", "teal duh"],
         "cedilla": ["cedilla", "sedilla", "cecila", "sidiya", "sadilla"]}


def clips(spec: dict) -> list[dict]:
    """The letter and animal clips the spec needs, with the speech for each."""
    rows = [{"key": f'letter {row["key"]}', "speech": row["speech"], "audio": row["audio"],
             "kind": "letter", "letter": row["key"]} for row in spec["letters"]]
    rows += [{"key": f'animal {row["letter"]}', "speech": row["speech"], "audio": row["audio"],
              "kind": "animal", "letter": row["letter"]} for row in spec["animals"]]
    return rows


def missing_words(row: dict, heard: str) -> list[str]:
    """Which parts of the clip were not heard: the animal, or the letter and its mark."""
    words = as_words(heard)
    if row["kind"] == "animal":
        # An animal clip stands for a letter but never says it, so only the
        # animal's own name is checked here.
        return [] if any(word in words for word in as_words(row["speech"])) else [row["speech"]]
    base, _, mark = row["letter"].partition("_")
    absent = []
    if not any(name in words for name in HEARD_AS[base]):
        absent.append(base)
    if mark and not any(name in words for name in MARKS[mark]):
        absent.append(mark)
    return absent


def probe_wording(wordings: list[str]) -> None:
    """Record candidate wordings to a scratch folder and hear them, both ears.

    Wording is not guessable: "Ay acute" comes back as "Eh, cute", and "Ay"
    before another word can come back as "I". These clips are not used by the
    deck - they exist only to be judged before a wording is chosen.
    """
    probe_dir = OUT / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    for wording in wordings:
        pcm, content_type, _ = synthesize(wording)
        rate = re.search(r"rate=(\d+)", content_type)
        channels = re.search(r"channels=(\d+)", content_type)
        if not rate or not channels:
            raise RuntimeError(f"unexpected content type {content_type!r}")
        pcm_path = probe_dir / f'.{abs(hash(wording))}.pcm'
        pcm_path.write_bytes(pcm)
        mp3 = probe_dir / f'"{wording}".mp3'.replace("/", "-")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le",
                        "-ar", rate.group(1), "-ac", channels.group(1), "-i", str(pcm_path),
                        "-codec:a", "libmp3lame", "-qscale:a", "2", str(mp3)], check=True)
        pcm_path.unlink()
        print(f'{wording!r:34s} heard {transcribe(mp3)!r}  | '
              f'{SECOND_OPINION_MODEL}: {transcribe(mp3, SECOND_OPINION_MODEL)!r}', flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--probe", action="append", default=[],
                        help="record this wording to a scratch folder and hear it back")
    parser.add_argument("--retake", action="append", default=[])
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--kind", choices=["letter", "animal"], default="",
                        help="only the letter clips, or only the animal clips")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if args.probe:
        probe_wording(args.probe)
        return
    rows = clips(spec)
    if args.kind:
        rows = [row for row in rows if row["kind"] == args.kind]
    if args.only:
        rows = [row for row in rows if row["letter"] in args.only or row["key"] in args.only]
    if args.dry_run:
        print(f"{len(rows)} clip(s) to record")
        for row in rows:
            print(f'  {row["key"]:16s} says {row["speech"]!r}')
        return

    state = json.loads(STATE.read_text()) if STATE.is_file() else {}
    if args.retake:
        for row in rows:
            if row["letter"] in args.retake or row["key"] in args.retake:
                (OUT / row["audio"]).unlink(missing_ok=True)

    if args.verify:
        bad = 0
        for row in rows:
            path = OUT / row["audio"]
            if not path.is_file():
                print(f'?? {row["key"]:16s} MISSING {row["audio"]}')
                bad += 1
                continue
            heard = transcribe(path)
            absent = missing_words(row, heard)
            second = ""
            if absent:
                second = transcribe(path, SECOND_OPINION_MODEL)
                absent = missing_words(row, second)
            bad += 1 if absent else 0
            flag = "??" if absent else "ok"
            note = f'  missing {absent}' if absent else ""
            print(f'{flag} {row["key"]:16s} says {row["speech"]!r:20s} heard {heard!r}{note}'
                  + (f'  | second ear: {second!r}' if second else ""), flush=True)
        print(f"\n{len(rows)} clip(s), {bad} doubtful to both ears")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    counter = {"done": 0, "cost": 0.0}

    def produce(row: dict) -> None:
        mp3 = OUT / row["audio"]
        if mp3.is_file() and state.get(row["key"], {}).get("speech") == row["speech"]:
            return
        pcm, content_type, generation_id = synthesize(row["speech"])
        rate = re.search(r"rate=(\d+)", content_type)
        channels = re.search(r"channels=(\d+)", content_type)
        if not rate or not channels:
            raise RuntimeError(f'{row["key"]}: unexpected content type {content_type!r}')
        pcm_path = OUT / f'.{row["audio"]}.{os.getpid()}.{threading.get_ident()}.pcm'
        pcm_path.write_bytes(pcm)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le",
                        "-ar", rate.group(1), "-ac", channels.group(1), "-i", str(pcm_path),
                        "-codec:a", "libmp3lame", "-qscale:a", "2", str(mp3)], check=True)
        pcm_path.unlink()
        with lock:
            state[row["key"]] = {"speech": row["speech"], "audio": row["audio"],
                                 "model": MODEL, "voice": VOICE, "duration": duration(mp3),
                                 "bytes": mp3.stat().st_size, "generation_id": generation_id,
                                 "cost": generation_cost(generation_id)}
            counter["done"] += 1
            counter["cost"] += state[row["key"]]["cost"] or 0.0
            print(f'  {counter["done"]:>3}/{len(rows)}  {row["key"]:16s} '
                  f'{state[row["key"]]["duration"]:>4}s  {row["speech"]!r}', flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(produce, rows))
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f'recorded {counter["done"]} clip(s), ${counter["cost"]:.4f}')
    print("state: " + str(STATE.relative_to(ROOT)))


if __name__ == "__main__":
    main()
