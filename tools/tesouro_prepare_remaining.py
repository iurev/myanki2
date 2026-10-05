#!/usr/bin/env python3
import argparse
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

ALIGNMENT_ALIASES = {"ts0036": "estranho"}


def tokens(text: str) -> list[str]:
    text = "".join(
        char for char in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(char) != "Mn"
    )
    text = re.sub(r"[^0-9a-z]+", " ", text)
    return [word[1:] if len(word) > 1 and word.startswith("h") else word for word in text.split()]


def transcribe(audio: Path, saved: Path, window_start: float) -> dict:
    if saved.is_file():
        result = json.loads(saved.read_text())
        if result.get("_window_start") == window_start:
            return result
    body = {
        "model": "deepgram/nova-3",
        "input_audio": {"data": base64.b64encode(audio.read_bytes()).decode(), "format": "mp3"},
        "language": "pt",
        "response_format": "verbose_json",
        "timestamp_granularities": ["word", "segment"],
    }
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/audio/transcriptions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"},
    )
    for attempt in range(4):
        try:
            result = json.load(urllib.request.urlopen(request, timeout=60))
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2**attempt)
    result["_window_start"] = window_start
    saved.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def align(reference: list[str], words: list[dict], expected_center: float) -> tuple[float, int, int]:
    best = None
    for start in range(len(words)):
        for length in range(max(1, len(reference) - 2), min(len(words) - start, len(reference) + 2) + 1):
            hypothesis = []
            positions = []
            for index, word in enumerate(words[start:start + length]):
                word_tokens = tokens(word["word"])
                hypothesis.extend(word_tokens)
                positions.extend([start + index] * len(word_tokens))
            ratio = SequenceMatcher(None, reference, hypothesis, autojunk=False).ratio()
            center = (words[start]["start"] + words[start + length - 1]["end"]) / 2
            score = ratio - 0.015 * abs(center - expected_center)
            if best is None or score > best[0]:
                matcher = SequenceMatcher(None, reference, hypothesis, autojunk=False)
                matched = []
                for tag, _, _, hyp_start, hyp_end in matcher.get_opcodes():
                    if tag == "equal":
                        matched.extend(positions[hyp_start:hyp_end])
                best = score, ratio, min(matched) if matched else start, max(matched) if matched else start + length - 1
    if best is None or best[1] < 0.72:
        raise RuntimeError(f"alignment failed: ratio={best[1] if best else 0}")
    return best[1], best[2], best[3]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inventory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    items = json.loads(args.inventory.read_text())[args.offset:]
    if args.limit is not None:
        items = items[:args.limit]
    args.output.mkdir(parents=True, exist_ok=True)
    cache = args.output / "wide-deepgram"
    cache.mkdir(exist_ok=True)
    prepared = []
    for item in items:
        window_start = max(0, item["historical_start"] - 10)
        window_end = item["historical_end"] + 10
        wide = args.output / f".{item['id']}-wide.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-ss", str(window_start), "-i", item["source"],
            "-t", str(window_end - window_start), "-map", "0:a", "-codec:a", "libmp3lame", "-qscale:a", "2", str(wide),
        ], check=True)
        result = transcribe(wide, cache / f"{item['id']}.json", window_start)
        alignment_text = ALIGNMENT_ALIASES.get(item["id"], item["portuguese_text"])
        ratio, first, last = align(
            tokens(alignment_text), result["words"],
            (item["historical_start"] + item["historical_end"]) / 2 - window_start,
        )
        start = max(0, window_start + result["words"][first]["start"] - 0.2)
        end = window_start + result["words"][last]["end"] + 0.2
        output_audio = args.output / f"{item['id']}.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-i", item["source"],
            "-t", str(end - start), "-map", "0:a", "-codec:a", "libmp3lame", "-qscale:a", "2", str(output_audio),
        ], check=True)
        wide.unlink(missing_ok=True)
        prepared.append({**item, "start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3), "alignment_ratio": round(ratio, 3)})
        (args.output / "manifest.json").write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n")
        records = [{
            "id": row["id"],
            "front": {"portuguese_audio": f"audio/{row['id']}.mp3"},
            "back": {"portuguese_text": row["portuguese_text"], "english_text": row["english_text"], "english_audio": None},
        } for row in prepared]
        (args.output / "records.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
        print(item["id"], f"ratio={ratio:.3f}", f"source={start:.3f}-{end:.3f}")


if __name__ == "__main__":
    main()
