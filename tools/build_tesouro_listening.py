#!/usr/bin/env python3
"""Build Tesouro Submerso listening cards from alignment + bilingual book text.

The alignment CSV defines the final Portuguese audio-card boundaries. Chapter
XHTML files contain the corresponding English translation. Most story content
is stored as PT/EN paragraph pairs, which lets us split a paragraph only when
its Portuguese side was split into multiple listening cards.
"""
from __future__ import annotations

import csv
import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT = ROOT / "tesouro" / "alignment-ch01-10.csv"
OUT = ROOT / "tesouro-listening.yaml"
REPORT = ROOT / "tesouro" / "translation-report.csv"
XHTML = "{http://www.w3.org/1999/xhtml}"

# Chapter 1 section 1.2 is laid out unusually in the EPUB (a block of PT lines
# followed by a block of EN lines rather than alternating paragraphs). These
# five translations are the same natural translations used in the approved PoC.
OVERRIDES = {
    "ts0011": "Oh, no!",
    "ts0012": "The red wine isn’t here.",
    "ts0013": "I’m absent-minded and I’m tired.",
    "ts0014": "But there’s no problem!",
    "ts0015": "Here’s the white wine.",
}


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def text_of(el: ET.Element) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def norm(s: str) -> str:
    s = html.unescape(s).casefold().replace("\u200e", "").replace("\u200f", "")
    return re.sub(r"[^\w]+", "", s, flags=re.UNICODE)


def strip_outer_quotes(s: str) -> str:
    s = s.strip().replace("\u200e", "").replace("\u200f", "")
    for a, b in [("“", "”"), ('"', '"'), ("‘", "’")]:
        if s.startswith(a) and s.endswith(b):
            return s[1:-1].strip()
    return s


def split_en(s: str) -> list[str]:
    s = html.unescape(strip_outer_quotes(s))
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"‘])", s)
    return [strip_outer_quotes(p.strip()) for p in parts if p.strip()]


def story_pairs(chapter: int) -> list[tuple[str, str]]:
    """Extract ordinary alternating PT/EN story paragraph pairs.

    Italic story paragraphs are the English translation. Notes and exercises
    are excluded. A few identity translations such as a person's name are not
    italicized, so adjacent equal-normalized paragraphs are accepted too.
    """
    path = ROOT / "extracted" / "OEBPS" / f"upart-002-chapter-{chapter}.xhtml"
    root = ET.parse(path).getroot()
    text_div = next(
        (d for d in root.iter(f"{XHTML}div") if "text" in (d.get("class") or "").split()),
        None,
    )
    if text_div is None:
        raise RuntimeError(f"No story text div in {path}")

    pairs: list[tuple[str, str]] = []
    in_story = False
    pending: str | None = None
    for child in list(text_div):
        tag = local(child.tag)
        txt = text_of(child)

        if tag == "h2":
            in_story = txt.startswith("Section ")
            pending = None
            continue
        if tag == "div" and in_story and txt == "NOTES":
            in_story = False
            pending = None
            continue
        if not in_story or tag != "p":
            continue
        if not txt or txt in {"...", "* * *"} or txt.startswith("(audio "):
            continue

        italic = any(local(d.tag) == "i" for d in child.iter())
        if italic:
            if pending is not None:
                pairs.append((pending, txt))
                pending = None
            continue

        if pending is not None and norm(pending) == norm(txt):
            pairs.append((pending, txt))
            pending = None
            continue
        pending = txt

    return pairs


def load_alignment() -> list[dict[str, str]]:
    with ALIGNMENT.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def map_translations(rows: list[dict[str, str]]) -> tuple[dict[str, str], list[dict[str, str]]]:
    by_chapter: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        by_chapter.setdefault(int(row["chapter"]), []).append(row)

    translations = dict(OVERRIDES)
    report: list[dict[str, str]] = []

    for chapter, cards in sorted(by_chapter.items()):
        pairs = story_pairs(chapter)
        pos = 0
        fallbacks = 0

        for pt_source, en_source in pairs:
            # Skip already-overridden cards when searching forward.
            while pos < len(cards) and cards[pos]["id"] in translations:
                pos += 1
            if pos >= len(cards):
                break

            target = norm(pt_source)
            end = pos
            joined = ""
            while end < len(cards):
                joined = norm(" ".join(c["text"] for c in cards[pos : end + 1]))
                if joined == target:
                    break
                if len(joined) > len(target) + 4:
                    break
                end += 1
            if end >= len(cards) or joined != target:
                continue

            group = cards[pos : end + 1]
            en_parts = split_en(en_source)
            if len(group) == 1:
                # A single listening card may intentionally contain multiple
                # clauses/sentences (e.g. "Olhe… Cuidado!"). Keep the book's
                # complete translation together in that case.
                translations[group[0]["id"]] = strip_outer_quotes(en_source)
            elif len(en_parts) == len(group):
                for card, en in zip(group, en_parts):
                    translations[card["id"]] = en
            else:
                # Preserve the author's complete translation, but make this
                # visible in the report because it is less granular than ideal.
                fallbacks += len(group)
                for card in group:
                    translations[card["id"]] = strip_outer_quotes(en_source)
            pos = end + 1

        missing = [c["id"] for c in cards if c["id"] not in translations]
        report.append({
            "chapter": str(chapter),
            "cards": str(len(cards)),
            "mapped": str(len(cards) - len(missing)),
            "fallbacks": str(fallbacks),
            "status": "ok" if not missing else "missing:" + ",".join(missing),
        })
        print(
            f"chapter {chapter}: cards={len(cards)}, mapped={len(cards)-len(missing)}, "
            f"fallbacks={fallbacks}, missing={len(missing)}"
        )
        if missing:
            raise RuntimeError(f"Chapter {chapter}: missing translations for {missing}")

    return translations, report


def yaml_quote(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def write_deck(rows: list[dict[str, str]], translations: dict[str, str]) -> None:
    lines = ["deck: tesouro-listening", "model: words", "cards:"]
    for row in rows:
        cid = row["id"]
        ch = int(row["chapter"])
        pt = row["text"].strip()
        en = translations[cid]
        lines += [
            f"- id: {cid}",
            f"  word: {cid}",
            "  front: ''",
            f"  audio: tesouro/audio/ch{ch:02d}/{cid}.mp3",
            f"  back: {yaml_quote(f'<b>{pt}</b><br>{en}')}",
            f"  tags: [tesouro, listening, chapter{ch:02d}]",
        ]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(rows: list[dict[str, str]]) -> None:
    with REPORT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["chapter", "cards", "mapped", "fallbacks", "status"])
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    rows = load_alignment()
    assert len(rows) == 312, len(rows)
    translations, report = map_translations(rows)
    assert len(translations) == len(rows), (len(translations), len(rows))
    write_deck(rows, translations)
    write_report(report)
    print(f"generated {len(rows)} cards with English backs")


if __name__ == "__main__":
    main()
