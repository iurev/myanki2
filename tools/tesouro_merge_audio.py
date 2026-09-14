#!/usr/bin/env python3
"""Merge each card's Portuguese clip + English clip into a single combined
audio file for the back of the card (front keeps the standalone Portuguese
clip). A short silence is inserted between the two languages.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DECK_YAML = ROOT / "tesouro-listening.yaml"
OUT_DIR = ROOT / "tesouro" / "audio-combined"
PAUSE_SEC = 0.6


def merge(pt_path: Path, en_path: Path, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    filter_complex = f"[0:a]apad=pad_dur={PAUSE_SEC}[a0];[a0][1:a]concat=n=2:v=0:a=1[out]"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(pt_path), "-i", str(en_path),
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-acodec", "libmp3lame", "-qscale:a", "2",
            str(out_path),
        ],
        check=True,
    )


def main() -> None:
    only_id = sys.argv[1] if len(sys.argv) > 1 else None
    with DECK_YAML.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    done = 0
    for card in cfg["cards"]:
        cid = card["id"]
        if only_id and cid != only_id:
            continue
        pt_path = ROOT / card["audio"]
        en_path = ROOT / "tesouro" / "audio-en" / f"{cid}.mp3"
        out_path = OUT_DIR / f"{cid}.mp3"
        if not pt_path.is_file():
            raise FileNotFoundError(pt_path)
        if not en_path.is_file():
            raise FileNotFoundError(en_path)
        merge(pt_path, en_path, out_path)
        done += 1
        print(f"  + {cid}")

    print(f"merged {done} clips into {OUT_DIR}")


if __name__ == "__main__":
    main()
