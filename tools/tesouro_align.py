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

import numpy as np

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
# {(chapter, id): (start, end)} -- raw times, before refine_boundaries().
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

# Fixed/gap-proportional padding (both earlier approaches) guesses an offset
# instead of looking at the actual audio, and a systematic check across all
# 312 cut clips found 41% ending mid-sound and 11% starting mid-sound
# (bleeding the previous sentence's tail in). Guessing a pad amount can never
# reliably work across varying speech rates and pause lengths. Fixed below by
# actually detecting silence in the source audio around each boundary --
# see refine_boundaries().
SR = 16000
FRAME_MS = 10
FRAME_LEN = SR * FRAME_MS // 1000
# "Silence" is relative to *this word's own* peak volume, not a chapter-wide
# floor: a global percentile gets dragged down to near-absolute-zero by true
# digital silence elsewhere in the file (before the chapter title, etc),
# giving a threshold nothing in a real inter-sentence gap ever crosses.
RELATIVE_MARGIN_DB = 20   # "speech" = within this many dB of the word's own peak
MIN_SILENCE_MS = 80        # sustained silence needed to call a gap real
ANCHOR_WINDOW = 0.15       # tight window right at the raw boundary, used to confirm
                           # and locate real speech before searching outward from it
END_SEARCH_AFTER = 1.2     # how far past the anchor we search for trailing silence
START_SEARCH_BEFORE = 0.4  # how far before the anchor we search for leading silence
END_BUFFER = 0.04          # small trailing silence left after the cut, for a clean stop
START_BUFFER = 0.04        # small lead-in silence left before the cut


def load_envelope(chapter: int) -> np.ndarray:
    """Per-10ms-frame RMS (dB) for the whole chapter, for boundary refinement."""
    mp3 = SOURCE_DIR / f"Storyglot-O_Tesouro_Submerso_chpt{chapter}.mp3"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-f", "s16le", "-ar", str(SR), "-ac", "1", "pipe:1"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    n_frames = len(samples) // FRAME_LEN
    frames = samples[: n_frames * FRAME_LEN].reshape(n_frames, FRAME_LEN)
    rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-12)


def find_anchor(db: np.ndarray, lo: float, hi: float) -> tuple[int, float] | None:
    """Loudest frame in [lo, hi] (seconds), used both as the local "this is
    real speech" reference level and as a confirmed starting point to search
    outward from. None if the window is silent (no real speech found there
    at all -- e.g. whisper's raw timestamp landed in a gap)."""
    i0 = max(0, int(lo * SR / FRAME_LEN))
    i1 = min(len(db), int(hi * SR / FRAME_LEN))
    if i1 <= i0:
        return None
    peak_i = i0 + int(np.argmax(db[i0:i1]))
    return peak_i, float(db[peak_i])


def find_speech_offset(db: np.ndarray, anchor_i: int, after: float, threshold: float) -> float | None:
    """Search forward from a confirmed-speech anchor frame for where
    sustained silence begins (the true end of speech). None if not found
    within the window -- e.g. a long dramatic pause outlasts the search."""
    min_frames = max(1, MIN_SILENCE_MS // FRAME_MS)
    i1 = min(len(db), anchor_i + int(after * SR / FRAME_LEN))
    for i in range(anchor_i, i1 - min_frames):
        if np.all(db[i : i + min_frames] < threshold):
            return i * FRAME_LEN / SR
    return None


def find_speech_onset(db: np.ndarray, anchor_i: int, before: float, threshold: float) -> float | None:
    """Search backward from a confirmed-speech anchor frame for where the
    preceding silence gap ends (the true onset), i.e. the last silence run
    strictly before the anchor. None if not found within the window."""
    min_frames = max(1, MIN_SILENCE_MS // FRAME_MS)
    i0 = max(0, anchor_i - int(before * SR / FRAME_LEN))
    for i in range(anchor_i - min_frames, i0 - 1, -1):
        if np.all(db[i : i + min_frames] < threshold):
            return (i + min_frames) * FRAME_LEN / SR
    return None


def refine_boundaries(chapter: int, aligned: list[dict]) -> list[str]:
    """Replace each raw word-based start/end with the actual detected speech
    boundary in the source audio. Returns ids where no clear anchor/boundary
    was found (fell back to the raw timestamp) for the caller to flag."""
    db = load_envelope(chapter)
    fallback_ids = []

    for s in aligned:
        if s["start"] is None:
            continue

        # Anchor into *this sentence's own* audio first (forward from the raw
        # start, backward from the raw end -- never toward the neighboring
        # sentence), confirming real speech exists there, before searching
        # outward from that confirmed point. Searching a fixed window without
        # first anchoring on real speech risks landing entirely inside a
        # neighboring silence (e.g. a long dramatic pause) and misreading
        # "still silent way out here" as "the boundary."
        start_anchor = find_anchor(db, s["start"] - 0.05, s["start"] + ANCHOR_WINDOW)
        end_anchor = find_anchor(db, s["end"] - ANCHOR_WINDOW, s["end"] + 0.05)

        onset = offset = None
        if start_anchor is not None:
            anchor_i, peak_db = start_anchor
            onset = find_speech_onset(db, anchor_i, START_SEARCH_BEFORE, peak_db - RELATIVE_MARGIN_DB)
        if end_anchor is not None:
            anchor_i, peak_db = end_anchor
            offset = find_speech_offset(db, anchor_i, END_SEARCH_AFTER, peak_db - RELATIVE_MARGIN_DB)

        if onset is None or offset is None:
            fallback_ids.append(s["id"])
        s["start"] = max(0.0, (onset if onset is not None else s["start"]) - START_BUFFER)
        s["end"] = (offset if offset is not None else s["end"]) + END_BUFFER

    # Hard guarantee, independent of how good the detection above was: never
    # let two consecutive clips overlap. A missed detection on one side can
    # otherwise combine with a correct extension on the other into exactly
    # the "starts with sounds from the previous line" bleed this whole
    # rewrite exists to fix.
    prev_end = None
    for s in aligned:
        if s["start"] is None:
            continue
        if prev_end is not None and s["start"] < prev_end:
            s["start"] = prev_end
        prev_end = s["end"]

    return fallback_ids


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

    unmatched = [s for s in aligned if s["start"] is None]
    print(f"chapter {chapter}: {len(aligned)} sentences, sequence match ratio={aligned[0]['match_ratio'] if aligned else 0:.3f}")
    if unmatched:
        print(f"  UNMATCHED ({len(unmatched)}): {[s['id'] for s in unmatched]}")

    fallback_ids = refine_boundaries(chapter, aligned)
    if fallback_ids:
        print(f"  NO SILENCE FOUND, used fallback pad ({len(fallback_ids)}): {fallback_ids}")

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
