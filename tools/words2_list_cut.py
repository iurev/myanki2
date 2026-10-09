#!/usr/bin/env python3
"""Record the letters and the animals as two long takes, then cut them apart.

Recording one clip per letter gives 29 separate utterances, each with its own
shape: every clip ends as if the sentence ended, some are faster than others, and
levelling them one by one leaves them slightly different from each other. That is
the wrong sound for clips whose only job is to be joined into the middle of a
word's spelling.

So each family is spoken once, as a list, in one take - "A, B, C, ... Z, A tilde,
..." and "Axolotl, Bat, ... Zouwu" - and cut into clips afterwards. One voice,
one pace, one loudness for the whole set, and the joins inside a word come out
even.

Cutting needs to know where each item is, so the take is transcribed with word
timestamps and the items are matched in order (the list's order is known, which
makes the alignment a single walk through the transcript). A boundary sits
between two items, a little before the earlier one's tail and a little after the
next one's start, so no clip swallows its neighbour.

Nothing here is trusted until it is heard: `--verify` plays each cut clip back to
a transcriber that is told nothing, and compares what it heard with the item it
should be.

    python3 tools/words2_list_cut.py --spec cidadela/work/words2-spec.json
    python3 tools/words2_list_cut.py --spec ... --verify
"""
from __future__ import annotations

import argparse
import base64
import difflib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mnemonics_tts import duration, synthesize  # noqa: E402
from words2_sounds import HEARD_AS, MARKS, OUT, as_words, transcribe  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "cidadela" / "work" / "words2-spec.json"
WORK = ROOT / "cidadela" / "work" / "list-takes"
LOUDNESS = "I=-18:TP=-1.5"
# Word timestamps for a single short word are tight - a letter read in a list comes
# back as a span of about 0.2s - so a clip cut to the span itself loses the sound
# (the letter B was cut to 0.38s of near silence). Each clip reaches well past its
# own span and stops at the midpoint to its neighbour, which no neighbour's voice
# reaches into.
BOUNDARY_BACK = 0.25
BOUNDARY_FORWARD = 0.35
MARKS_SPEECH = {"tilde": "tilde", "acute": "acute accent", "cedilla": "cedilla"}
# Spellings a transcriber has actually produced for an item, where the sound was
# right but the guess at the letters was not ("Sholo Dog" for xolo-dog).
ALIASES = {"xolo-dog": ["sholo", "solo", "zolo", "show"],
           "zouwu": ["zowu", "zowoo", "zowu"]}
# How many transcript words one item may swallow before it is called missing. The
# list is read in order, so an item's words are here or very near here; without a
# window a single miss runs to the end of the transcript and takes every later
# item down with it.
WINDOW = 3


def letter_items(spec: dict) -> list[dict]:
    """The letters, in one fixed order, with the words the take should speak.

    A letter is spoken as the character itself. Respellings were tried and are
    worse: "Ay" is the sound of the letter I, and "ei"/"ey" come back as "Hey".
    A marked letter is spoken as the plain letter plus the mark's name, which is
    how it is told apart from the plain letter without any carrier word.
    """
    items = []
    for letter in "abcdefghijklmnopqrstuvwxyz":
        items.append({"key": letter, "audio": f"w2_letter_{letter}.mp3",
                      "speech": letter.upper(), "kind": "letter"})
    for row in spec["letters"]:
        key = row["key"]
        if "_" not in key:
            continue
        base, mark = key.split("_", 1)
        items.append({"key": key, "audio": row["audio"],
                      "speech": f"{base.upper()} {MARKS_SPEECH[mark]}", "kind": "letter"})
    return items


def animal_items(spec: dict) -> list[dict]:
    return [{"key": row["letter"], "audio": row["audio"], "speech": row["name"].capitalize(),
             "kind": "animal"} for row in spec["animals"]]


def say(items: list[dict]) -> str:
    """The list as one utterance: items separated so the voice pauses between them."""
    return ". ".join(item["speech"] for item in items) + "."


