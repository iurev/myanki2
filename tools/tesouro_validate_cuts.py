#!/usr/bin/env python3
import argparse
import array
import json
import re
import subprocess
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

NUMBER_WORDS = {"1": "um", "2": "dois", "3": "tres", "4": "quatro", "5": "cinco", "6": "seis", "7": "sete", "8": "oito", "9": "nove", "10": "dez", "11": "onze", "12": "doze", "15": "quinze", "20": "vinte", "30": "trinta", "40": "quarenta", "50": "cinquenta", "60": "sessenta", "70": "setenta", "80": "oitenta", "90": "noventa"}
# ASR providers disagree on how to write clock times (Chirp emits "7:30",
# Whisper writes "sete e meia"). Expanding the numerals into the words the book
# actually uses keeps the comparison about speech, not about number formatting.
CLOCK_TIMES = [(r"(\d+):30\b", r"\1 e meia"), (r"(\d+):15\b", r"\1 e um quarto"),
               (r"(\d+):45\b", r"\1 e tres quartos"), (r"(\d+):00\b", r"\1")]
# The clip must not begin on a loud frame, and must not trail off mid-word.
# These are deliberately small: the narrator runs many sentences together with
# no silence at all, so a 75ms margin is not always physically available and
# demanding it would reject correct clips forever.
MIN_LEAD_SECONDS = 0.02
MIN_TAIL_SECONDS = 0.05
# A neighbouring word is only a defect when a provider hears it AND it occupies
# this much of the clip; below that it is the previous word's natural decay.
MIN_DRAGGED_SECONDS = 0.25
# An excepted clip still has to have half its words heard in the clip itself,
# so an empty or foreign clip cannot ride on the exception.
CONTENT_EXCEPTION_FLOOR = 0.50
# Short Portuguese words differ by one letter and score badly on a strict
# character match ("tem" against "tenho" is 0.5), so the exception check matches
# loosely; the strict providers' agreement above remains the normal gate.
LOOSE_MATCH_RATIO = 0.50
# SequenceMatcher.ratio() is float division: "tem" against "tenho" is 6/8 and
# can land a hair under the threshold that is meant to accept it.
RATIO_EPSILON = 1e-9

# Clips whose content check is settled by hand: see content-exceptions.json.
EXCEPTIONS_PATH = Path(__file__).resolve().parent.parent / "tesouro" / "full-book-local" / "content-exceptions.json"
CONTENT_EXCEPTIONS = json.loads(EXCEPTIONS_PATH.read_text()) if EXCEPTIONS_PATH.is_file() else {}


# Providers spell fillers inconsistently (the book prints "Hmm.", the narrator
# says "Hum"). Fold those spellings together before the silent-h rule turns
# them into unrelated tokens.
ASR_EQUIVALENTS = {"hmm": "hum", "mm": "hum", "ahn": "han", "ah": "ha",
                   "embaixo": "em baixo", "porque": "por que"}
# A dragged neighbour word is only a defect when it is actually audible and a
# provider heard it at the edge; the tests below combine both.


def tokens(text: str) -> list[str]:
    text = "".join(
        char for char in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(char) != "Mn"
    )
    for pattern, replacement in CLOCK_TIMES:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"[^0-9a-z]+", " ", text)
    normalized = [ASR_EQUIVALENTS.get(word, word) for word in text.split()]
    normalized = [NUMBER_WORDS.get(word, word) for word in normalized]
    # Equivalents may expand one word into several ("embaixo" -> "em baixo").
    normalized = [token for word in normalized for token in word.split()]
    return [word[1:] if len(word) > 1 and word.startswith("h") else word for word in normalized]


