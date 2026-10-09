#!/usr/bin/env python3
"""Cut A Cidadela Misteriosa into per-sentence Portuguese clips (deck listening2).

The book is one 71-minute MP3 with no chapter marks, so the chapters are located
first from the timestamps its own EPUB prints ("áudio 05:04"), cut out of the
whole file, and only those minutes are ever sent for transcription. Nothing
transcribes the whole book, and nothing transcribes it twice: responses are
cached per chapter.

Boundary placement, silence snapping and padding come from the Tesouro cutter
(``tesouro_align_api``), which is the tested implementation of all three. Only
the paths and the record shape are this book's.

    python3 tools/cidadela_align.py --chapters 1-5 --probe      # transcribe, do not cut
    python3 tools/cidadela_align.py --chapters 1-5              # cut the clips
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tesouro_align_api as core  # noqa: E402 - the tested cutting core, reused as is

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "cidadela" / "source"
INVENTORY = ROOT / "cidadela" / "work" / "text-inventory.json"
DIVERGENCES = ROOT / "cidadela" / "work" / "part-divergences.json"
OVERRIDES_PATH = ROOT / "cidadela" / "work" / "boundary-overrides.json"
WORK = ROOT / "cidadela" / "work"
AUDIO = ROOT / "cidadela" / "audio"

# The narrator reads the printed Portuguese; unlike Tesouro there are no spoken
# variants to fold in, so the cutting core needs no variant table.
# The cutting core resolves ``tokens`` at call time, so an aligned sentence's
# tokens and the transcript's tokens can both be brought under this book's
# spellings. "Porquê?" is printed as one word but spoken as two ("Por" + "quê?");
# left un-folded, the sentence's last word never anchors and the clip is cut
# without it (this is exactly how cm0194 lost its "Porquê?").
TOKEN_FOLDS = {"porque": ["por", "que"], "embaixo": ["em", "baixo"]}
_core_tokens = core.tokens


def merged_folds() -> dict[str, list[str]]:
    """Spellings the narration merges, discovered from the recording itself.

    The book writes reflexive verbs with a hyphen ("ri-se", "lembra-se") and the
    transcript writes what was said ("risse"). Left alone, the two never match,
    the sentence's tail token falls into the aligner's short-token skip, and the
    clip is cut without its last word -- which is how cm0209 lost its "ri-se".
    A word that begins with one half and ends with the other is taken as merged.
    """
    book = " ".join(record["portuguese_text"] for record in json.loads(INVENTORY.read_text()))
    halves = set()
    for first, second in re.findall(r"\b([A-Za-zÀ-ÿ]+)-([A-Za-zÀ-ÿ]+)\b", book):
        left, right = _core_tokens(first), _core_tokens(second)
        if left and right:
            halves.add((left[0], right[0]))
    folds: dict[str, list[str]] = {}
    for chapter in sorted({record["chapter"] for record in json.loads(INVENTORY.read_text())}):
        cached = WORK / "asr-deepgram" / f"ch{chapter:02d}.json"
        if not cached.is_file():
            continue
        for word in json.loads(cached.read_text()).get("words") or []:
            heard = _core_tokens(word["word"])
            if len(heard) != 1:
                continue
            token = heard[0]
            for left, right in halves:
                if token.startswith(left) and token.endswith(right) and len(token) <= len(left) + len(right) + 2:
                    folds[token] = [left, right]
    return folds


def tokens(text: str) -> list[str]:
    folded = []
    for token in _core_tokens(text):
        folded.extend(TOKEN_FOLDS.get(token, MERGED_FOLDS.get(token, [token])))
    return folded


core.SPOKEN_VARIANTS = {}
MERGED_FOLDS = merged_folds()
core.tokens = tokens
core.MIN_LEAD, core.MIN_TAIL = 0.075, 0.150


def asr_copy(chapter: int) -> Path:
    """A small mono copy of the chapter, for transcription only.

    The source audio is 330 kbps stereo, so a five-minute chapter is 17-22 MB and
    the transcription endpoint refuses it outright ("does not support large audio
    inputs"). Speech needs none of that: 16 kHz mono at 48 kbps is a couple of MB
    and transcribes identically. The clips themselves are always cut from the
    full-quality chapter file.
    """
    out = WORK / "asr-audio" / f"ch{chapter:02d}.mp3"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        # -map 0:a -vn: the source MP3 carries a 13 MB cover image, which would
        # otherwise ride along and make the "small" copy bigger than the audio.
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(SOURCE_DIR / f"ch{chapter:02d}.mp3"),
                        "-map", "0:a", "-vn", "-map_metadata", "-1",
                        "-ac", "1", "-ar", "16000", "-b:a", "48k", str(out)], check=True)
    return out


def transcribe(chapter: int, refresh: bool = False) -> dict:
    """Deepgram word timestamps for one chapter (a few minutes, not the book)."""
    cache = WORK / "asr-deepgram" / f"ch{chapter:02d}.json"
    if cache.is_file() and not refresh:
        return json.loads(cache.read_text())
    source = asr_copy(chapter)
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
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                 "Content-Type": "application/json"})
    for attempt in range(5):
        try:
            result = json.load(urllib.request.urlopen(request, timeout=600))
            break
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def heard_tokens(result: dict) -> list[str]:
    tokens_: list[str] = []
    for word in result.get("words") or []:
        tokens_.extend(tokens(word["word"]))
    return tokens_


def in_order_coverage(sentence: str, heard: list[str]) -> float:
    """Share of a sentence's tokens that appear in the transcript, in order.

    Used to ask a specific question of the audio: the two editions of this book
    differ in four sentences, and only the recording can say which one was
    narrated. A sentence that is really in the audio matches nearly all of its
    tokens; one that was never spoken matches only its commonest filler words.
    """
    wanted = tokens(sentence)
    if not wanted:
        return 1.0
    position, found = 0, 0
    for token in wanted:
        hit = None
        for index in range(position, len(heard)):
            if heard[index] == token or SequenceMatcher(None, heard[index], token, autojunk=False).ratio() >= 0.75:
                hit = index
                break
        if hit is not None:
            found += 1
            position = hit + 1
    return found / len(wanted)


def probe(chapters: list[int]) -> None:
    """Report what the audio says at the four places the editions disagree."""
    divergences = json.loads(DIVERGENCES.read_text())
    report = []
    for chapter in chapters:
        result = transcribe(chapter)
        heard = heard_tokens(result)
        rows = [d for d in divergences if d["chapter"] == chapter]
        for row in rows:
            for sentence in row["part_001_only"]:
                report.append({"chapter": chapter, "sentence": sentence,
                               "part_001_only_coverage": round(in_order_coverage(sentence, heard), 3)})
        print(json.dumps({"chapter": chapter, "words": len(heard),
                          "divergences": len(rows)}, ensure_ascii=False))
    print(json.dumps({"divergence_probe": report}, ensure_ascii=False, indent=2))


# The transcript splits words the book prints as one ("Numa" comes back as "Em"
# + "uma"; "numa poção" as "em uma porção"). The aligner anchors the sentence on
# the half it recognises and leaves the other half outside the span, so the clip
# is cut through a spoken word -- that is how cm0095 lost the start of "Numa"
# and cm0192 lost "poção". A transcript word that touches the span with no silence
# between and that no other sentence has claimed is part of the same spoken word.
CONTIGUOUS_SECONDS = 0.06


def settle_spans(aligned: list[dict], words: list[dict]) -> None:
    """Grow each sentence's span over unclaimed words touching its edges."""
    spans = [[row["first_word"], row["last_word"]] if row["first_word"] is not None else None
             for row in aligned]
    for position, span in enumerate(spans):
        if span is None:
            continue
        floor = spans[position - 1][1] if position > 0 and spans[position - 1] else -1
        ceiling = spans[position + 1][0] if position + 1 < len(spans) and spans[position + 1] else len(words)
        while span[0] - 1 > floor and words[span[0] - 1]["end"] >= words[span[0]]["start"] - CONTIGUOUS_SECONDS:
            span[0] -= 1
        while span[1] + 1 < ceiling and words[span[1] + 1]["start"] <= words[span[1]]["end"] + CONTIGUOUS_SECONDS:
            span[1] += 1
    for row, span in zip(aligned, spans):
        if span is None:
            continue
        row["first_word"], row["last_word"] = span
        row["start"], row["end"] = words[span[0]]["start"], words[span[1]]["end"]


def process_chapter(chapter: int, dry_run: bool) -> dict:
    records = [r for r in json.loads(INVENTORY.read_text()) if r["chapter"] == chapter]
    source = SOURCE_DIR / f"ch{chapter:02d}.mp3"
    result = transcribe(chapter)
    words = result.get("words") or []
    if not words:
        raise RuntimeError(f"chapter {chapter}: no word timestamps returned")
    aligned, ratio = core.align_sentences(records, words)
    settle_spans(aligned, words)
    runs, _ = core.chapter_envelope(source)
    overrides = json.loads(OVERRIDES_PATH.read_text()) if OVERRIDES_PATH.is_file() else {}

    # Place the cut edges first, then settle them against each other: two
    # sentences can be run together so tightly that the independently chosen
    # edges cross by a frame, which would put the same audio in two clips.
    spans = []
    for row in aligned:
        override = overrides.get(row["id"])
        if row["start"] is None and not override:
            continue
        if row["start"] is None:
            # A sentence the transcript never anchored at all — a one-word
            # exclamation Deepgram did not transcribe — cannot be placed from
            # words that are not there, so both edges and the span come from the
            # override. It has no token coverage by definition, and is kept out
            # of the chapter's min_coverage, which describes the ASR alignment.
            row["start"] = override["span_start"]
            row["end"] = override["span_end"]
            row["coverage"] = None
            row["hand_cut"] = True
            spans.append((row, max(0.0, min(override["cut_start"], row["start"])), max(override["cut_end"], row["end"])))
            continue
        start = core.boundary_times(words, row["first_word"], True, runs)
        end = core.boundary_times(words, row["last_word"], False, runs)
        if override:
            # Overrides may move either edge alone: some corrections are a single
            # missed word ("Ah!" in cm0100) and pinning the other edge by hand
            # would freeze a number the aligner still owns.
            start = override.get("cut_start", override.get("cut", [start, end])[0])
            end = override.get("cut_end", override.get("cut", [start, end])[1])
            row["start"] = override.get("span_start", override.get("span", [row["start"], row["end"]])[0])
            row["end"] = override.get("span_end", override.get("span", [row["start"], row["end"]])[1])
        spans.append((row, max(0.0, min(start, row["start"])), max(end, row["end"])))
    for index in range(len(spans) - 1):
        row, start, end = spans[index]
        following, next_start, _ = spans[index + 1]
        if end <= next_start:
            continue
        middle = (end + next_start) / 2
        if middle < row["end"] - 1e-6 or middle > following["start"] + 1e-6:
            raise RuntimeError(f"{row['id']}/{following['id']}: crossing cuts cannot be settled without clipping a word")
        spans[index] = (row, start, middle)
        spans[index + 1] = (following, middle, spans[index + 1][2])

    package = AUDIO / f"ch{chapter:02d}"
    package.mkdir(parents=True, exist_ok=True)
    manifest = []
    for row, start, end in spans:
        if end - start <= 0.05:
            raise RuntimeError(f"{row['id']}: degenerate cut {start:.3f}-{end:.3f}")
        clip = package / f"{row['id']}.mp3"
        if not dry_run:
            core.cut(clip, source, start, end)
            core.pad_to_margins(clip, row["start"] - start, end - row["end"])
            # The margins above are measured by ASR, whose word onsets run up to
            # 0.3s late: a clip can then open straight onto the onset of its own
            # first word. Measure the silence that is really there and fill the
            # rest with synthetic silence, which cannot let any speech in.
            lead, tail = measure_silence(clip)
            core.pad_to_margins(clip, lead, tail)
            lead, tail = measure_silence(clip)
            duration = float(subprocess.check_output(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)],
                text=True).strip())
        else:
            lead, tail, duration = measure_silence(clip) if clip.is_file() else (0.0, 0.0, end - start)
        manifest.append({
            **row,
            "source": str(source.relative_to(ROOT)),
            "start": round(start, 3), "end": round(end, 3),
            "word_start": round(row["start"], 3), "word_end": round(row["end"], 3),
            "duration": round(duration, 3), "lead": round(lead, 3), "tail": round(tail, 3),
        })
    if not dry_run:
        (package / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {"chapter": chapter, "records": len(records), "cut": len(manifest), "sequence_ratio": ratio,
            "unmatched": [row["id"] for row in aligned if row["start"] is None],
            "min_coverage": min((row["coverage"] for row in manifest if row["coverage"] is not None), default=0)}


def measure_silence(clip: Path) -> tuple[float, float]:
    """Silent run at each end of a clip, measured from the audio itself."""
    from tesouro_validate_cuts import edge_silence
    return edge_silence(clip)


def parse_chapters(text: str) -> list[int]:
    chapters = []
    for part in text.split(","):
        if "-" in part:
            low, high = part.split("-")
            chapters.extend(range(int(low), int(high) + 1))
        else:
            chapters.append(int(part))
    return chapters


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapters", default="1-5")
    parser.add_argument("--probe", action="store_true", help="transcribe and report, cut nothing")
    parser.add_argument("--refresh", action="store_true", help="ignore the transcription cache")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    chapters = parse_chapters(args.chapters)
    if args.refresh:
        for chapter in chapters:
            (WORK / "asr-deepgram" / f"ch{chapter:02d}.json").unlink(missing_ok=True)
    if args.probe:
        probe(chapters)
        return
    for chapter in chapters:
        print(json.dumps(process_chapter(chapter, args.dry_run), ensure_ascii=False))


if __name__ == "__main__":
    main()
