#!/usr/bin/env python3
"""Transcribe a Tesouro Submerso chapter MP3 with faster-whisper (word-level
timestamps), align the words against the known-correct sentence text, and cut
sentence-level clips with ffmpeg.

Unlike the old VAD-based cutter, timestamps come from a real ASR model
(large-v3) run on the full chapter for context, then each sentence's
boundaries are found by aligning the whisper word stream against the ground
truth from tesouro/alignment-ch01-10.csv (Portuguese text only; the old
start/end columns there are not trusted and are ignored).
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALIGNMENT_CSV = ROOT / "tesouro" / "alignment-ch01-10.csv"
SOURCE_DIR = ROOT / "tesouro" / "source"
CACHE_DIR = ROOT / "tesouro" / "whisper-cache"
AUDIO_DIR = ROOT / "tesouro" / "audio"

# Chapters where whisper's VAD gate silently drops real speech (confirmed by
# re-transcribing without it and recovering the missing sentences).
NO_VAD_CHAPTERS = {10}

# Rare hand-audited fixes for lines where the ground-truth text doesn't
# exactly match what whisper hears (e.g. because whisper mis-transcribes a
# fast/blended word even though its timestamp still lands on the right
# audio, or the audiobook narration genuinely diverges from the book text).
# {(chapter, id): (start, end)} -- raw times, before apply_padding().
MANUAL_OVERRIDES: dict[tuple[int, str], tuple[float, float]] = {
    # "Tem a certeza?" heard by whisper as "Tenha certeza." (phonetically
    # close blend); only "certeza" got an equal-anchor, truncating the
    # start. Manually verified from the raw word timestamps.
    (4, "ts0080"): (58.22, 60.0),
    # "Porque é que..." -- whisper split "Porque" into two tokens "Por" +
    # "que", so the target's single "porque" token never equal-matched and
    # the cut started one word late. Manually verified from raw timestamps.
    (9, "ts0297"): (117.59, 123.05),
}

# Whisper's word-end timestamp for a vowel-final word is often measurably
# early, and Portuguese sentences overwhelmingly end in vowels -- confirmed
# by ear on ts0001: "biólog[o]" cut half-heard even with 0.11-0.15s of
# gap-proportional trailing pad (the earlier approach, which capped the pad
# at half the natural inter-sentence gap). Fix: always add a *fixed* pad
# regardless of neighbor timing, so the trailing edge isn't held hostage to
# however much silence happens to exist -- but bound how far that's allowed
# to overshoot the actual gap, so a rare near-zero-gap sentence can't
# swallow a neighbor's entire next word. A guaranteed 0.15s minimum trailing
# pad even at zero gap, up to the full 0.22s when there's room, is a much
# better tradeoff than the previous proportional split: a listening
# flashcard bleeding a faint fraction of a neighboring word is a minor,
# often inaudible cost; a clipped target word is not.
START_PAD = 0.06
END_PAD = 0.22
OVERSHOOT_ALLOWANCE = 0.15  # how far the pad may exceed the measured gap


def normalize(tok: str) -> str:
    tok = unicodedata.normalize("NFC", tok)
    tok = tok.strip().strip(".,!?;:—–“”\"'()…").lower()
    # Word-initial 'h' is always silent in Portuguese, so spelling variants
    # like "Hei"/"Ei" are the same sound; applied symmetrically to both
    # target and whisper tokens (same function), so it can't cause a false
    # match, only recover ones that were falsely blocked by spelling alone.
    if len(tok) > 1 and tok[0] == "h":
        tok = tok[1:]
    return tok


@dataclass
class Word:
    text: str
    start: float
    end: float
    prob: float


def load_targets(chapter: int) -> list[tuple[str, str]]:
    """Return [(id, text), ...] for one chapter, in book order."""
    rows = []
    with ALIGNMENT_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if int(row["chapter"]) == chapter:
                rows.append((row["id"], row["text"]))
    return rows


def transcribe_chapter(chapter: int) -> list[Word]:
    """Transcribe the full chapter mp3, cache the word list to JSON."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"ch{chapter:02d}.json"
    if cache_path.is_file():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return [Word(**w) for w in data]

    from faster_whisper import WhisperModel

    model = WhisperModel("large-v3", device="cuda", compute_type="float16")
    mp3 = SOURCE_DIR / f"Storyglot-O_Tesouro_Submerso_chpt{chapter}.mp3"
    # VAD is needed for most chapters (without it, whisper's long-form
    # decoder can drift/skip large stretches after a silence -- confirmed
    # this broke chapter 1). But VAD itself misfired on chapter 10, silently
    # gating out ~40s of real speech there. Neither setting is safe for
    # every chapter, so it's an explicit per-chapter override.
    use_vad = chapter not in NO_VAD_CHAPTERS
    segments, _info = model.transcribe(str(mp3), language="pt", word_timestamps=True, vad_filter=use_vad)

    words: list[Word] = []
    for seg in segments:
        for w in seg.words:
            words.append(Word(text=w.word.strip(), start=w.start, end=w.end, prob=w.probability))

    cache_path.write_text(
        json.dumps([w.__dict__ for w in words], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return words


CONF_THRESHOLD = 0.45  # drop hallucinated words (e.g. filler heard during silence)


def align_chapter(chapter: int) -> list[dict]:
    """Return per-sentence dicts: id, text, start, end, match_ratio."""
    targets = load_targets(chapter)
    words = [w for w in transcribe_chapter(chapter) if w.prob >= CONF_THRESHOLD]

    # Flatten target text into a token stream, remembering each sentence's
    # token index range so we can map back after the sequence alignment.
    target_tokens: list[str] = []
    sentence_ranges: list[tuple[int, int]] = []  # [start_idx, end_idx) into target_tokens
    for _id, text in targets:
        # Split on hyphens too: compounds like "caravela-portuguesa" and
        # clitic forms like "chama-se" are spoken as separate syllables and
        # whisper never emits the literal hyphen, so keeping it as one
        # token means it can never get an equal-match anchor.
        toks = [normalize(p) for w in text.split() for p in w.split("-")]
        toks = [t for t in toks if t]
        start_idx = len(target_tokens)
        target_tokens.extend(toks)
        sentence_ranges.append((start_idx, len(target_tokens)))

    whisper_tokens = [normalize(w.text) for w in words]

    sm = SequenceMatcher(None, target_tokens, whisper_tokens, autojunk=False)
    opcodes = sm.get_opcodes()

    # Build a mapping target_idx -> whisper_idx. Only trust 'equal' opcode
    # blocks (exact token matches) as anchors -- 'replace' blocks pair up
    # target/whisper spans positionally with no guarantee the text actually
    # corresponds (e.g. can map "O" to an unrelated "2"), which produced
    # wildly wrong boundaries in practice. Anything not exactly matched is
    # left unmapped and resolved by the nearest-neighbor fallback below,
    # which only ever lands on a trusted 'equal' anchor.
    target_to_whisper: dict[int, int] = {}
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for offset in range(i2 - i1):
                target_to_whisper[i1 + offset] = j1 + offset

    def nearest_whisper_idx(target_idx: int, forward: bool) -> int | None:
        idx = target_idx
        n = len(target_tokens)
        while 0 <= idx < n:
            if idx in target_to_whisper:
                return target_to_whisper[idx]
            idx += 1 if forward else -1
        return None

    results = []
    ratio = sm.ratio()
    for (sid, text), (t_start, t_end) in zip(targets, sentence_ranges):
        if (chapter, sid) in MANUAL_OVERRIDES:
            start, end = MANUAL_OVERRIDES[(chapter, sid)]
            results.append({"id": sid, "text": text, "start": start, "end": end, "match_ratio": ratio})
            continue
        first_w = nearest_whisper_idx(t_start, forward=True)
        last_w = nearest_whisper_idx(t_end - 1, forward=False)
        if first_w is None or last_w is None or first_w > last_w:
            results.append({"id": sid, "text": text, "start": None, "end": None, "match_ratio": 0.0})
            continue
        results.append(
            {
                "id": sid,
                "text": text,
                "start": words[first_w].start,
                "end": words[last_w].end,
                "match_ratio": ratio,
            }
        )
    return results


def apply_padding(aligned: list[dict]) -> None:
    """Pad each sentence boundary. See START_PAD/END_PAD/OVERSHOOT_ALLOWANCE comment."""
    for i, s in enumerate(aligned):
        if s["start"] is None:
            continue
        prev_end = aligned[i - 1]["end"] if i > 0 and aligned[i - 1]["end"] is not None else 0.0
        next_start = (
            aligned[i + 1]["start"] if i + 1 < len(aligned) and aligned[i + 1]["start"] is not None else s["end"] + 10
        )
        gap_before = max(0.0, s["start"] - prev_end)
        gap_after = max(0.0, next_start - s["end"])
        s["start"] = max(0.0, s["start"] - min(START_PAD, gap_before + OVERSHOOT_ALLOWANCE))
        s["end"] = s["end"] + min(END_PAD, gap_after + OVERSHOOT_ALLOWANCE)


def cut_clips(chapter: int, aligned: list[dict]) -> None:
    mp3 = SOURCE_DIR / f"Storyglot-O_Tesouro_Submerso_chpt{chapter}.mp3"
    out_dir = AUDIO_DIR / f"ch{chapter:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for s in aligned:
        if s["start"] is None:
            continue
        out_path = out_dir / f"{s['id']}.mp3"
        duration = s["end"] - s["start"]
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", f"{s['start']:.3f}", "-i", str(mp3),
                "-t", f"{duration:.3f}",
                "-map", "0:a",
                "-acodec", "libmp3lame", "-qscale:a", "2",
                str(out_path),
            ],
            check=True,
        )


