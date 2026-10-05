#!/usr/bin/env python3
"""Cut per-sentence Portuguese clips for Tesouro chapters using API ASR only.

No local speech libraries: the chapter is transcribed with Deepgram Nova 3 via
OpenRouter (word timestamps), the transcript is sequence-aligned against the
book's own Portuguese text, and the cut boundaries are placed inside the real
inter-word gaps so a clip can never contain a neighbouring sentence.

Chapters 1-10 are deliberately out of scope: their clips already exist and are
frozen (see ch01-10-portuguese-original-sha256.json).
"""
from __future__ import annotations

import argparse
import array
import base64
import json
import os
import re
import subprocess
import time
import unicodedata
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "tesouro" / "source"
INVENTORY = ROOT / "tesouro" / "full-book-local" / "text-inventory.json"
SPOKEN_VARIANTS = json.loads((ROOT / "tesouro" / "full-book-local" / "audio-text-variants.json").read_text())
# Hand-checked cut points, for clips whose chapter-level word times put the cut
# inside the sentence. Each was measured from the recording's energy envelope
# and confirmed by locating the sentence in a window transcription.
OVERRIDES = json.loads((ROOT / "tesouro" / "full-book-local" / "boundary-overrides.json").read_text())

MIN_LEAD = 0.075
MIN_TAIL = 0.150
# The validator re-measures margins with its own ASR. It under-reports the
# leading edge and can overshoot the trailing word end by ~0.26s, so aim well
# above the gates and let pad_to_margins add synthetic silence when a real gap
# is too tight.
TARGET_LEAD = 0.30
TARGET_TAIL = 0.60
# How far a boundary may reach when the sentence is joined to its neighbour
# with no silence of its own. Reaching too little clips a word; reaching too
# much carries the neighbour. A missing word is the worse defect, so this is
# generous, and the silence-snapping above is what keeps clean cases tight.
LEAD_PAD = 0.30
TAIL_PAD = 0.25
# How far outside a speech run an ASR word time may sit and still belong to it.
RUN_SLACK = 0.06
# A speech run that begins this much earlier than the matched word is merged
# with the previous sentence; do not snap to its edge or the clip would swallow
# the whole neighbouring sentence.
MAX_MERGED_REACH = 0.35
# Envelope frame length used to locate speech and silence.
FRAME_SECONDS = 0.01
# How far inside the surrounding silence the edge sits, so MP3 frame padding
# cannot reach the neighbouring word.
EDGE_INSET = 0.05
# Never place an edge exactly on a neighbouring word's timestamp: MP3 frames are
# ~26ms long, so a boundary on the boundary still drags the neighbour's first
# frames into the clip.
GUARD = 0.06
PAD_STEP = 0.03

NUMBER_WORDS = {"1": "um", "2": "dois", "3": "tres", "4": "quatro", "5": "cinco", "6": "seis",
                "7": "sete", "8": "oito", "9": "nove", "10": "dez", "20": "vinte"}
# The book prints "Hmm." and the narrator says "Hum"; fold those spellings so
# the filler still anchors instead of becoming an unmatched sentence.
ASR_EQUIVALENTS = {"hmm": "hum", "mm": "hum", "ahn": "han", "ah": "ha"}
# How many short words may be skipped while matching a sentence's tail (or
# head) to the transcript, and how long a skipped word may be.
SKIP_LIMIT = 3
SKIPPABLE_LENGTH = 4


def tokens(text: str) -> list[str]:
    text = "".join(
        char for char in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(char) != "Mn"
    )
    text = re.sub(r"[^0-9a-z]+", " ", text)
    normalized = [ASR_EQUIVALENTS.get(word, word) for word in text.split()]
    normalized = [NUMBER_WORDS.get(word, word) for word in normalized]
    return [word[1:] if len(word) > 1 and word.startswith("h") else word for word in normalized]


