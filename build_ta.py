#!/usr/bin/env python3
"""Generate ta.yaml from downloaded ta/<n>.html pages.

Each page's sentence lives in a rich-text span like:
    <span class="wixui-rich-text__text">3. - Tem uma reserva? - Não tenho.</span>
and its matching audio was saved by fetch-ta.js to ta/audio/<n>.<ext>
(extension varies by page: mp3/wav/mp4; a page with more than one audio clip
saves ta/audio/<n>-1.<ext>, <n>-2.<ext>, etc.).

Only front, audio and ta_id are filled in here; back/translation is
added later by hand.

    python3 build_ta.py [--yaml]
"""
import glob
import os
import sys

import yaml
from bs4 import BeautifulSoup

SRC_DIR, AUDIO_DIR, OUT = "ta", "ta/audio", "ta.yaml"


def parse_page(path, n):
    soup = BeautifulSoup(open(path, encoding="utf-8"), "html.parser")
    for span in soup.select("span.wixui-rich-text__text"):
        text = span.get_text(strip=True)
        if text.startswith(f"{n}."):
            return text
    return None


def find_audio(n):
    """Return the audio file(s) for page n, whatever their extension/suffix."""
    matches = sorted(glob.glob(os.path.join(AUDIO_DIR, f"{n}.*")))
    matches += sorted(glob.glob(os.path.join(AUDIO_DIR, f"{n}-*.*")))
    return matches


def main():
    pages = sorted(
        glob.glob(os.path.join(SRC_DIR, "*.html")),
        key=lambda p: int(os.path.splitext(os.path.basename(p))[0]),
    )

    rows = []
    for path in pages:
        n = int(os.path.splitext(os.path.basename(path))[0])
        text = parse_page(path, n)
        if text is None:
            print(f"  ! no sentence found on page {n}", file=sys.stderr)
            continue
        audio_files = find_audio(n)
        if len(audio_files) == 0:
            audio = ""
            print(f"  ! no audio found for page {n}", file=sys.stderr)
        elif len(audio_files) == 1:
            audio = audio_files[0]
        else:
            audio = audio_files
        rows.append((n, text, audio))
        if "--yaml" not in sys.argv:
            print(f"{n:3} {text}")

    out = {"deck": "words", "model": "words", "cards": [
        dict(id="", ta_id=n, front=text, audio=audio)
        for n, text, audio in rows
    ]}

    print(f"\n{len(rows)} cards")
    if "--yaml" in sys.argv:
        yaml.safe_dump(out, open(OUT, "w", encoding="utf-8"),
                       allow_unicode=True, sort_keys=False, width=1000)
        print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
