#!/usr/bin/env python3
"""Level the A Cidadela Misteriosa English clips with the Tesouro gain tool.

`tesouro_en_gain.py` already does the whole job: park the pristine take, measure
with EBU R128, render the gain in one pass, measure the render back and refuse to
ship a clip whose gain it cannot confirm. None of that is worth writing twice, so
this file points that tool at this book's directories and hands it the arguments.

    python3 tools/cidadela_en_gain.py --target-lufs -24.4
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tesouro_en_gain  # noqa: E402 - the tested implementation, reused

# The tool reads these module globals while it runs, so pointing them at this
# book before calling main() is enough to reuse it unchanged.
tesouro_en_gain.LOCAL = ROOT / "cidadela"
tesouro_en_gain.ORIGINAL = ROOT / "cidadela" / "audio-en-original"
tesouro_en_gain.SHIPPED = ROOT / "cidadela" / "audio-en"
tesouro_en_gain.STATE = ROOT / "cidadela" / "english-gain.json"
tesouro_en_gain.INVENTORY = ROOT / "cidadela" / "work" / "text-inventory.json"

if __name__ == "__main__":
    sys.argv[0] = "cidadela_en_gain.py"
    tesouro_en_gain.main()