def transcribe(chapter: int, cache_dir: Path) -> dict:
    cache = cache_dir / f"ch{chapter:02d}.json"
    if cache.is_file():
        return json.loads(cache.read_text())
    source = SOURCE_DIR / f"Storyglot-O_Tesouro_Submerso_chpt{chapter}.mp3"
    body = {
        "model": "deepgram/nova-3",
        "input_audio": {"data": base64.b64encode(source.read_bytes()).decode(), "format": "mp3"},
        "language": "pt",
        "response_format": "verbose_json",
        "timestamp_granularities": ["word", "segment"],
    }
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/audio/transcriptions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"},
    )
    for attempt in range(5):
        try:
            result = json.load(urllib.request.urlopen(request, timeout=300))
            break
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def align_sentences(records: list[dict], words: list[dict]) -> list[dict]:
    """Map each sentence's tokens onto the ASR word stream in book order."""
    hyp_tokens: list[str] = []
    for word in words:
        hyp_tokens.extend(tokens(word["word"]))
    # Remember which ASR word each hypothesis token came from.
    hyp_owner: list[int] = []
    for index, word in enumerate(words):
        hyp_owner.extend([index] * len(tokens(word["word"])))

    target_tokens: list[str] = []
    ranges: list[tuple[int, int]] = []
    for record in records:
        sentence_tokens = tokens(record["portuguese_text"])
        ranges.append((len(target_tokens), len(target_tokens) + len(sentence_tokens)))
        target_tokens.extend(sentence_tokens)

    matcher = SequenceMatcher(None, target_tokens, hyp_tokens, autojunk=False)
    anchors: dict[int, int] = {}
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                anchors[i1 + offset] = j1 + offset

    def nearest(target_index: int, forward: bool) -> int | None:
        index = target_index
        while 0 <= index < len(target_tokens):
            if index in anchors:
                return anchors[index]
            index += 1 if forward else -1
        return None

    def fuzzy(left: str, right: str) -> float:
        return SequenceMatcher(None, left, right, autojunk=False).ratio()

    # Deepgram writes a proper noun differently from the book ("Victor" for the
    # book's "Vítor"), so that token never gets an equal anchor and the sentence
    # would end one word early. Walk the remaining unmatched tokens along the
    # ASR word stream and accept them when they are recognisably the same word.
    def extend(target_token: int, word_index: int, step: int) -> int | None:
        candidate = word_index + step
        if not 0 <= candidate < len(words):
            return None
        heard = tokens(words[hyp_owner[candidate]]["word"])
        if not heard:
            return None
        if max(fuzzy(target_tokens[target_token], token) for token in heard) >= 0.7:
            return candidate
        return None

    first_anchors: list[int | None] = []
    last_anchors: list[int | None] = []
    for start_token, end_token in ranges:
        first = next((index for index in range(start_token, end_token) if index in anchors), None)
        last = next((index for index in range(end_token - 1, start_token - 1, -1) if index in anchors), None)
        first_anchors.append(anchors[first] if first is not None else None)
        last_anchors.append(anchors[last] if last is not None else None)

    aligned: list[dict] = []
    previous_end_index = -1
    for position, (record, (start_token, end_token)) in enumerate(zip(records, ranges)):
        first = first_anchors[position]
        last = last_anchors[position]
        if first is None or last is None:
            aligned.append({"id": record["id"], "chapter": record["chapter"],
                            "portuguese_text": record["portuguese_text"],
                            "english_text": record["english_text"],
                            "audio_text_variants": SPOKEN_VARIANTS.get(record["id"], {}).get("variants", []),
                            "coverage": 0.0, "start": None, "end": None,
                            "first_word": None, "last_word": None})
            continue

        first_token = next(index for index in range(start_token, end_token) if index in anchors)
        last_token = next(index for index in range(end_token - 1, start_token - 1, -1) if index in anchors)

        # Leading tokens the ASR spelled differently, walking backwards. A block
        # of short words can be missing from the transcript ("com vida" heard
        # as one "convida"), so a failed token may be skipped for a later one.
        limit = previous_end_index + 1
        for token in range(first_token - 1, start_token - 1, -1):
            extended = None
            for candidate in range(token, max(token - SKIP_LIMIT, start_token - 1), -1):
                if candidate < token and len(target_tokens[candidate]) > SKIPPABLE_LENGTH:
                    break
                extended = extend(candidate, first, -1)
                if extended is not None and extended >= limit:
                    break
                extended = None
            if extended is None:
                break
            first = extended
        # Trailing tokens, walking forwards, never into the next sentence.
        next_first = next((value for value in first_anchors[position + 1:] if value is not None), None)
        ceiling = len(words) - 1 if next_first is None else next_first - 1
        for token in range(last_token + 1, end_token):
            extended = None
            for candidate in range(token, min(token + SKIP_LIMIT, end_token)):
                if candidate > token and len(target_tokens[candidate]) > SKIPPABLE_LENGTH:
                    break
                extended = extend(candidate, last, 1)
                if extended is not None and extended <= ceiling:
                    break
                extended = None
            if extended is None:
                break
            last = extended

        matched = sum(1 for index in range(start_token, end_token) if index in anchors)
        coverage = matched / max(1, end_token - start_token)
        row = {"id": record["id"], "chapter": record["chapter"],
               "portuguese_text": record["portuguese_text"],
               "english_text": record["english_text"],
               "audio_text_variants": SPOKEN_VARIANTS.get(record["id"], {}).get("variants", []),
               "coverage": round(coverage, 3), "start": None, "end": None,
               "first_word": None, "last_word": None}
        if first <= last:
            if first <= previous_end_index:
                first = previous_end_index + 1
            if first <= last:
                row["first_word"] = hyp_owner[first]
                row["last_word"] = hyp_owner[last]
                row["start"] = words[row["first_word"]]["start"]
                row["end"] = words[row["last_word"]]["end"]
                previous_end_index = last
        aligned.append(row)
    return aligned, round(matcher.ratio(), 3)


