#!/usr/bin/env python3
"""Cut one Tesouro Submerso chapter MP3 into sentence-level listening clips.

The canonical timing source is tesouro/alignment-ch01-10.csv. Each source MP3
contains exactly one book chapter, so select the matching chapter number with
--chapter and the script writes the card IDs for that chapter to
``tesouro/audio/chXX`` by default.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
from pathlib import Path


def load_cards(path: Path, chapter: int) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        cards = [row for row in csv.DictReader(f) if int(row["chapter"]) == chapter]
    if not cards:
        raise ValueError(f"No chapter {chapter} rows in {path}")
    return cards


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("source", help="chapter MP3, e.g. Storyglot-O_Tesouro_Submerso_chpt4.mp3")
    p.add_argument(
        "alignment",
        nargs="?",
        default="tesouro/alignment-ch01-10.csv",
        help="aggregate alignment CSV (default: tesouro/alignment-ch01-10.csv)",
    )
    p.add_argument("--chapter", type=int, required=True, help="chapter number in the source MP3")
    p.add_argument("--output", help="output directory; defaults to tesouro/audio/chXX")
    args = p.parse_args()

    source = Path(args.source)
    alignment = Path(args.alignment)
    if not source.is_file():
        raise FileNotFoundError(source)
    if not alignment.is_file():
        raise FileNotFoundError(alignment)

    output = Path(args.output) if args.output else Path(f"tesouro/audio/ch{args.chapter:02d}")
    output.mkdir(parents=True, exist_ok=True)

    cards = load_cards(alignment, args.chapter)
    for card in cards:
        dst = output / f"{card['id']}.mp3"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                card["start"],
                "-to",
                card["end"],
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "44100",
                "-b:a",
                "64k",
                str(dst),
            ],
            check=True,
        )
        print(dst)

    print(f"cut {len(cards)} chapter {args.chapter} clips into {output}")


if __name__ == "__main__":
    main()
