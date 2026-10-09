#!/usr/bin/env python3
"""Check the A Cidadela Misteriosa clips before any of them reach Anki.

Two kinds of check, because they fail differently:

* Free gates on every clip — a clip may not touch a cut edge with speech, may not
  carry a neighbouring sentence's words, must contain its own sentence's whole ASR
  word span, and must match its manifest. These come from the clip's own energy
  envelope and the chapter alignment, both already paid for.
* A paid transcription of a sample of clips — the one check that can catch a clip
  holding the wrong audio altogether, and the only way to tell whether the free
  gates are measuring the right thing at all.

``--self-test`` deliberately produces two defective clips (a neighbour's audio, and
a cut moved a second and a half late) and fails if the checks pass them. A checker
that accepts everything proves nothing.

    python3 tools/cidadela_validate.py                 # gates + a 24-clip sample
    python3 tools/cidadela_validate.py --all           # transcribe every clip
    python3 tools/cidadela_validate.py --self-test
"""
from __future__ import annotations

import argparse
import array
import base64
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / "cidadela" / "audio"
WORK = ROOT / "cidadela" / "work"
STT = WORK / "stt-unprompted"
SOURCE = ROOT / "cidadela" / "source"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tesouro_validate_cuts import edge_silence, fuzzy_fraction, tokens  # noqa: E402

# A cut edge must sit in silence: speech touching an edge is either a sliced word
# or a neighbour the narrator ran together with this sentence.
MIN_LEAD_SECONDS = 0.02
MIN_TAIL_SECONDS = 0.05
# How closely a clip's transcription must reproduce the sentence it should hold.
MIN_FUZZY = 0.80
MIN_SIMILARITY = 0.70
# A one-word ASR slip on a short clip moves the fraction a lot; the sample is
# judged with a little room, and anything below the floor is escalated instead.
ESCALATE_FUZZY = 0.60
PROVIDER = "openai/whisper-large-v3"
ESCALATION_PROVIDER = "google/chirp-3"


def duration(path: Path) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], text=True))


def load_rows() -> list[dict]:
    rows = []
    for manifest in sorted(AUDIO.glob("ch*/manifest.json")):
        chapter = int(manifest.parent.name[2:])
        for row in json.loads(manifest.read_text()):
            row["chapter"] = chapter
            row["package"] = str(manifest.parent)
            row["audio"] = manifest.parent / f"{row['id']}.mp3"
            rows.append(row)
    return rows


# Speech sitting between two consecutive clips is speech no clip holds: each
# clip already carries its own silence padding, so the gap should be silent. Two
# signals, because one alone is too blunt: a word the transcript places inside the
# gap, or a stretch of audio as loud as speech. A sentence's soft decay sits in
# many gaps and is not speech -- this is what caught cm0209 losing "ri-se".
SPEECH_LEVEL_SHARE = 0.15
MIN_GAP_SPEECH_SECONDS = 0.10
ASR_DIR = WORK / "asr-deepgram"
# Gap audio inspected by hand and shown to be non-speech (a laugh, a decay, an
# onset). Each entry carries the measured seconds it is allowed to cover, so an
# exception cannot quietly absorb more speech later, and a transcribed word in a
# gap is never excepted at all.
GAP_EXCEPTIONS_PATH = WORK / "gap-exceptions.json"
GAP_EXCEPTIONS = json.loads(GAP_EXCEPTIONS_PATH.read_text()) if GAP_EXCEPTIONS_PATH.is_file() else {}
GAP_EXCEPTION_SLACK = 0.05


def asr_words(chapter: int, cache: dict[int, list[dict]]) -> list[dict]:
    if chapter not in cache:
        cached = ASR_DIR / f"ch{chapter:02d}.json"
        cache[chapter] = json.loads(cached.read_text()).get("words") or [] if cached.is_file() else []
    return cache[chapter]


def source_frames(chapter: int, cache: dict[int, tuple[list[float], float]]) -> tuple[list[float], float]:
    """Energy envelope of a chapter recording, and its audibility threshold."""
    if chapter not in cache:
        import array
        raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(SOURCE / f"ch{chapter:02d}.mp3"),
                                       "-f", "s16le", "-ac", "1", "-ar", "16000", "-"])
        samples = array.array("h")
        samples.frombytes(raw)
        step = 160
        frames = [(sum(value * value for value in samples[offset:offset + step]) / step) ** 0.5
                  for offset in range(0, len(samples) - step + 1, step)]
        cache[chapter] = (frames, max(25.0, max(frames, default=0.0) * 0.03))
    return cache[chapter]


def spoken_seconds(frames: list[float], threshold: float, start: float, end: float) -> float:
    low, high = max(0, int(start / 0.01)), min(len(frames), int(end / 0.01))
    return sum(1 for value in frames[low:high] if value > threshold) * 0.01


