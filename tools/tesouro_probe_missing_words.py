#!/usr/bin/env python3
"""Decide whether a failed content check means a genuinely clipped clip.

Providers sometimes turn a word into noise, or drop a short quiet word, which
looks identical to a clip cut through that word. The recording decides: the
window around the clip is transcribed with word timestamps, the sentence's own
tokens are located in that word stream, and the clip is only called clipped when
the located sentence starts before the clip or ends after it. A plain keyword
probe cannot do this: the neighbouring sentence often contains the same word.
"""
import argparse
import json
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tesouro_collect_asr import request_transcription  # noqa: E402
from tesouro_validate_cuts import fuzzy_match_span, tokens  # noqa: E402
ROOT = Path(__file__).resolve().parent.parent
MODELS = ("openai/whisper-large-v3", "deepgram/nova-3")
MARGIN_TOLERANCE = 0.12


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("--ids", required=True)
    args = parser.parse_args()
    manifest = {row["id"]: row for row in json.loads((args.package / "manifest.json").read_text())}
    for sid in filter(None, args.ids.split(",")):
        item = manifest[sid]
        source = ROOT / "tesouro" / "source" / f"Storyglot-O_Tesouro_Submerso_chpt{item['chapter']}.mp3"
        low = max(0.0, item["start"] - 1.0)
        window = Path(f"/tmp/window-{sid}.mp3")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{low:.3f}", "-to", f"{item['end'] + 1.0:.3f}",
                        "-i", str(source), "-acodec", "libmp3lame", "-qscale:a", "4", str(window)], check=True)
        expected = tokens(item["portuguese_text"])
        findings = []
        for model in MODELS:
            result = request_transcription(window, model, True)
            words = result.get("words") or []
            span = fuzzy_match_span(expected, words)
            findings.append({"model": model, "text": result.get("text", ""), "span": span})
        starts = [row["span"][0] for row in findings if row["span"]]
        ends = [row["span"][1] for row in findings if row["span"]]
        # Word times are relative to the window; shift them into the recording.
        # One provider can slide a span into the neighbouring word (it hears the
        # previous word as this sentence's first word just as easily as the
        # reverse), so only an agreement between providers proves a clipped edge.
        verdict, detail = "NOT_PROVEN", "no provider located the whole sentence"
        if starts and ends:
            first, last = low + min(starts), low + max(ends)
            over_head = sum(1 for value in starts if low + value < item["start"] - MARGIN_TOLERANCE)
            over_tail = sum(1 for value in ends if low + value > item["end"] + MARGIN_TOLERANCE)
            if over_head == len(starts):
                verdict, detail = "CLIPPED", f"sentence starts {item['start'] - first:.2f}s before the clip"
            elif over_tail == len(ends):
                verdict, detail = "CLIPPED", f"sentence ends {last - item['end']:.2f}s after the clip"
            else:
                verdict, detail = "SOUND", f"sentence located {first:.2f}-{last:.2f} inside clip {item['start']:.2f}-{item['end']:.2f}"
        print(json.dumps({"id": sid, "expected": item["portuguese_text"], "clip": [item["start"], item["end"]],
                          "verdict": verdict, "detail": detail, "findings": findings}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
