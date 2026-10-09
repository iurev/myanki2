#!/usr/bin/env python3
"""Build every clip a words2 card needs: three recordings and two merges.

Per card:

* the English word, spoken - the front's first audio;
* the English example sentence, spoken, the word in it sounding stressed;
* the Portuguese word, spoken by a native pt-PT voice;
* the spelling by letters: one clip per letter of the word, joined;
* the spelling by animals: the mnemonics animal of each letter, joined.

The voices are split on purpose. English stays with the house voice. The Portuguese
word is spoken by a native European Portuguese voice, because a learner copying a
flashcard must copy Lisbon's habits and not a multilingual voice's approximation of
them. Plain text is sent, never IPA: inline IPA in /slashes/ was measured and
rejected - on both v3 and v4 it came back as different words altogether.

The two merges record nothing new. The letters and animals come from
`words2_list_cut.py`, which recorded one long take per family and cut it into 29
letters and 26 animals for the whole deck, so a word is merged from clips that
already exist - and changing one letter fixes it in every word at once.

A join is never levelled again. The takes were levelled once, as a whole, so the
parts already match each other; running them through the same levelling a second
time pulls them apart again, which is the opposite of why they were recorded as
one take. The gaps of silence between parts are not levelled at all.

`--verify` is a check, not a printout. Every recorded clip is played back to a
transcriber that is told nothing, and what it heard is compared with what the clip
was asked to say: a one-word clip has to have all of its words heard, and a
sentence clip nearly all of them, in order. The merges are checked by arithmetic
instead - every part they were built from is still there and the join lasts as
long as its parts plus its gaps - because their letter and animal clips are
listened to one by one by `tools/words2_list_cut.py --verify`. The verdicts are
written to `work/words2-audio-verification.json` and a doubtful clip fails the
command, so a mistake cannot pass unnoticed in a wall of output.

    python3 tools/words2_audio.py --spec cidadela/work/words2-spec-pilot.json --dry-run
    python3 tools/words2_audio.py --spec cidadela/work/words2-spec-pilot.json
    python3 tools/words2_audio.py --spec ... --verify
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mnemonics_tts import (MODEL, SECOND_OPINION_MODEL, VOICE, as_words, duration,
                           generation_cost, synthesize)
from mnemonics_tts import transcribe as hear_with
from cidadela_align import in_order_coverage, tokens
from cidadela_glossary_gap import plain

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "cidadela" / "work" / "words2-spec.json"
OUT = ROOT / "cidadela" / "audio2"
STATE = ROOT / "cidadela" / "work" / "words2-audio-state.json"
# Where the `--verify` run leaves its verdicts, so a doubtful clip outlives the
# output of the command that found it.
VERDICT = ROOT / "cidadela" / "work" / "words2-audio-verification.json"
# A sentence read back by a machine loses a word now and then, so a clip passes
# when nearly all of its words were heard, in order, rather than all of them.
COVERAGE = 0.9
# How differently a word may be written down and still be the word that was said.
# "viagem" is heard as "Viajeng." because the last vowel is nasal Portuguese, and
# "tão" as "Tchau." or "tau": a machine spells Portuguese vowels with English
# letters, so the comparison is deliberately loose about them. A clip that says a
# different word shares neither most of the letters nor the order they come in -
# "viagem" against "banana" - which is what this is here to catch.
CLOSE_ENOUGH = 0.75
SAME_LETTERS = 0.6
# A real recording of one word or one sentence cannot be this short. A clip that
# is, lost its sound somewhere between the model and here.
MIN_WORD_SECONDS = 0.25
MIN_SENTENCE_SECONDS = 0.6
SILENCE = OUT / "w2_silence_160ms.mp3"
LOUDNESS = "I=-18:TP=-1.5"
GAP_SECONDS = 0.16

# The native European Portuguese voice for Portuguese words. Bárbara is a library
# voice kept in the account for exactly this, and she is verified on pt-PT across
# the multilingual models.
ELEVENLABS_VOICE = "WG4z7mVwYbBsuZ4tvxzm"
ELEVENLABS_MODEL = "eleven_v4"
# What a thousand characters of eleven_v4 cost right now. The promotional rate runs
# until 12 October 2026; the list rate is 0.08. Only used to report what a run spent.
ELEVENLABS_RATE = 0.022
# The key is read from the environment, or from a file outside this repository, so
# there is nothing here to commit by accident.
ELEVENLABS_KEY = Path.home() / ".config" / "elevenlabs" / "api-key"
# How a word is written for the voice. Capitalised with a full stop, which stops her
# running the word into the next one. The exceptions are words whose wording was
# chosen by ear from the probe pages, and "ele" is the one that should not be read
# any further into: none of the wordings fixed that word, so its own take stays.
SENT_AS = {"ele": "ele"}
# A burst of parallel requests runs into the account's rate limit, which answers 429
# rather than queueing. The wait grows with each attempt and a persistent refusal is
# raised, so a real problem still stops the run instead of hiding in retries.
ELEVENLABS_TRIES = 5
ELEVENLABS_BACKOFF = 3.0
# One Portuguese word is asked for at a time. A burst is what the rate limit answers
# with a 429, so the words are sent one after another; the English clips are another
# service and still record in parallel.
ELEVENLABS_LOCK = threading.Lock()


def said_as(word: str) -> str:
    """One Portuguese word as it is written for the voice."""
    return SENT_AS.get(word, word[:1].upper() + word[1:] + ".")


# One English word is not spoken as written either. Asked for the bare word "noise",
# the voice treated it as a sound effect: seven takes came back as a 79-second music
# file, laughter, a cough, a sigh, "ahem", "Hmm." and "Whew.", and "Noise." was read
# as "Mm-hmm" - the word names a sound, so the model makes the sound. Respelled
# "Noyze.", the same voice reads the word itself (heard back as "noise"). What the
# card shows, and what the blind ear is asked for, stays the glossary's `card["english"]`;
# only the text sent to the voice changes.
EN_SAID_AS = {"noise": "Noyze."}


def english_said_as(word: str) -> str:
    """One English word as it is written for the voice."""
    return EN_SAID_AS.get(word.strip().lower(), word)


def elevenlabs_key() -> str:
    """The ElevenLabs API key, from the environment or from outside the repository."""
    from_environment = os.environ.get("ELEVENLABS_API_KEY")
    if from_environment:
        return from_environment.strip()
    if ELEVENLABS_KEY.is_file():
        return ELEVENLABS_KEY.read_text().strip()
    raise SystemExit(f"no ElevenLabs key: set ELEVENLABS_API_KEY or write one to {ELEVENLABS_KEY}")


def speak_portuguese(word: str) -> bytes:
    """One Portuguese word as mp3, said by the native pt-PT voice, in plain text."""
    request = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE}"
        "?output_format=mp3_44100_128",
        data=json.dumps({"text": said_as(word), "model_id": ELEVENLABS_MODEL}).encode(),
        headers={"xi-api-key": elevenlabs_key(), "Content-Type": "application/json"})
    for attempt in range(ELEVENLABS_TRIES):
        try:
            with ELEVENLABS_LOCK, urllib.request.urlopen(request, timeout=180) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == ELEVENLABS_TRIES - 1:
                raise
            time.sleep(ELEVENLABS_BACKOFF * (attempt + 1))
    raise RuntimeError("unreachable")


def build_clips(spec: dict) -> list[dict]:
    """Every clip the spec asks to be recorded, and the merge recipes."""
    clips = []
    for card in spec["cards"]:
        clips += [
            {"key": f'{card["portuguese"]} english', "speech": card["english"],
             "say": english_said_as(card["english"]),
             "audio": card["media"]["english"], "language": "en", "kind": "word"},
            {"key": f'{card["portuguese"]} sentence', "speech": card["sentence"],
             "audio": card["media"]["sentence"], "language": "en", "kind": "sentence"},
            {"key": f'{card["portuguese"]} portuguese', "speech": card["portuguese"],
             "audio": card["media"]["portuguese"], "language": "pt", "kind": "word"},
        ]
    return clips


def merge_recipes(spec: dict) -> list[dict]:
    """Each card's two merged clips, as the list of source clips to join."""
    animal_clip = {row["name"]: row["audio"] for row in spec["animals"]}
    recipes = []
    for card in spec["cards"]:
        letters = [f'w2_letter_{key}.mp3' for key in card["letters"]]
        animals = [animal_clip[name] for name in card["animals"]]
        recipes += [
            {"key": f'{card["portuguese"]} letters', "audio": card["media"]["letters"],
             "sources": letters},
            {"key": f'{card["portuguese"]} animals', "audio": card["media"]["animals"],
             "sources": animals},
        ]
    return recipes