def free_gates(rows: list[dict]) -> list[dict]:
    """The checks that need no provider: edges, spans, neighbours, manifest."""
    findings = []
    by_chapter: dict[int, list[dict]] = {}
    envelopes: dict[int, tuple[list[float], float]] = {}
    transcripts: dict[int, list[dict]] = {}
    for row in rows:
        by_chapter.setdefault(row["chapter"], []).append(row)
    for chapter, chapter_rows in by_chapter.items():
        chapter_rows.sort(key=lambda r: r["start"])
        frames, threshold = source_frames(chapter, envelopes)
        words = asr_words(chapter, transcripts)
        for index, row in enumerate(chapter_rows):
            problems = []
            notes = []
            if not row["audio"].is_file():
                findings.append({"id": row["id"], "problems": ["clip missing"]})
                continue
            measured = duration(row["audio"])
            if abs(measured - row["duration"]) > 0.05:
                problems.append(f"duration {measured:.3f}s != manifest {row['duration']:.3f}s")
            lead, tail = edge_silence(row["audio"])
            if lead < MIN_LEAD_SECONDS:
                problems.append(f"lead margin {lead:.3f}s < {MIN_LEAD_SECONDS}s")
            if tail < MIN_TAIL_SECONDS:
                problems.append(f"tail margin {tail:.3f}s < {MIN_TAIL_SECONDS}s")
            # The clip must hold its own sentence's whole word span.
            if row["start"] > row["word_start"] + 0.001:
                problems.append(f"cut starts {row['word_start'] - row['start']:.3f}s inside its own first word")
            if row["end"] < row["word_end"] - 0.001:
                problems.append(f"cut ends {row['end'] - row['word_end']:.3f}s before its own last word")
            # No neighbouring sentence's words may be inside this clip, and no
            # part of this clip may reach into a neighbour's words.
            if index > 0:
                previous = chapter_rows[index - 1]
                if row["start"] < previous["word_end"] - 0.001:
                    problems.append(f"clip starts {previous['word_end'] - row['start']:.3f}s inside the previous sentence")
                if row["start"] < previous["end"] - 0.001:
                    problems.append("clip overlaps the previous clip")
            if index + 1 < len(chapter_rows):
                following = chapter_rows[index + 1]
                if row["end"] > following["word_start"] + 0.001:
                    problems.append(f"clip ends {row['end'] - following['word_start']:.3f}s into the next sentence")
                if row["end"] > following["start"] + 0.001:
                    problems.append("clip overlaps the next clip")
                loose = spoken_seconds(frames, max(frames) * SPEECH_LEVEL_SHARE, row["end"], following["start"])
                stranded = [word["word"] for word in words
                            if row["end"] < word["start"] < following["start"]
                            and word["end"] - word["start"] >= 0.05]
                if stranded:
                    problems.append(f"transcript words {stranded} fall between this clip and the next one")
                elif loose >= MIN_GAP_SPEECH_SECONDS:
                    allowed = GAP_EXCEPTIONS.get(row["id"])
                    if allowed and loose <= allowed["seconds"] + GAP_EXCEPTION_SLACK:
                        notes.append(f"{loose:.2f}s of gap audio inspected and accepted: {allowed['reason']}")
                    else:
                        problems.append(f"{loose:.2f}s of speech-level audio falls between this clip and the next one")
            if problems or notes:
                findings.append({"id": row["id"], "problems": problems, "notes": notes})
    return findings


def transcribe(audio: Path, model: str) -> dict:
    body = {"model": model, "input_audio": {"data": base64.b64encode(audio.read_bytes()).decode(), "format": "mp3"},
            "language": "pt"}
    if model != ESCALATION_PROVIDER:
        # Chirp rejects the verbose shape outright; it is only asked for text.
        body.update({"response_format": "verbose_json",
                     "timestamp_granularities": ["word", "segment"], "temperature": 0})
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/audio/transcriptions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if attempt == 5:
                raise
            time.sleep(5 * (attempt + 1) if error.code == 429 else 2 ** attempt)
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def clip_digest(row: dict) -> str:
    import hashlib
    return hashlib.sha256(row["audio"].read_bytes()).hexdigest()[:16]


def cached_transcribe(row: dict, directory: Path, model: str) -> dict:
    """Transcribe once per clip *content*: a re-cut clip must not be judged on
    the transcript of the audio it used to be."""
    directory.mkdir(parents=True, exist_ok=True)
    row["digest"] = clip_digest(row)
    cached = directory / f"{row['id']}-{row['digest']}.json"
    if cached.is_file():
        return json.loads(cached.read_text())
    result = transcribe(row["audio"], model)
    cached.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def content_problems(row: dict, heard_text: str, strict: bool = True) -> tuple[list[str], dict]:
    from difflib import SequenceMatcher
    expected = tokens(row["portuguese_text"])
    heard = tokens(heard_text)
    fuzzy = fuzzy_fraction(expected, heard)
    similarity = SequenceMatcher(None, expected, heard, autojunk=False).ratio()
    notes = {"fuzzy": round(fuzzy, 3), "similarity": round(similarity, 3), "heard": heard_text.strip()[:200]}
    problems = []
    if strict and (fuzzy < MIN_FUZZY or similarity < MIN_SIMILARITY):
        problems.append(f"content: fuzzy {fuzzy:.3f}, similarity {similarity:.3f}")
    return problems, notes