def record(items: list[dict], name: str) -> Path:
    """Speak the whole list once, level the take once, keep it as a wav."""
    take = WORK / f"{name}.wav"
    text = say(items)
    pcm, content_type, _ = synthesize(text)
    rate = re.search(r"rate=(\d+)", content_type)
    channels = re.search(r"channels=(\d+)", content_type)
    if not rate or not channels:
        raise RuntimeError(f"unexpected content type {content_type!r}")
    WORK.mkdir(parents=True, exist_ok=True)
    raw = WORK / f".{name}.pcm"
    raw.write_bytes(pcm)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", rate.group(1),
                    "-ac", channels.group(1), "-i", str(raw), "-af", f"loudnorm={LOUDNESS}",
                    "-c:a", "pcm_s16le", str(take)], check=True)
    raw.unlink()
    (WORK / f"{name}.txt").write_text(text + "\n")
    return take


def timed_words(take: Path, name: str) -> list[dict]:
    """Word timestamps for the take, from a transcriber told nothing about it."""
    cache = WORK / f"{name}-words.json"
    if cache.is_file():
        return json.loads(cache.read_text())["words"]
    body = {"model": "openai/whisper-large-v3", "language": "en", "temperature": 0,
            "response_format": "verbose_json", "timestamp_granularities": ["word"],
            "input_audio": {"data": base64.b64encode(take.read_bytes()).decode(),
                            "format": "wav"}}
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/audio/transcriptions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                 "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            result = json.load(urllib.request.urlopen(request, timeout=600))
            break
        except urllib.error.HTTPError as error:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1) if error.code == 429 else 2 ** attempt)
    words = result.get("words") or []
    if not words:
        raise RuntimeError("no word timestamps came back for the take")
    cache.write_text(json.dumps({"words": words, "text": result.get("text", "")},
                                ensure_ascii=False, indent=2) + "\n")
    return words


