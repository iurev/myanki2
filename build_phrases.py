#!/usr/bin/env python3
"""Generate phrase cards (phrases.yaml) from phrases.md (Time + Useful words).

These are greetings, connectors, time words and clock phrases. They don't suit a
cloze, so the card is a straight English -> Portuguese prompt (front = English,
back = Portuguese). Time nouns keep a gender tag.

    python3 build_phrases.py [--yaml]
"""
import re
import sys
import yaml

SRC, OUT, START_ID = "phrases.md", "phrases.yaml", 620


def parse():
    rows = []
    for line in open(SRC, encoding="utf-8"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" in s:                                   # "portuguese: english"
            left, en = s.split(":", 1)
            left, en = left.strip(), en.strip()
            g = re.search(r"\((m|f),", left)
            if g:                                      # time noun -> tag gender
                pt = left[:g.start()].strip() + f" ({g.group(1)})"
            else:
                pt = left
        else:                                          # "Portuguese<.?…> English"
            m = re.search(r"[.?…]+\s", s)               # first PT sentence-end + space
            if m:
                pt, en = s[:m.end()].strip(), s[m.end():].strip()
            else:
                pt, en = s, ""
        rows.append((en, pt))
    return rows


def main():
    rows = parse()
    out = {"deck": "words", "model": "words", "cards": []}
    for i, (en, pt) in enumerate(rows):
        out["cards"].append(dict(id=f"{START_ID + i:04d}", word=pt,
                                 front=en, back=pt, chapter="—"))
        if "--yaml" not in sys.argv:
            print(f"{en:42} ->  {pt}")
    print(f"\n{len(rows)} phrases (ids {START_ID:04d}-{START_ID+len(rows)-1:04d})")
    if "--yaml" in sys.argv:
        yaml.safe_dump(out, open(OUT, "w", encoding="utf-8"),
                       allow_unicode=True, sort_keys=False, width=1000)
        print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