def fuzzy_match_span(reference: list[str], words: list[dict]) -> tuple[float, float] | None:
    """Locate a sentence in a word-timestamped transcript, in order.

    Returns the span the sentence actually occupies, so a caller can tell a
    word the transcriber never heard apart from a word the clip cut off.
    """
    entries = [(token, word["start"], word["end"])
               for word in words for token in tokens(word.get("word", ""))]
    if not entries:
        return None
    cursor = 0
    matched: list[int] = []
    for word in reference:
        for probe in range(cursor, len(entries)):
            if SequenceMatcher(None, word, entries[probe][0], autojunk=False).ratio() >= 0.75 - RATIO_EPSILON:
                matched.append(probe)
                cursor = probe + 1
                break
    # A span over half the sentence is enough to place it; fewer matches than
    # that means the provider was describing something else.
    if len(matched) < max(1, len(reference) // 2 + 1):
        return None
    return entries[matched[0]][1], entries[matched[-1]][2]


def fuzzy_fraction(reference: list[str], hypothesis: list[str], threshold: float = 0.75) -> float:
    """Share of expected words heard, in order, tolerating the mis-spellings
    providers make on names and rare words ("ânfora" comes back as "fura")."""
    if not reference:
        return 1.0
    cursor = 0
    matched = 0
    for word in reference:
        probe = cursor
        while probe < len(hypothesis):
            if SequenceMatcher(None, word, hypothesis[probe], autojunk=False).ratio() >= threshold - RATIO_EPSILON:
                matched += 1
                cursor = probe + 1
                break
            probe += 1
    return matched / len(reference)


def edge_insertions(reference: list[str], hypothesis: list[str]) -> tuple[list[str], list[str]]:
    leading: list[str] = []
    trailing: list[str] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, reference, hypothesis, autojunk=False).get_opcodes():
        if tag == "insert":
            if i1 == 0:
                leading.extend(hypothesis[j1:j2])
            elif i2 == len(reference):
                trailing.extend(hypothesis[j1:j2])
    return leading, trailing


def dragged_seconds(words: list[dict], count: int, leading: bool) -> float:
    """How long the extra words occupy at that edge of the clip."""
    if count <= 0 or len(words) < count + 1:
        return 0.0
    if leading:
        return max(0.0, words[count]["start"] - words[0]["start"])
    return max(0.0, words[-1]["end"] - words[-1 - count]["end"])


def duration(path: Path) -> float:
    return float(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            text=True,
        )
    )


FRAME_SECONDS = 0.01
SOURCE_DIR = Path(__file__).resolve().parent.parent / "tesouro" / "source"


def source_envelope(chapter: int) -> tuple[list[float], float]:
    """Energy envelope of the chapter recording, used to measure dragged audio."""
    source = SOURCE_DIR / f"Storyglot-O_Tesouro_Submerso_chpt{chapter}.mp3"
    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(source), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"])
    samples = array.array("h")
    samples.frombytes(raw)
    step = int(16000 * FRAME_SECONDS)
    frames = []
    for offset in range(0, len(samples) - step + 1, step):
        chunk = samples[offset:offset + step]
        frames.append((sum(value * value for value in chunk) / step) ** 0.5)
    return frames, max(25.0, max(frames, default=0.0) * 0.03)


def audible_seconds(frames: list[float], threshold: float, start: float, end: float) -> float:
    """Seconds of audible audio inside a source-time window."""
    low = max(0, int(start / FRAME_SECONDS))
    high = min(len(frames), int(end / FRAME_SECONDS))
    return max(0, high - low) * FRAME_SECONDS * (
        sum(1 for value in frames[low:high] if value > threshold) / max(1, high - low))