def chapter_envelope(source: Path) -> tuple[list[tuple[int, int]], float]:
    """Find the chapter's speech runs from a short-frame energy envelope.

    ASR word times are a starting point, not ground truth: a word's reported
    onset can be late (clipping "Porque"), its offset early (clipping "com
    vida"), and its reverb tail runs past it. Snapping each cut edge to real
    silence removes all three failure modes at once.
    """
    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(source), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"])
    samples = array.array("h")
    samples.frombytes(raw)
    step = int(16000 * FRAME_SECONDS)
    frames = []
    for offset in range(0, len(samples) - step + 1, step):
        chunk = samples[offset:offset + step]
        frames.append((sum(value * value for value in chunk) / step) ** 0.5)
    if not frames:
        return [], 0.0
    threshold = max(25.0, max(frames) * 0.03)
    runs: list[tuple[int, int]] = []
    start = None
    for index, value in enumerate(frames):
        if value > threshold:
            if start is None:
                start = index
        elif start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(frames) - 1))
    return runs, threshold


def run_containing(runs: list[tuple[int, int]], frame: int) -> tuple[int, int] | None:
    """Find the speech run at a frame, tolerating a frame of slack.

    ASR word times land slightly outside the run they belong to, and missing by
    one frame would fall back to a fixed pad and slice the word's own decay.
    """
    slack = int(RUN_SLACK / FRAME_SECONDS)
    best = None
    for start, end in runs:
        if start - slack <= frame <= end + slack:
            distance = 0 if start <= frame <= end else min(abs(frame - start), abs(frame - end))
            if best is None or distance < best[0]:
                best = (distance, (start, end))
    return best[1] if best else None


def boundary_times(words: list[dict], index: int, is_start: bool,
                   runs: list[tuple[int, int]]) -> float:
    """Place a cut edge just outside the speech run holding the matched word.

    The edge sits in real silence, so a clip cannot carry the previous word's
    reverb tail and cannot slice the first or last word of its own sentence.
    When the neighbouring sentence is joined to this one with no silence, fall
    back to a short fixed pull-back from the word instead of reaching deep into
    the shared run.
    """
    if is_start:
        word_start = words[index]["start"]
        run = run_containing(runs, int(word_start / FRAME_SECONDS))
        if run is not None and run[0] * FRAME_SECONDS >= word_start - MAX_MERGED_REACH:
            candidate = run[0] * FRAME_SECONDS - EDGE_INSET
        else:
            candidate = word_start - LEAD_PAD
        if index > 0:
            candidate = max(candidate, words[index - 1]["end"] + GUARD)
        return max(0.0, min(candidate, word_start - 0.02))
    word_end = words[index]["end"]
    run = run_containing(runs, int(word_end / FRAME_SECONDS))
    if run is not None and run[1] * FRAME_SECONDS <= word_end + MAX_MERGED_REACH:
        candidate = run[1] * FRAME_SECONDS + EDGE_INSET
    else:
        candidate = word_end + TAIL_PAD
    if index < len(words) - 1:
        candidate = min(candidate, words[index + 1]["start"] - GUARD)
    return max(candidate, word_end + 0.02)