def silence() -> None:
    """One short silence, reused as the gap between joined clips."""
    if not SILENCE.is_file():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "anullsrc=r=24000:cl=mono", "-t", str(GAP_SECONDS),
                        "-codec:a", "libmp3lame", "-qscale:a", "2", str(SILENCE)],
                       check=True)


def join(sources: list[str], out: Path) -> None:
    """Join clips into one mp3, trimming them to the same quiet length.

    Nothing is levelled here. The letter and animal clips are cut from one take
    each, which was levelled once as a whole, so they already match; levelling
    each piece again would pull them apart, which is the opposite of the point of
    recording them in one take. The gaps are not levelled either: pushing silence
    through loudnorm makes the mp3 encoder assert (`psymodel.c: calc_energy`).
    """
    inputs: list[str] = []
    for source in sources:
        inputs += ["-i", str(OUT / source), "-i", str(SILENCE)]
    count = len(inputs) // 2
    filters = "".join(f"[{index}:a]aresample=24000[a{index}];" for index in range(count))
    joined = "".join(f"[a{index}]" for index in range(count))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex",
                    f"{filters}{joined}concat=n={count}:v=0:a=1[aout]",
                    "-map", "[aout]", "-codec:a", "libmp3lame", "-b:a", "128k", str(out)],
                   check=True)