def clean(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def matches(item: dict, word: str) -> bool:
    """Is this transcript word the item the take was meant to speak there?"""
    heard = clean(word)
    if not heard:
        return False
    if item["kind"] == "letter":
        return heard in {clean(name) for name in HEARD_AS[item["key"].split("_")[0]]}
    wanted = clean(item["speech"].split("-")[0])
    if heard == wanted or (len(wanted) > 3 and heard.startswith(wanted[:4])):
        return True
    if heard in {clean(name) for name in ALIASES.get(item["speech"].lower(), [])}:
        return True
    # "ZOWU" for zouwu: the sound is close enough that the letters differ.
    return difflib.SequenceMatcher(None, heard, wanted).ratio() >= 0.7


def rest_names(item: dict) -> set[str]:
    """The other words of an item's own name, so its whole name is cut at once.

    Two kinds of item are spoken with more than one word: a marked letter ("A
    acute accent") and a hyphenated animal ("Xolo-dog"). Both are one clip, and
    a clip that stops before "accent" would not say which mark it is.
    """
    names = {clean(part) for part in re.split(r"[\s-]+", item["speech"])[1:]}
    if item["kind"] == "letter" and "_" in item["key"]:
        names |= {clean(name) for name in MARKS[item["key"].split("_", 1)[1]]}
    return names - {""}


def align(items: list[dict], words: list[dict]) -> tuple[list[dict], list[str]]:
    """Give every item its span, walking the transcript once, in order.

    The search for an item stops after a few words: the list is read in order, so
    a word that is not this item is either its own extra word or a neighbour's
    (or the transcriber misheard one), never something far away.
    """
    spans, notes, position = [], [], 0
    for item in items:
        found = next((look for look in range(position, min(position + WINDOW, len(words)))
                      if matches(item, words[look]["word"])), None)
        if found is None:
            spans.append(None)
            notes.append(f'{item["speech"]}: not found in '
                         f'{[w["word"] for w in words[position:position + WINDOW]]}')
            continue
        if found > position:
            notes.append(f'{item["speech"]}: skipped '
                         f'{[w["word"] for w in words[position:found]]}')
        start, end = words[found]["start"], words[found]["end"]
        following = found + 1
        names = rest_names(item)
        while names and following < len(words) and clean(words[following]["word"]) in names:
            end = words[following]["end"]
            following += 1
        spans.append({"start": start, "end": end})
        position = following
    return spans, notes


def cut(take: Path, spans: list[dict], items: list[dict]) -> int:
    """Cut one clip per item, with the boundary between it and its neighbour."""
    length = duration(take)
    missing = []
    for index, (item, span) in enumerate(zip(items, spans)):
        if span is None:
            missing.append(item["speech"])
            continue
        following = next((s for s in spans[index + 1:] if s), None)
        start = max(0.0, span["start"] - BOUNDARY_BACK)
        end = span["end"] + BOUNDARY_FORWARD
        # The last item has no neighbour to stop it, and the take's own tail is
        # the honest limit; elsewhere the midpoint keeps two clips apart.
        end = min(end, (span["end"] + following["start"]) / 2) if following else min(end, length)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(take),
                        "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                        "-c:a", "libmp3lame", "-b:a", "128k", str(OUT / item["audio"])],
                       check=True)
    return missing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", default=str(SPEC))
    parser.add_argument("--family", choices=["letters", "animals"], default="")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    families = {"letters": letter_items(spec), "animals": animal_items(spec)}
    if args.family:
        families = {args.family: families[args.family]}

    if args.dry_run:
        for name, items in families.items():
            print(f"{name}: {len(items)} item(s), {len(say(items).split())} words")
            print(f"   {say(items)[:150]}...")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    for name, items in families.items():
        take = WORK / f"{name}.wav"
        if not take.is_file():
            print(f"recording the {name} take: {len(items)} items, "
                  f"{len(say(items).split())} words")
            take = record(items, name)
            print(f"   {duration(take)}s -> {take.relative_to(ROOT)}")
        words = timed_words(take, name)
        print(f"   {len(words)} word timestamp(s) came back")
        spans, notes = align(items, words)
        missing = cut(take, spans, items)
        found = sum(1 for span in spans if span)
        print(f"   cut {found}/{len(items)} clip(s)")
        for note in notes:
            print(f"      note: {note}")
        for item, span in zip(items, spans):
            heard = next((w["word"] for w in words
                          if span and abs(w["start"] - span["start"]) < 1e-6), "")
            print(f'      {"ok" if span else "MISSING"} {item["speech"]:6s} '
                  f'{(span or {}).get("start", 0):6.2f}s  heard {heard!r}')
        if missing:
            print(f"   NOT FOUND in the take: {missing}")

    if args.verify:
        bad = 0
        for name, items in families.items():
            for item in items:
                path = OUT / item["audio"]
                heard = transcribe(path) if path.is_file() else "(missing)"
                absent = []
                if item["kind"] == "animal":
                    # The same sound-based test the alignment uses, applied word by
                    # word: a name the transcriber spells its own way ("Sholo Dog"
                    # for xolo-dog, "ZOWU" for zouwu) passes, a wrong name does not.
                    if not any(matches(item, word) for word in as_words(heard)):
                        absent.append(item["speech"])
                else:
                    base, _, mark = item["key"].partition("_")
                    if not any(word in as_words(heard) for word in HEARD_AS[base]):
                        absent.append(base)
                    if mark and not any(word in as_words(heard) for word in MARKS[mark]):
                        absent.append(mark)
                bad += 1 if absent else 0
                note = f'  MISSING {absent}' if absent else ""
                print(f'{"ok" if not absent else "??"} {item["speech"]:6s} '
                      f'{duration(path) if path.is_file() else 0:>5.2f}s heard {heard!r}{note}',
                      flush=True)
        print(f"\n{bad} doubtful to a blind ear")


if __name__ == "__main__":
    main()