def cut(clip: Path, source: Path, start: float, end: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", str(source),
         "-t", f"{end - start:.3f}", "-map", "0:a", "-acodec", "libmp3lame", "-qscale:a", "2", str(clip)],
        check=True,
    )


def pad_to_margins(clip: Path, lead: float, tail: float) -> tuple[float, float]:
    """Add synthetic silence when a tight gap cannot provide the margins.

    Only silence is added: no extra speech can enter the clip.
    """
    add_lead = max(0.0, TARGET_LEAD - lead)
    add_tail = max(0.0, TARGET_TAIL - tail)
    if add_lead <= 0 and add_tail <= 0:
        return lead, tail
    tmp = clip.with_suffix(".padded.mp3")
    filters = []
    if add_lead > 0:
        filters.append(f"adelay={int(add_lead * 1000)}:all=1")
    if add_tail > 0:
        filters.append(f"apad=pad_dur={add_tail:.3f}")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip), "-af", ",".join(filters),
         "-acodec", "libmp3lame", "-qscale:a", "2", str(tmp)],
        check=True,
    )
    tmp.replace(clip)
    return lead + add_lead, tail + add_tail


def process_chapter(chapter: int, out_root: Path, dry_run: bool) -> dict:
    records = [r for r in json.loads(INVENTORY.read_text()) if r["chapter"] == chapter]
    source = SOURCE_DIR / f"Storyglot-O_Tesouro_Submerso_chpt{chapter}.mp3"
    cache_dir = out_root / "asr-deepgram"
    result = transcribe(chapter, cache_dir)
    words = result.get("words") or []
    if not words:
        raise RuntimeError(f"chapter {chapter}: no word timestamps")
    aligned, ratio = align_sentences(records, words)
    runs, _ = chapter_envelope(source)
    package = out_root / f"ch{chapter:02d}"
    package.mkdir(parents=True, exist_ok=True)
    manifest = []
    unmatched = [row["id"] for row in aligned if row["start"] is None]
    for row in aligned:
        if row["start"] is None:
            continue
        start = boundary_times(words, row["first_word"], True, runs)
        end = boundary_times(words, row["last_word"], False, runs)
        override = OVERRIDES.get(row["id"])
        if override:
            start, end = override["cut"]
            row["start"], row["end"] = override["span"]
        start = max(0.0, min(start, row["start"]))
        end = max(end, row["end"])
        if end - start <= 0.05:
            raise RuntimeError(f"{row['id']}: degenerate cut {start:.3f}-{end:.3f}")
        clip = package / f"{row['id']}.mp3"
        if not dry_run:
            cut(clip, source, start, end)
            lead, tail = pad_to_margins(clip, row["start"] - start, end - row["end"])
            duration = float(subprocess.check_output(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)],
                text=True).strip())
        else:
            lead, tail, duration = row["start"] - start, end - row["end"], end - start
        manifest.append({
            **row,
            "source": str(source.relative_to(ROOT)),
            "start": round(start, 3), "end": round(end, 3),
            # The ASR word span, kept alongside the cut edges so a validator can
            # tell how much non-sentence audio each edge actually carries.
            "word_start": round(row["start"], 3), "word_end": round(row["end"], 3),
            "duration": round(duration, 3),
            "lead": round(lead, 3), "tail": round(tail, 3),
        })
    if not dry_run:
        (package / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {"chapter": chapter, "records": len(records), "cut": len(manifest),
            "sequence_ratio": ratio, "unmatched": unmatched,
            "min_coverage": min((row["coverage"] for row in manifest), default=0)}


def parse_chapters(text: str) -> list[int]:
    chapters: list[int] = []
    for part in text.split(","):
        if "-" in part:
            low, high = part.split("-")
            chapters.extend(range(int(low), int(high) + 1))
        else:
            chapters.append(int(part))
    return chapters


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapters", default="11-30")
    parser.add_argument("--out", type=Path, default=ROOT / "tesouro" / "full-book-local")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    for chapter in parse_chapters(args.chapters):
        stats = process_chapter(chapter, args.out, args.dry_run)
        print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