def said_words(text: str) -> list[str]:
    """The words of a transcript, as the mnemonics tools read them (digits spelt out)."""
    return as_words(text)


def close(heard: str, wanted: str) -> bool:
    """Is this the same word, allowing for how a machine spelt what it heard?

    Two ways to be the same: most of the letters match in order, or enough of the
    letters appear in the same order. The second is what saves a short Portuguese
    word, where one vowel heard as English costs a large share of its few letters.
    """
    if heard == wanted:
        return True
    if SequenceMatcher(None, heard, wanted, autojunk=False).ratio() >= CLOSE_ENOUGH:
        return True
    return letter_share(wanted, heard) >= SAME_LETTERS


def letter_share(wanted: str, heard: str) -> float:
    """Share of the wanted word's letters that appear in the heard word, in order."""
    if not wanted:
        return 1.0
    position, found = 0, 0
    for letter in wanted:
        index = heard.find(letter, position)
        if index >= 0:
            found += 1
            position = index + 1
    return found / len(wanted)


def missing_from(clip: dict, heard: str) -> list[str]:
    """Which of a one-word clip's words were not heard."""
    heard_words = said_words(heard)
    return [word for word in said_words(clip["speech"])
            if not any(close(spoken, word) for spoken in heard_words)]


def coverage_of(clip: dict, heard: str) -> float:
    """How much of a sentence was heard, with digits read back as words.

    A transcriber writes "forty years" as "40 years", which is the same sentence
    said the same way, so numbers are spelt out before the two are compared.
    """
    tokens_ = [token for word in as_words(heard) for token in tokens(word)]
    return in_order_coverage(clip["speech"], tokens_)


# Short Portuguese words that an English ear writes down as the one letter they
# sound like. These were not waved through: each one was read back by hand and the
# clip does say the word. The letter is what the word really sounds like - "ele"
# is /'eli/, "tu" is /tu/ heard as "two", "quem" is nasal and lands on "Keng" -
# and none of them can be confused with a different Portuguese word. A clip that
# said the wrong word would not come back as a letter that is in the word.
REVIEWED_SOUNDS = {
    "ele": ["l"], "esse": ["s"], "quem": ["keng", "k"], "seu": ["entao", "so"],
    "ti": ["t"], "tu": ["2", "two"],
}


def reviewed_by_hand(clip: dict, heard: str) -> bool:
    """Does this clip say a short word that a blind ear writes as a single letter?

    The comparison is on the plain transcript itself, not on its words: as_words
    splits "Então?" at the letter ã, and a whole spelling is what the table holds.
    """
    wanted = plain(clip["speech"])
    written = re.sub(r"[^a-z0-9 ]", "", plain(heard)).strip()
    return any(written == spelling for spelling in REVIEWED_SOUNDS.get(wanted, []))


def second_opinion(clip: dict) -> tuple[str, list[str] | float]:
    """Ask a second transcriber what the clip says before doubting it.

    One ear is not evidence that a clip is wrong: it mishears nasal Portuguese as
    an English ending, and a name or a rare word as a commoner one. A clip is only
    doubtful when both ears fail to find the word.
    """
    heard = hear_with(OUT / clip["audio"], SECOND_OPINION_MODEL)
    if clip["kind"] == "sentence":
        return heard, coverage_of(clip, heard)
    return heard, missing_from(clip, heard)


def shortest_is_plausible(clip: dict) -> tuple[bool, float]:
    """Was this clip long enough to hold what it is supposed to say?"""
    path = OUT / clip["audio"]
    seconds = duration(path) if path.is_file() else 0.0
    floor = MIN_WORD_SECONDS if clip["kind"] == "word" else MIN_SENTENCE_SECONDS
    return seconds >= floor, round(seconds, 2)