def sample(rows: list[dict], count: int, seed: int = 20261005) -> list[dict]:
    """One clip per chapter for every chapter, then fill up at random."""
    chosen, seen = [], set()
    for chapter in sorted({row["chapter"] for row in rows}):
        chapter_rows = [row for row in rows if row["chapter"] == chapter]
        pick = chapter_rows[len(chapter_rows) // 2]
        chosen.append(pick)
        seen.add(pick["id"])
    remaining = [row for row in rows if row["id"] not in seen]
    random.Random(seed).shuffle(remaining)
    chosen.extend(remaining[:max(0, count - len(chosen))])
    return sorted(chosen, key=lambda r: r["id"])


def self_test() -> None:
    """Produce two clips that must fail, and check that they do.

    A neighbour's audio stands in for a mis-identified sentence; a cut moved 1.5s
    late stands in for a boundary placed inside the sentence. If the checks pass
    either of these they are not measuring the clip's content or its edges.
    """
    rows = load_rows()
    target = next(row for row in rows if row["duration"] > 4 and row["chapter"] == 1)
    neighbour = next(row for row in rows if row["chapter"] == 1 and row["start"] > target["end"])
    failures = []
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        # (a) wrong content: the neighbour sentence's audio under this clip's name.
        wrong = dict(target, audio=directory / f"{target['id']}.mp3")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(neighbour["audio"]), "-c", "copy", str(wrong["audio"])],
                       check=True)
        problems, notes = content_problems(wrong, transcribe(wrong["audio"], PROVIDER).get("text", ""))
        if not problems:
            failures.append(f"wrong-audio clip passed the content check (fuzzy {notes['fuzzy']})")
        # (b) a late cut: the clip starts 1.5s after the sentence does.
        late = dict(target, audio=directory / "late.mp3")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{target['start'] + 1.5:.3f}",
                        "-to", f"{target['end']:.3f}", "-i", str(SOURCE / "ch01.mp3"),
                        "-c", "copy", str(late["audio"])], check=True)
        lead, tail = edge_silence(late["audio"])
        if lead >= MIN_LEAD_SECONDS:
            failures.append(f"late cut passed the lead gate (lead {lead:.3f}s)")
        content, _ = content_problems(late, transcribe(late["audio"], PROVIDER).get("text", ""))
        print(json.dumps({
            "wrong_audio": {"problems": problems, "notes": notes},
            "late_cut": {"lead": round(lead, 3), "tail": round(tail, 3), "content_problems": content},
        }, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit("SELF-TEST FAILED (the checker is vacuous): " + "; ".join(failures))
    print("SELF-TEST PASSED: the checker rejects wrong audio and a late cut")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="transcribe every clip, not a sample")
    parser.add_argument("--sample", type=int, default=24)
    parser.add_argument("--gates-only", action="store_true", help="free checks only, no transcription")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return

    rows = load_rows()
    findings = free_gates(rows)
    print(json.dumps({"clips": len(rows), "free_gate_findings": findings}, ensure_ascii=False, indent=2))
    if args.gates_only:
        if any(finding["problems"] for finding in findings):
            raise SystemExit(1)
        print(f"PASS: {len(rows)} clips passed the free gates")
        return

    picks = rows if args.all else sample(rows, args.sample)
    rows_by_id = {row["id"]: row for row in rows}
    report, escalated, failed = [], [], []
    for row in picks:
        result = cached_transcribe(row, STT, PROVIDER)
        problems, notes = content_problems(row, result.get("text", ""))
        if problems and notes["fuzzy"] > 0.15:
            # Anything the first provider doubts gets a second opinion: the
            # below-floor cases matter most, and a clip both providers reject is
            # a real defect. Only audio that is plainly something else fails here.
            second = transcribe(row["audio"], ESCALATION_PROVIDER)
            second_problems, second_notes = content_problems(row, second.get("text", ""))
            escalated.append({"id": row["id"], "whisper": notes, "chirp": second_notes,
                              "whisper_problems": problems, "chirp_problems": second_problems})
            if not second_problems:
                notes["cleared_by"] = ESCALATION_PROVIDER
                problems = []
        lead, tail = edge_silence(row["audio"])
        entry = {"id": row["id"], "chapter": row["chapter"], "duration": row["duration"],
                 "digest": notes.pop("digest", row.get("digest")), "lead": round(lead, 3), "tail": round(tail, 3),
                 **notes, "problems": problems}
        report.append(entry)
        if problems:
            failed.append(entry)

    print(json.dumps({"transcribed": len(picks), "provider": PROVIDER,
                      "problems": failed, "escalated": escalated}, ensure_ascii=False, indent=2))
    if any(finding["problems"] for finding in findings) or failed:
        raise SystemExit(1)
    print(f"PASS: {len(rows)} clips passed the free gates; {len(picks)} transcriptions agreed with their sentences")


if __name__ == "__main__":
    main()
