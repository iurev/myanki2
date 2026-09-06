#!/usr/bin/env python3
"""Cut Tesouro Submerso chapter audio into sentence clips from an alignment YAML."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import yaml


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("source", help="chapter MP3, e.g. Storyglot-O_Tesouro_Submerso_chpt1.mp3")
    p.add_argument("alignment", help="alignment YAML, e.g. tesouro/ch01-alignment.yaml")
    p.add_argument("--output", default="tesouro/audio/ch01", help="output directory")
    args = p.parse_args()

    source = Path(args.source)
    alignment_path = Path(args.alignment)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    cfg = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
    for card in cfg["cards"]:
        dst = output / f"{card['id']}.mp3"
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-ss", str(card["start"]), "-to", str(card["end"]),
                "-i", str(source), "-map", "0:a:0", "-vn",
                "-ac", "1", "-ar", "44100", "-b:a", "64k", str(dst),
            ],
            check=True,
        )
        print(dst)


if __name__ == "__main__":
    main()