def verdict_of(clip: dict, heard: str) -> dict:
    """What a clip should say, against what a blind ear heard in it.

    A one-word clip has to have every one of its words heard - for a Portuguese
    verb that is the word and its pronoun, since "casar-se" comes back as
    "casar se". A sentence clip is judged by how much of it was heard, in order,
    because a transcriber drops a small word now and then even on a clean take.
    """
    plausible, seconds = shortest_is_plausible(clip)
    where = {"key": clip["key"], "audio": clip["audio"], "wanted": clip["speech"],
             "heard": heard, "seconds": seconds}
    # A clip with nothing to say would otherwise pass every check below by having
    # nothing to look for, which is the shape of a vacuous pass.
    if not said_words(clip["speech"]):
        return {**where, "ok": False, "no_text": True}
    if not plausible:
        return {**where, "ok": False, "too_short": True}
    if clip["kind"] == "sentence":
        coverage = coverage_of(clip, heard)
        if coverage >= COVERAGE:
            return {**where, "coverage": round(coverage, 3), "ok": True}
    else:
        missing = missing_from(clip, heard)
        if not missing:
            return {**where, "coverage": 1.0, "ok": True}
        if reviewed_by_hand(clip, heard):
            return {**where, "coverage": 1.0, "ok": True, "reviewed": True}
    second, evidence = second_opinion(clip)
    where["second_opinion"] = second
    if clip["kind"] == "sentence":
        return {**where, "coverage": round(coverage, 3), "second_coverage": round(evidence, 3),
                "ok": evidence >= COVERAGE}
    return {**where, "coverage": 0.0, "missing": missing, "second_missing": evidence,
            "ok": not evidence, "second_opinion": second}


def merge_verdict(recipe: dict) -> dict:
    """A join is right when it holds every part it was built from, and lasts as long.

    The join is a concatenation of named clips, so the parts are known and the
    length is arithmetic: the parts' own lengths plus one gap between each pair. A
    join that lost a part, or died halfway leaving a stub, fails here. The letter
    and animal clips themselves are listened to one at a time by
    tools/words2_list_cut.py --verify, which is a sharper ear on them than a
    transcriber hearing the whole join at once.
    """
    path = OUT / recipe["audio"]
    lengths = [duration(OUT / source) for source in recipe["sources"]]
    expected = sum(lengths) + GAP_SECONDS * (len(lengths) - 1)
    actual = duration(path) if path.is_file() else 0.0
    return {"key": recipe["key"], "audio": recipe["audio"], "parts": len(recipe["sources"]),
            "seconds": round(actual, 2), "expected": round(expected, 2),
            "ok": bool(lengths) and expected - 0.35 <= actual <= expected + 0.35}


