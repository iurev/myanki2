#!/usr/bin/env python3
"""Independently verify every generated English clip with unprompted ASR.

The expected text is the book's embedded English translation, unmodified. TTS
engines sometimes skip a short inline parenthetical like "(the)", so a clip
also passes if it matches the same sentence with parentheticals dropped; which
of the two matched is recorded so the difference is never hidden.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PASS_RATIO = 0.85
PASS_RATIO_TYPED = 0.80
INVENTORY = ROOT / "tesouro" / "full-book-local" / "text-inventory.json"

NUMBER_WORDS = {"1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six",
                "7": "seven", "8": "eight", "9": "nine", "10": "ten", "11": "eleven",
                "12": "twelve", "15": "fifteen", "20": "twenty", "30": "thirty"}
# Providers punctuate and spell the same words differently: Whisper writes
# "All right" where the book prints "Alright", and "20" where it prints
# "twenty". Compare speech, not typography.
SPELLING_EQUIVALENTS = {"alright": "all right", "okay": "ok", "ok": "ok", "cannot": "can not"}

# Clips where both providers mishear a single word, checked against the clip and
# the text actually synthesised: see english-exceptions.json.
EXCEPTIONS_PATH = ROOT / "tesouro" / "full-book-local" / "english-exceptions.json"
EXCEPTIONS = json.loads(EXCEPTIONS_PATH.read_text()) if EXCEPTIONS_PATH.is_file() else {}


def normalize(text: str) -> list[str]:
    text = "".join(
        char for char in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(char) != "Mn"
    )
    text = re.sub(r"[^0-9a-z]+", " ", text)
    words = [NUMBER_WORDS.get(word, word) for word in text.split()]
    words = [SPELLING_EQUIVALENTS.get(word, word) for word in words]
    return [token for word in words for token in word.split()]


def drop_parentheticals(text: str) -> str:
    return re.sub(r"\([^)]*\)", " ", text)


def transcribe(audio: Path, cache: Path, model: str) -> dict:
    if cache.is_file():
        return json.loads(cache.read_text())
    body = {
        "model": model,
        "input_audio": {"data": base64.b64encode(audio.read_bytes()).decode(), "format": "mp3"},
        "language": "en",
    }
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/audio/transcriptions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"},
    )
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            result = json.load(urllib.request.urlopen(request, timeout=120))
            break
        except urllib.error.HTTPError as error:
            last_error = error
            # 429 means the account is over its concurrent request budget;
            # back off harder than for a transient network fault.
            time.sleep(5 * (attempt + 1) if error.code == 429 else 2 ** attempt)
        except Exception as error:
            last_error = error
            time.sleep(2 ** attempt)
    else:
        raise RuntimeError(f"ASR failed for {audio.name}: {last_error}")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def fuzzy_fraction(expected: list[str], heard: list[str]) -> float:
    """Share of expected words present, in order, allowing ASR mis-spellings.

    Proper nouns are where providers diverge most ("João" comes back as
    "Joel", "Zhouao", "Squown"), so a word counts as present when it is
    recognisably close rather than byte-identical.
    """
    if not expected:
        return 1.0
    cursor = 0
    matched = 0
    for word in expected:
        found = False
        probe = cursor
        while probe < len(heard):
            if SequenceMatcher(None, word, heard[probe], autojunk=False).ratio() >= 0.75:
                found = True
                cursor = probe + 1
                break
            probe += 1
        if found:
            matched += 1
    return matched / len(expected)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, default=ROOT / "tesouro" / "full-book-local" / "audio-en")
    parser.add_argument("--record", action="append", default=[])
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    records = json.loads(INVENTORY.read_text())
    if args.record:
        wanted = set(args.record)
        records = [r for r in records if r["id"] in wanted]

    cache_dir = args.audio.parent / "stt-en-unprompted"
    chirp_dir = args.audio.parent / "stt-en-chirp"
    report: list[dict] = []
    failures: list[str] = []
    lock = threading.Lock()

    def check(record: dict) -> None:
        sid = record["id"]
        audio = args.audio / f"{sid}.mp3"
        if not audio.is_file():
            with lock:
                failures.append(f"{sid}: missing {audio}")
            return
        expected = normalize(record["english_text"])
        stripped_expected = normalize(drop_parentheticals(record["english_text"]))
        readings = []
        for directory, model in (("whisper", "openai/whisper-large-v3"), ("chirp", "google/chirp-3")):
            cache = (cache_dir if directory == "whisper" else chirp_dir) / f"{sid}.json"
            heard = normalize(transcribe(audio, cache, model).get("text", ""))
            readings.append({
                "verbatim": SequenceMatcher(None, expected, heard, autojunk=False).ratio(),
                "parentheticals_dropped": SequenceMatcher(None, stripped_expected, heard, autojunk=False).ratio()
                if stripped_expected != expected else 0.0,
                "fuzzy": fuzzy_fraction(expected, heard),
                "length_ratio": len(heard) / max(1, len(expected)),
                "heard": heard,
            })
        # A reading is convincing when it reproduces the sentence, or when it
        # clearly carries the same words in the same order despite ASR
        # mis-spelling names.
        def convincing(reading: dict) -> bool:
            return (reading["verbatim"] >= PASS_RATIO
                    or reading["parentheticals_dropped"] >= PASS_RATIO
                    or (reading["fuzzy"] >= PASS_RATIO_TYPED and reading["length_ratio"] >= 0.7))
        best = max(readings, key=lambda reading: max(reading["verbatim"], reading["parentheticals_dropped"], reading["fuzzy"]))
        match_kind = None
        if best["verbatim"] >= PASS_RATIO:
            match_kind = "verbatim"
        elif best["parentheticals_dropped"] >= PASS_RATIO:
            match_kind = "parentheticals_dropped"
        elif best["fuzzy"] >= PASS_RATIO_TYPED and best["length_ratio"] >= 0.7:
            match_kind = "fuzzy_words"
        # The weaker provider must not be describing a different sentence.
        weakest = min(readings, key=lambda reading: reading["fuzzy"])
        consistent = weakest["fuzzy"] >= 0.6 or weakest["verbatim"] >= 0.6
        # Three clips are transcribed wrong by both providers on one word only
        # ("João" as "Joel", a lone leading "But" as "Good"/"Now", "tea" as
        # the letter "t"). Each was checked against the recording itself, in
        # english-exceptions.json, and each still has to carry the rest of the
        # sentence so a blank or wrong clip cannot pass this way.
        noted_exception = None
        if match_kind is None or not consistent:
            if sid in EXCEPTIONS and max(reading["fuzzy"] for reading in readings) >= 0.6:
                noted_exception = EXCEPTIONS[sid]
            else:
                with lock:
                    failures.append(f"{sid}: {[(round(r['verbatim'], 3), round(r['fuzzy'], 3), r['heard']) for r in readings]}")
                match_kind = None
        with lock:
            report.append({"id": sid, "matched": match_kind, "content_exception": noted_exception,
                           "verbatim": round(best["verbatim"], 3), "fuzzy": round(best["fuzzy"], 3),
                           "status": "PASS" if (match_kind or noted_exception) else "FAIL"})
            print(json.dumps({"id": sid, "matched": match_kind}), flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(check, records))

    report.sort(key=lambda row: row["id"])

    (args.audio.parent / "english-verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        print("\nFAILURES")
        print("\n".join(failures))
        raise SystemExit(1)
    print(f"\nPASS: {len(report)} English clips verified by independent ASR")


if __name__ == "__main__":
    main()
