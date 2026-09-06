#!/usr/bin/env python3
"""Build Tesouro Submerso listening cards from alignment + bilingual book text.

The alignment CSV defines the Portuguese audio-card boundaries. In the EPUB,
a logical story unit ends at an ``implicit-break`` paragraph. Inside such a
unit the layout varies: some units alternate PT/EN paragraphs, while others
contain a block of Portuguese followed by a block of English. Parsing by these
logical boundaries makes both layouts deterministic.
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


def clean_en(s: str) -> str:
    s = html.unescape(s).replace("\u200e", "").replace("\u200f", "").strip()
    return s.strip('“”"‘’').strip()


def split_en(s: str) -> list[str]:
    s = html.unescape(s).replace("\u200e", "").replace("\u200f", "").strip()
    # Parenthetical literal glosses are explanatory notes, not extra spoken
    # sentence translations; dropping them also prevents ``lit.`` being seen
    # as a false sentence boundary.
    s = re.sub(r"\s*\(lit\.[^)]*\)", "", s, flags=re.IGNORECASE)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"‘])", s)
    return [clean_en(p) for p in parts if clean_en(p)]


def story_groups(chapter: int) -> list[tuple[str, list[str]]]:
    """Return logical ``(Portuguese text, English chunks)`` story groups."""
    path = ROOT / "extracted" / "OEBPS" / f"upart-002-chapter-{chapter}.xhtml"
    root = ET.parse(path).getroot()
    text_div = next(
        (d for d in root.iter(f"{XHTML}div") if "text" in (d.get("class") or "").split()),
        None,
    )
    if text_div is None:
        raise RuntimeError(f"No story text div in {path}")

    groups: list[tuple[str, list[str]]] = []
    raw: list[tuple[str, bool]] = []
    in_story = False

    def flush() -> None:
        nonlocal raw
        if not raw:
            return
        english = [txt for txt, italic in raw if italic and not txt.lstrip().startswith("*")]
        plain = [txt for txt, italic in raw if not italic]

        # Rare identity translation (typically a proper name) is not italicized.
        if not english and len(plain) == 2 and norm(plain[0]) == norm(plain[1]):
            english = [plain[1]]
            plain = [plain[0]]

        if plain and english:
            groups.append((" ".join(plain), english))
        raw = []

    for child in list(text_div):
        tag = local(child.tag)
        txt = text_of(child)
        classes = set((child.get("class") or "").split())

        if tag == "h2":
            flush()
            in_story = txt.startswith("Section ")
            continue

        if tag == "div":
            if in_story and txt == "NOTES":
                flush()
                in_story = False
            elif in_story and "ornamental-break" in classes:
                flush()
            continue

        if not in_story or tag != "p":
            continue
        if "implicit-break" in classes:
            flush()
            continue
        if not txt or txt in {"...", "* * *"} or txt.startswith("(audio "):
            continue

        italic = any(local(d.tag) == "i" for d in child.iter())
        raw.append((txt, italic))

    flush()
    return groups


def load_alignment() -> list[dict[str, str]]:
    with ALIGNMENT.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def reconcile_units(cards: list[dict[str, str]], units: list[str]) -> list[str]:
    """Reconcile small punctuation-only differences in PT/EN segmentation."""
    units = list(units)
    while len(units) > len(cards):
        merged = False
        for i in range(len(cards) - 1, -1, -1):
            text = cards[i]["text"]
            if "…" not in text and "..." not in text:
                continue
            extra = len(units) - len(cards)
            j = i + extra - 1
            if 0 <= j < len(units) - 1:
                units[j : j + 2] = [f"{units[j]} {units[j + 1]}".strip()]
                merged = True
                break
        if not merged:
            break
    return units


def map_translations(rows: list[dict[str, str]]) -> tuple[dict[str, str], list[dict[str, str]]]:
    by_chapter: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        by_chapter.setdefault(int(row["chapter"]), []).append(row)

    translations: dict[str, str] = {}
    report: list[dict[str, str]] = []

    for chapter, cards in sorted(by_chapter.items()):
        groups = story_groups(chapter)
        pos = 0
        fallbacks = 0

        for pt_source, en_chunks in groups:
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
                raise RuntimeError(
                    f"Chapter {chapter}: source group did not match at {cards[pos]['id']}: {pt_source!r}"
                )

            group_cards = cards[pos : end + 1]
            en_units: list[str] = []
            for chunk in en_chunks:
                en_units.extend(split_en(chunk))
            en_units = reconcile_units(group_cards, en_units)

            if len(group_cards) == 1:
                translations[group_cards[0]["id"]] = " ".join(clean_en(x) for x in en_chunks)
            elif len(en_units) == len(group_cards):
                for card, en in zip(group_cards, en_units):
                    translations[card["id"]] = en
            else:
                fallbacks += len(group_cards)
                raise RuntimeError(
                    f"Chapter {chapter}: {group_cards[0]['id']}..{group_cards[-1]['id']} has "
                    f"{len(group_cards)} PT cards but {len(en_units)} EN units; "
                    f"PT={pt_source!r}; EN={en_chunks!r}"
                )

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