SUSPICIOUS_SEC_PER_WORD = 1.3  # flag clips whose duration/word-count implies a bad boundary


def flag_suspicious(aligned: list[dict]) -> list[dict]:
    flagged = []
    for s in aligned:
        if s["start"] is None:
            continue
        n_words = max(1, len(s["text"].split()))
        duration = s["end"] - s["start"]
        if duration / n_words > SUSPICIOUS_SEC_PER_WORD:
            flagged.append(s)
    return flagged


def main() -> None:
    chapter = int(sys.argv[1])
    aligned = align_chapter(chapter)
    apply_padding(aligned)

    unmatched = [s for s in aligned if s["start"] is None]
    print(f"chapter {chapter}: {len(aligned)} sentences, sequence match ratio={aligned[0]['match_ratio'] if aligned else 0:.3f}")
    if unmatched:
        print(f"  UNMATCHED ({len(unmatched)}): {[s['id'] for s in unmatched]}")
    for s in aligned:
        if s["start"] is None:
            print(f"  ! {s['id']}: NO MATCH -- {s['text']!r}")
        else:
            print(f"  {s['id']} [{s['start']:.2f}-{s['end']:.2f}] {s['text']}")

    suspicious = flag_suspicious(aligned)
    if suspicious:
        print(f"  SUSPICIOUS DURATION ({len(suspicious)}): {[s['id'] for s in suspicious]}")

    cut_clips(chapter, aligned)
    print(f"cut {len([s for s in aligned if s['start'] is not None])} clips into {AUDIO_DIR / f'ch{chapter:02d}'}")


if __name__ == "__main__":
    main()
