#!/usr/bin/env python3
"""Build Tesouro Submerso listening cards from sentence alignment + book English.

The alignment CSV is the source of truth for Portuguese card boundaries. The
chapter XHTML already contains the author's English story translation, but its
layout is not consistent: some sections alternate PT/EN paragraphs and others
place several Portuguese lines before their English translations. Instead of
pairing DOM paragraphs, this script extracts English story units in order and
maps them to the already-aligned Portuguese cards.
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
    """Split an English story paragraph into card-sized sentence/utterance units."""
    s = html.unescape(strip_outer_quotes(s))
    # The book occasionally has dialogue quotes spanning multiple sentences.
    # Keep punctuation on each sentence but strip quote characters at edges.
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"‘])", s)
    return [strip_outer_quotes(p.strip()) for p in parts if p.strip()]


def story_paragraphs(chapter: int) -> list[tuple[str, bool]]:
    """Return (text, has_italic) story paragraphs only, excluding notes/exercises."""
    path = ROOT / "extracted" / "OEBPS" / f"upart-002-chapter-{chapter}.xhtml"
    root = ET.parse(path).getroot()
    text_div = next(
        (d for d in root.iter(f"{XHTML}div") if "text" in (d.get("class") or "").split()),
        None,
    )
    if text_div is None:
        raise RuntimeError(f"No story text div in {path}")

    out: list[tuple[str, bool]] = []
    in_story = False
    for child in list(text_div):
        tag = local(child.tag)
        txt = text_of(child)
        if tag == "h2":
            in_story = txt.startswith("Section ")
            continue
        if tag == "div" and in_story and txt == "NOTES":
            in_story = False
            continue
        if not in_story or tag != "p":
            continue
        if not txt or txt in {"...", "* * *"} or txt.startswith("(audio "):
            continue
        out.append((txt, any(local(d.tag) == "i" for d in child.iter())))
    return out


def english_units(chapter: int) -> list[str]:
    """Extract author English story units in reading order.

    Most translations contain <i>. A few identity translations (names such as
    João.) are plain text; those are detected when two adjacent plain story
    paragraphs normalize to the same content.
    """
    paras = story_paragraphs(chapter)
    chunks: list[str] = []
    pending_plain: str | None = None

    for txt, italic in paras:
        if italic:
            chunks.append(txt)
            pending_plain = None
            continue

        if pending_plain is not None and norm(pending_plain) == norm(txt):
            chunks.append(txt)
            pending_plain = None
        else:
            pending_plain = txt

    units: list[str] = []
    for chunk in chunks:
        units.extend(split_en(chunk))
    return units


def load_alignment() -> list[dict[str, str]]:
    with ALIGNMENT.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def map_translations(rows: list[dict[str, str]]) -> tuple[dict[str, str], list[dict[str, str]]]:
    by_chapter: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        by_chapter.setdefault(int(row["chapter"]), []).append(row)

    translations: dict[str, str] = {}
    report: list[dict[str, str]] = []

    for chapter, cards in sorted(by_chapter.items()):
        en = english_units(chapter)
        report.append({
            "chapter": str(chapter),
            "cards": str(len(cards)),
            "english_units": str(len(en)),
            "status": "ok" if len(cards) == len(en) else "count-mismatch",
        })
        print(f"chapter {chapter}: cards={len(cards)}, english_units={len(en)}")
        if len(cards) != len(en):
            print("ENGLISH UNITS:")
            for i, unit in enumerate(en, 1):
                print(f"  {i:03d}: {unit}")
            raise RuntimeError(
                f"Chapter {chapter}: {len(cards)} aligned cards but {len(en)} English units"
            )
        for card, translation in zip(cards, en):
            translations[card["id"]] = translation

    return translations, report


def yaml_quote(s: str) -> str:
    # JSON string syntax is valid YAML and robust around colons/quotes/unicode.
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
        w = csv.DictWriter(f, fieldnames=["chapter", "cards", "english_units", "status"])
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    rows = load_alignment()
    translations, report = map_translations(rows)
    assert len(rows) == 312, len(rows)
    assert len(translations) == len(rows), (len(translations), len(rows))
    write_deck(rows, translations)
    write_report(report)
    print(f"generated {len(rows)} cards with author English translations")


if __name__ == "__main__":
    main()