def transcribe(path: Path, language: str) -> str:
    """Hear a clip with no hint of what it should say, in the language asked."""
    body = {"model": "openai/whisper-large-v3", "language": language, "temperature": 0,
            "input_audio": {"data": base64.b64encode(path.read_bytes()).decode(),
                            "format": "mp3"}}
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/audio/transcriptions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                 "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            return (json.load(urllib.request.urlopen(request, timeout=60)).get("text") or "").strip()
        except urllib.error.HTTPError as error:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1) if error.code == 429 else 2 ** attempt)
    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", default=str(SPEC))
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    clips = build_clips(spec)
    recipes = merge_recipes(spec)
    if args.only:
        clips = [c for c in clips if any(word in c["key"] for word in args.only)]
        recipes = [r for r in recipes if any(word in r["key"] for word in args.only)]
    media = len(spec["cards"]) * 5
    if args.dry_run:
        print(f'{len(spec["cards"])} card(s): {len(clips)} clip(s) to record, '
              f'{len(recipes)} merge(s) to build, {media} media file(s) in the deck')
        print(f'letters per word: '
              f'{", ".join(str(len(c["letters"])) for c in spec["cards"])}')
        return

    if args.verify:
        results, problems = [], []
        for clip in clips:
            path = OUT / clip["audio"]
            heard = transcribe(path, clip["language"]) if path.is_file() else "(missing)"
            row = verdict_of(clip, heard)
            results.append(row)
            if not row["ok"]:
                problems.append(row)
                print(f'?? {row["key"]:26s} wanted {row["wanted"]!r} heard {heard!r} '
                      f'| second ear: {row.get("second_opinion")!r} '
                      f'{(row.get("missing") or "")}', flush=True)
        merges = [merge_verdict(recipe) for recipe in recipes]
        problems += [row for row in merges if not row["ok"]]
        for row in merges:
            if not row["ok"]:
                print(f'?? {row["key"]:26s} {row["parts"]} parts should last '
                      f'{row["expected"]}s, lasts {row["seconds"]}s', flush=True)
        VERDICT.write_text(json.dumps({
            "checked": len(results) + len(merges), "clips": results, "merges": merges,
            "problems": problems}, ensure_ascii=False, indent=2) + "\n")
        print(f'\nrecorded clips: {sum(1 for r in results if r["ok"])}/{len(results)} pass; '
              f'merges: {sum(1 for m in merges if m["ok"])}/{len(merges)} pass')
        print(f'wrote {VERDICT.relative_to(ROOT)}')
        if problems:
            raise SystemExit(f'{len(problems)} clip(s) doubtful to a blind ear')
        return

    OUT.mkdir(parents=True, exist_ok=True)
    silence()
    state = json.loads(STATE.read_text()) if STATE.is_file() else {}
    lock = threading.Lock()
    counter = {"recorded": 0, "joined": 0, "cost": 0.0}

    def produce(clip: dict) -> None:
        mp3 = OUT / clip["audio"]
        native = clip["language"] == "pt" and clip["kind"] == "word"
        spoken_by = ELEVENLABS_VOICE if native else VOICE
        # A clip is only already done when the same text was said by the same voice.
        # Two voices say a word identically on paper and differently in the ear, so
        # the voice that is on record is part of what makes this skip safe.
        entry = state.get(clip["key"], {})
        if (mp3.is_file() and entry.get("speech") == clip["speech"]
                and entry.get("voice") == spoken_by
                and entry.get("say", clip["speech"]) == clip.get("say", clip["speech"])):
            return
        source = OUT / f'.{clip["audio"]}.{os.getpid()}.{threading.get_ident()}'
        if native:
            source = source.with_suffix(".mp3")
            source.write_bytes(speak_portuguese(clip["speech"]))
            inputs = ["-i", str(source)]
            voice, model, generation_id = ELEVENLABS_VOICE, ELEVENLABS_MODEL, None
            cost = len(said_as(clip["speech"])) / 1000 * ELEVENLABS_RATE
        else:
            pcm, content_type, generation_id = synthesize(clip.get("say", clip["speech"]))
            rate = re.search(r"rate=(\d+)", content_type)
            channels = re.search(r"channels=(\d+)", content_type)
            if not rate or not channels:
                raise RuntimeError(f'{clip["key"]}: unexpected content type {content_type!r}')
            source = source.with_suffix(".pcm")
            source.write_bytes(pcm)
            inputs = ["-f", "s16le", "-ar", rate.group(1), "-ac", channels.group(1),
                      "-i", str(source)]
            voice, model = VOICE, MODEL
            cost = generation_cost(generation_id)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
                        "-af", f"loudnorm={LOUDNESS}", "-codec:a", "libmp3lame",
                        "-qscale:a", "2", str(mp3)], check=True)
        source.unlink()
        with lock:
            state[clip["key"]] = {"speech": clip["speech"], "audio": clip["audio"],
                                  "say": clip.get("say", clip["speech"]),
                                  "model": model, "voice": voice, "duration": duration(mp3),
                                  "bytes": mp3.stat().st_size, "generation_id": generation_id,
                                  "cost": cost}
            counter["recorded"] += 1
            counter["cost"] += cost or 0.0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(produce, clips))
    def measure(path: Path) -> float | None:
        """A clip's length, or None when the file is missing or unreadable.

        A merge that died half way leaves an empty file behind, and probing it
        would stop the run before the new merge can overwrite it.
        """
        try:
            return duration(path) if path.is_file() else None
        except subprocess.CalledProcessError:
            return None

    for recipe in recipes:
        before = measure(OUT / recipe["audio"])
        join(recipe["sources"], OUT / recipe["audio"])
        counter["joined"] += 1
        after = duration(OUT / recipe["audio"])
        if before is not None and abs(before - after) > 0.01:
            print(f'  rebuilt {recipe["audio"]}: {before}s -> {after}s')
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f'recorded {counter["recorded"]} clip(s), joined {counter["joined"]} merge(s), '
          f'${counter["cost"]:.4f}')
    print(f'media in {OUT.relative_to(ROOT)}: '
          f'{len([f for f in OUT.iterdir() if f.suffix == ".mp3"])} files')


if __name__ == "__main__":
    main()