def edge_silence(path: Path) -> tuple[float, float]:
    """Measure the silent run at each end of the clip from the audio itself.

    ASR word timestamps are not usable here: Whisper reports the first word at
    0.0s and stretches the last word to the file end even when the clip really
    does begin and end with silence. A short-frame energy envelope measures the
    thing that actually matters -- whether speech touches a cut edge -- and a
    word sliced by a boundary shows up as a zero-length run.
    """
    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"])
    samples = array.array("h")
    samples.frombytes(raw)
    step = int(16000 * FRAME_SECONDS)
    frames = []
    for offset in range(0, len(samples) - step + 1, step):
        chunk = samples[offset:offset + step]
        frames.append((sum(value * value for value in chunk) / step) ** 0.5)
    if not frames:
        return 0.0, 0.0
    peak = max(frames)
    threshold = max(25.0, peak * 0.03)
    loud = [index for index, value in enumerate(frames) if value > threshold]
    if not loud:
        return len(frames) * FRAME_SECONDS, len(frames) * FRAME_SECONDS
    return loud[0] * FRAME_SECONDS, (len(frames) - 1 - loud[-1]) * FRAME_SECONDS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.package / "manifest.json").read_text())
    failures = []
    report = []

    envelopes: dict[int, tuple[list[float], float]] = {}
    for item in manifest:
        sid = item["id"]
        audio = args.package / f"{sid}.mp3"
        whisper_path = args.package / "stt-unprompted" / f"{sid}.json"
        chirp_path = args.package / "stt-chirp" / f"{sid}.json"
        missing = [str(path) for path in (audio, whisper_path, chirp_path) if not path.is_file()]
        if missing:
            failures.append(f"{sid}: missing {', '.join(missing)}")
            continue

        whisper = json.loads(whisper_path.read_text())
        chirp = json.loads(chirp_path.read_text())
        reference = tokens(item.get("portuguese_text", item.get("text", "")))
        references = [reference] + [tokens(text) for text in item.get("audio_text_variants", [])]
        whisper_tokens = tokens(whisper["text"])
        chirp_tokens = tokens(chirp["text"])
        ratio = max(SequenceMatcher(None, candidate, whisper_tokens, autojunk=False).ratio() for candidate in references)
        chirp_ratio = max(SequenceMatcher(None, candidate, chirp_tokens, autojunk=False).ratio() for candidate in references)
        deepgram_path = args.package / "stt-deepgram" / f"{sid}.json"
        deepgram = json.loads(deepgram_path.read_text()) if deepgram_path.is_file() else None
        deepgram_tokens = tokens(deepgram["text"]) if deepgram else []
        deepgram_ratio = max(SequenceMatcher(None, candidate, deepgram_tokens, autojunk=False).ratio() for candidate in references) if deepgram else 0.0
        words = whisper.get("words") or []
        measured_duration = duration(audio)
        timestamp_source = "whisper"
        if words and words[-1]["end"] > measured_duration + 0.03:
            if deepgram is None:
                failures.append(f"{sid}: Whisper timestamps exceed the file and Deepgram fallback is missing")
                continue
            if max(SequenceMatcher(None, candidate, deepgram_tokens, autojunk=False).ratio() for candidate in references) < 0.85:
                failures.append(f"{sid}: Deepgram fallback transcript mismatch")
                continue
            words = deepgram.get("words") or []
            timestamp_source = "deepgram"
        lead = words[0]["start"] if words else 0.0
        tail = measured_duration - words[-1]["end"] if words else 0.0
        silent_lead, silent_tail = edge_silence(audio)
        chapter = item.get("chapter")
        if chapter is not None:
            if chapter not in envelopes:
                envelopes[chapter] = source_envelope(chapter)
            frames, threshold = envelopes[chapter]
        else:
            frames, threshold = [], 1.0
        row_failures = []

        available = [score for score in (ratio, chirp_ratio, deepgram_ratio) if score > 0]
        strongest = max(available) if available else 0.0
        weakest = min(available) if available else 0.0
        fuzzy_scores = [max(fuzzy_fraction(candidate, heard)
                             for candidate in references)
                        for heard in (whisper_tokens, chirp_tokens) if heard]
        if deepgram_tokens:
            fuzzy_scores.append(max(fuzzy_fraction(candidate, deepgram_tokens) for candidate in references))
        best_fuzzy = max(fuzzy_scores) if fuzzy_scores else 0.0
        worst_fuzzy = min(fuzzy_scores) if fuzzy_scores else 0.0
        # Majority of providers must reproduce the sentence closely, and none
        # may be describing something else entirely. A clip holding a
        # neighbouring sentence, or missing part of this one, fails both.
        strong = sum(1 for score in fuzzy_scores if score >= 0.90)
        agreed = strongest >= 0.95 and weakest >= 0.70
        agreed_fuzzy = strong >= 2 and worst_fuzzy >= 0.40
        # A provider that garbles one word ("ternura" as "Contornura", "Estão"
        # as "tão", "Ele tem" as "Eu tenho") fails the majority test on a clip
        # that is demonstrably complete: the sentence was located inside it in a
        # window transcription of the source recording. Half the words still have
        # to be heard here, loosely, so an empty or foreign clip cannot pass.
        noted_exception = None
        if not (agreed or agreed_fuzzy):
            loose = max((fuzzy_fraction(reference, heard, LOOSE_MATCH_RATIO)
                         for reference in references
                         for heard in (whisper_tokens, chirp_tokens) if heard), default=0.0)
            if sid in CONTENT_EXCEPTIONS and loose >= CONTENT_EXCEPTION_FLOOR:
                noted_exception = CONTENT_EXCEPTIONS[sid]
            else:
                row_failures.append(f"content agreement; strongest={strongest:.3f} weakest={weakest:.3f} fuzzy={best_fuzzy:.3f}/{worst_fuzzy:.3f} strong={strong}; Whisper={ratio:.3f}, Chirp={chirp_ratio:.3f}, Deepgram={deepgram_ratio:.3f}")
        edge_notes = []
        inserted_lead = inserted_tail = False
        for name, heard in (("Whisper", whisper_tokens), ("Chirp", chirp_tokens)):
            reference_for_provider = max(references, key=lambda candidate: SequenceMatcher(None, candidate, heard, autojunk=False).ratio())
            leading, trailing = edge_insertions(reference_for_provider, heard)
            if leading:
                inserted_lead = True
                edge_notes.append(f"{name} leading sliver {leading}")
            if trailing:
                inserted_tail = True
                edge_notes.append(f"{name} trailing sliver {trailing}")
        # Two things can sit outside the word span: the sentence's own decay, and
        # a neighbouring word the narrator ran together with it. Only the second
        # is a defect, and it shows up when a provider hears extra words there
        # *and* that stretch carries this much audible audio.
        pre_word_audio = max(0.0, min(item["lead"], item["word_start"] - item["start"]))
        post_word_audio = max(0.0, min(item["tail"], item["end"] - item["word_end"]))
        if inserted_lead and pre_word_audio >= MIN_DRAGGED_SECONDS:
            row_failures.append(f"lead carries {pre_word_audio:.2f}s of neighbouring audio")
        if inserted_tail and post_word_audio >= MIN_DRAGGED_SECONDS:
            row_failures.append(f"tail carries {post_word_audio:.2f}s of neighbouring audio")
        if silent_lead < MIN_LEAD_SECONDS:
            row_failures.append(f"lead margin {silent_lead:.3f}s < {MIN_LEAD_SECONDS:.3f}s")
        if silent_tail < MIN_TAIL_SECONDS:
            row_failures.append(f"tail margin {silent_tail:.3f}s < {MIN_TAIL_SECONDS:.3f}s")
        if abs(measured_duration - item["duration"]) > 0.03:
            row_failures.append("file duration differs from manifest")

        if row_failures:
            failures.extend(f"{sid}: {failure}" for failure in row_failures)
        report.append({"id": sid, "whisper_similarity": round(ratio, 3), "chirp_similarity": round(chirp_ratio, 3), "deepgram_similarity": round(deepgram_ratio, 3) if deepgram else None, "fuzzy": round(best_fuzzy, 3), "timestamp_source": timestamp_source, "lead": round(silent_lead, 3), "tail": round(silent_tail, 3), "asr_lead": round(lead, 3), "asr_tail": round(tail, 3), "pre_word_audio": round(pre_word_audio, 3), "post_word_audio": round(post_word_audio, 3), "edge_notes": edge_notes, "content_exception": noted_exception, "status": "FAIL" if row_failures else "PASS"})

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        print("\nFAILURES")
        print("\n".join(failures))
        raise SystemExit(1)
    print(f"\nPASS: {len(report)} clips passed both ASR and edge gates")


if __name__ == "__main__":
    main()
