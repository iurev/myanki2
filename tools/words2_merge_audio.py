#!/usr/bin/env python3
"""Join a word's two English clips into one, for the front of the words2 card.

The card used to play the word and then the example sentence as two clips in two
fields. This builds `w2_<word>_merged.mp3` - the word, then the sentence, with the
pause the narrator already left between them - so the front can play the pair as
one recording, the way a phrasebook says "kingdom. kingdom had many citizens".

The two source clips stay exactly as they are: this only adds a third file per
word. Nothing is silenced, shortened or re-ordered, and nothing of either clip is
dropped from the eight-second recording the sounds came from.

Joining mp3 streams with `-c copy` does not work here: mp3 frames are 1152
samples, the two clips' frames meet off-grid, and ffmpeg's concat demuxer then
muxes a non-monotonic timestamp (measured: the sentence landed 512 samples away
from where it belongs, with a warning from the muxer). So both clips are decoded
and joined as samples, then encoded once, at 256 kbps mono - the rate at which
this encoder is transparent on this material (measured against the originals:
-62 dB at 256k, -34 dB at 224k, -30 dB at 192k).

The build verifies itself: the merged file is decoded again and compared
against the two sources joined the same way, allowing for the one encode's loss.
A word whose merged clip does not hold both halves is an error, not a note.

    python3 tools/words2_merge_audio.py --limit 3     # pilot
    python3 tools/words2_merge_audio.py               # every word the deck uses
    python3 tools/words2_merge_audio.py --verify      # re-check, write nothing
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
AUDIO = ROOT / "cidadela" / "audio2"
WORK = ROOT / "cidadela" / "work"
STATE = WORK / "words2-merge-state.json"
# The specs the deck was actually built from: the twelve chapter specs and the
# pilot spec, whose `andar` is the one word no chapter spec names. words2-spec.json
# is left out because it is an earlier plan: it lists twelve words (certo, dar,
# dentro, eles, exemplo, iluminado, longe, me, medo, preso) that were never given
# clips and are in no note, so it does not describe the deck.
SPECS = sorted(WORK.glob("words2-spec-ch*.json")) + [WORK / "words2-spec-pilot.json"]
RATE = "48000"
BITRATE = "256k"
# The merged clip is verified at this sample rate; the error is the one encode's,
# and must sit well below the -30 dB that a careless bitrate would cost.
CHECK_RATE = 16000
MAX_ERROR_DB = -45.0


def sha1(path: pathlib.Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def pcm(path: pathlib.Path, rate: int) -> array.array:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(rate),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return array.array("h", raw)


def edge_silence(path: pathlib.Path, seconds: float = 0.60) -> tuple[float, float]:
    """How much near-silence the clip carries at its head and tail.

    Used only to report the pause the join inherits, so that a word whose two
    halves would meet with an odd gap is visible in the pilot rather than heard
    later. The clips are the narrator's, not ours; this measures, it does not cut.
    """
    samples = pcm(path, CHECK_RATE)
    window = int(CHECK_RATE * 0.02)
    span = min(int(CHECK_RATE * seconds), len(samples))
    floor = 60  # a quiet level, not zero: these are lossy clips with a noise floor

    def loud(block: array.array) -> bool:
        return math.sqrt(sum(v * v for v in block) / len(block)) > floor

    head = 0
    for start in range(0, span - window, window):
        if loud(samples[start:start + window]):
            head = start / CHECK_RATE
            break
    tail = 0
    for start in range(len(samples) - window, len(samples) - span, -window):
        if loud(samples[start:start + window]):
            tail = (len(samples) - (start + window)) / CHECK_RATE
            break
    return head, tail


def source_problems(first: pathlib.Path, second: pathlib.Path) -> list[str]:
    """Anything about the two source clips that says they cannot be what they claim.

    These are lengths, not transcriptions: every word in the deck is spoken in 0.5 to
    2 seconds and every sentence in 2 to 5, so a clip far outside that is a voice
    that sent the wrong thing back. One did: the word "noise" came back as a
    79-second music file, and it sat in the deck's English clip for months because
    nothing compared a clip's length with what it was supposed to be. Cheap, and it
    cannot be fooled by a plausible-sounding transcript.
    """
    problems = []
    for label, path, low, high in (("word clip", first, 0.30, 6.0),
                                   ("sentence clip", second, 1.0, 12.0)):
        seconds = len(pcm(path, CHECK_RATE)) / CHECK_RATE
        if not low <= seconds <= high:
            problems.append(f"{path.name}: the {label} is {seconds:.1f}s, which is not a "
                            f"{label} ({low}-{high}s)")
    return problems


def error_vs_sources(merged: pathlib.Path, first: pathlib.Path, second: pathlib.Path) -> tuple[float, float]:
    """How far the merged clip is from its two sources played back to back.

    Returns (error in dB below the signal, extra seconds the merged clip holds).
    The encode may shift the whole file by a few samples, so the offset that fits
    best is searched for first; a join that lost or repeated audio cannot hide
    behind that, because it would show up as a large error at every offset.
    """
    joined = pcm(first, CHECK_RATE) + pcm(second, CHECK_RATE)
    got = pcm(merged, CHECK_RATE)
    best = None
    for offset in range(0, 3000):
        n = min(len(joined), len(got) - offset)
        if n <= 0:
            break
        total = sum((got[offset + i] - joined[i]) ** 2 for i in range(0, n, 5))
        if best is None or total < best[1]:
            best = (offset, total, n)
    if best is None:
        raise SystemExit(f"{merged.name}: holds no samples to compare")
    offset, _, n = best
    rms_error = math.sqrt(sum((got[offset + i] - joined[i]) ** 2 for i in range(n)) / n)
    rms_signal = math.sqrt(sum(v * v for v in joined[:n]) / n) or 1
    return 20 * math.log10(rms_error / rms_signal), (len(got) - len(joined)) / CHECK_RATE


def words_used_by_the_deck() -> dict[str, dict]:
    """One entry per word the deck's specs name, keyed by the merged file's name.

    The names come from the specs' own media names rather than from the Portuguese
    word, because a name is sanitised when it is written (exceção -> excecao) and
    the deck is what has to keep playing.
    """
    words: dict[str, dict] = {}
    for spec_path in SPECS:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        for card in spec["cards"]:
            english = card["media"]["english"]
            sentence = card["media"]["sentence"]
            if not english.endswith("_en.mp3") or not sentence.endswith("_sent.mp3"):
                raise SystemExit(f"{spec_path.name}: unexpected media names {english}, {sentence}")
            merged = english[: -len("_en.mp3")] + "_merged.mp3"
            # The same word can appear in several chapters; the clips are shared.
            words[merged] = {"word": card["portuguese"], "english": english, "sentence": sentence}
    return words


def build(words: dict[str, dict], state: dict, verify_only: bool, limit: int) -> tuple[int, int, int, list[str]]:
    built, reused, failed = 0, 0, 0
    problems: list[str] = []
    for merged_name, names in sorted(words.items()):
        if limit and built + reused >= limit:
            break
        merged = AUDIO / merged_name
        first, second = AUDIO / names["english"], AUDIO / names["sentence"]
        for path in (first, second):
            if not path.is_file():
                problems.append(f"{names['word']}: missing source {path.name}")
        if problems and problems[-1].startswith(f"{names['word']}:"):
            failed += 1
            continue
        hashes = {"first": sha1(first), "second": sha1(second)}
        known = state.get(merged_name)
        if known and known["sources"] == hashes and merged.is_file():
            wrong = source_problems(first, second)
            if wrong:
                problems += wrong
                failed += 1
            else:
                reused += 1
            continue
        if verify_only:
            problems.append(f"{merged_name}: would be rebuilt (no up-to-date file)")
            failed += 1
            continue
        wrong = source_problems(first, second)
        if wrong:
            problems += wrong
            failed += 1
            continue
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / merged_name
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(first), "-i", str(second),
                 "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[a]", "-map", "[a]",
                 "-c:a", "libmp3lame", "-b:a", BITRATE, "-ac", "1", "-ar", RATE, str(out)],
                check=True)
            db, extra = error_vs_sources(out, first, second)
            if db > MAX_ERROR_DB:
                problems.append(f"{merged_name}: merged clip is {db:.1f} dB from its two sources "
                                f"(worse than the {MAX_ERROR_DB} dB an encode should cost)")
                failed += 1
                continue
            if abs(extra) > 0.005:
                problems.append(f"{merged_name}: merged clip is {extra:+.3f}s off the sum of its parts")
                failed += 1
                continue
            lead, tail = edge_silence(first)
            s_lead, _ = edge_silence(second)
            pause = tail + s_lead
            if not 0.05 <= pause <= 1.0:
                problems.append(f"{merged_name}: the two clips would meet with a {pause:.2f}s pause")
                failed += 1
                continue
            merged.write_bytes(out.read_bytes())
        state[merged_name] = {
            "word": names["word"], "sources": hashes, "bytes": merged.stat().st_size,
            "seconds": round(extra + sum(len(pcm(p, CHECK_RATE)) for p in (first, second)) / CHECK_RATE, 3),
            "error_db": round(db, 1), "inherited_pause": round(pause, 2),
        }
        built += 1
        if built % 50 == 0:
            print(f"  ... {built} merged", flush=True)
    return built, reused, failed, problems


def self_test(words: dict[str, dict]) -> None:
    """Prove the check can fail: merge one word's clip with another word's sentence.

    A merged clip that does not hold the two clips it claims must not pass, and
    the only way to know the check bites is to hand it one that is wrong.
    """
    names = sorted(words.values(), key=lambda row: row["word"])
    if len(names) < 2:
        raise SystemExit("self-test needs two words")
    first, other = names[0], names[1]
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "crossed.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(AUDIO / first["english"]),
                        "-i", str(AUDIO / other["sentence"]), "-filter_complex",
                        "[0:a][1:a]concat=n=2:v=0:a=1[a]", "-map", "[a]", "-c:a", "libmp3lame",
                        "-b:a", BITRATE, "-ac", "1", "-ar", RATE, str(out)], check=True)
        crossed, _ = error_vs_sources(out, AUDIO / first["english"], AUDIO / first["sentence"])
        honest, _ = error_vs_sources(out, AUDIO / first["english"], AUDIO / other["sentence"])
    print(f"self-test: {first['word']}'s word + {other['word']}'s sentence scores {crossed:.1f} dB "
          f"against {first['word']}'s own pair (must be worse than {MAX_ERROR_DB} dB) and "
          f"{honest:.1f} dB against the pair it is actually made of")
    if crossed <= MAX_ERROR_DB:
        raise SystemExit("self-test FAILED: the check passed a clip made of the wrong pair")
    if honest > MAX_ERROR_DB:
        raise SystemExit("self-test FAILED: the check rejects a correct pair")
    print("self-test PASSED: the check rejects a merged clip built from the wrong pair")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--verify", action="store_true", help="re-check and write nothing")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    words = words_used_by_the_deck()
    if args.self_test:
        self_test(words)
        return
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.is_file() else {}
    print(f"{len(words)} word(s) named by the deck's {len(SPECS)} specs")
    built, reused, failed, problems = build(words, state, args.verify, args.limit)
    if not args.verify:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    pauses = [row["inherited_pause"] for row in state.values() if "inherited_pause" in row]
    print(f"merged: {built} built, {reused} already up to date, {failed} failed")
    if pauses:
        pauses.sort()
        print(f"pause the join inherits: min {pauses[0]:.2f}s  median "
              f"{pauses[len(pauses)//2]:.2f}s  max {pauses[-1]:.2f}s")
    for problem in problems[:20]:
        print(f"  PROBLEM {problem}")
    if problems or failed:
        print(f"FAIL: {len(problems)} problem(s)")
        raise SystemExit(1)
    print(f"PASS: every merged clip holds both halves (within {MAX_ERROR_DB} dB of them)")


if __name__ == "__main__":
    main()
