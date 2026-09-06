#!/usr/bin/env python3
"""Build the Tesouro Submerso listening deck from aligned Portuguese clips and
English translations embedded in the EPUB chapter XHTML files.

The alignment CSV defines the final sentence/utterance boundaries. This script
maps those utterances back to the book's bilingual story pairs, reuses the
book's English translation whenever it can split it one-to-one, and records any
fallbacks that need review.
"""
from __future__ import annotations

import csv
import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT = ROOT / "tesouro" / "alignment-ch01-10.csv"
OUT = ROOT / "tesouro-listening.yaml"
FALLBACKS = ROOT / "tesouro" / "translation-fallbacks.csv"
XHTML = "{http://www.w3.org/1999/xhtml}"


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def text_of(el: ET.Element) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def norm_match(s: str) -> str:
    """Loose PT matching: alignment and EPUB sometimes differ only in punctuation."""
    s = html.unescape(s).casefold()
    return re.sub(r"[^\w]+", "", s, flags=re.UNICODE)


def strip_outer_quotes(s: str) -> str:
    s = s.strip()
    pairs = [("“", "”"), ('"', '"'), ("‘", "’")]
    for a, b in pairs:
        if s.startswith(a) and s.endswith(b):
            return s[1:-1].strip()
    return s


def split_en(s: str) -> list[str]:
    s = html.unescape(strip_outer_quotes(s))
    # Most source pairs are ordinary sentence sequences. Split only on strong
    # sentence punctuation followed by the beginning of another sentence.
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"‘])", s)
    return [p.strip() for p in parts if p.strip()]


def story_pairs(chapter: int) -> list[tuple[str, str]]:
    path = ROOT / "extracted" / "OEBPS" / f"upart-002-chapter-{chapter}.xhtml"
    root = ET.parse(path).getroot()
    text_div = None
    for div in root.iter(f"{XHTML}div"):
        if "text" in (div.get("class") or "").split():
            text_div = div
            break
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

        has_italic = any(local(desc.tag) == "i" for desc in child.iter())
        if has_italic:
            if pending is None:
                continue
            pairs.append((pending, txt))
            pending = None
            continue

        # Almost every English translation is italicized. A handful of lines
        # such as a person's name are intentionally identical in both
        # languages and may lack <i>; recognize those as the translation.
        if pending is not None and norm_match(pending) == norm_match(txt):
            pairs.append((pending, txt))
            pending = None
            continue
        pending = txt

    return pairs


def load_alignment() -> list[dict[str, str]]:
    with ALIGNMENT.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def map_translations(rows: list[dict[str, str]]) -> tuple[dict[str, str], list[dict[str, str]]]:
    translations: dict[str, str] = {}
    fallbacks: list[dict[str, str]] = []

    by_chapter: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        by_chapter.setdefault(int(row["chapter"]), []).append(row)

    for chapter, cards in sorted(by_chapter.items()):
        pairs = story_pairs(chapter)
        pos = 0

        for pt_source, en_source in pairs:
            if pos >= len(cards):
                break

            target = norm_match(pt_source)
            joined = ""
            end = pos
            while end < len(cards):
                joined = norm_match(" ".join(c["text"] for c in cards[pos : end + 1]))
                if joined == target:
                    break
                if len(joined) > len(target) + 4:
                    break
                end += 1

            if end >= len(cards) or joined != target:
                continue

            group = cards[pos : end + 1]
            en_parts = split_en(en_source)
            if len(en_parts) == len(group):
                for card, en in zip(group, en_parts):
                    translations[card["id"]] = en
            elif len(group) == 1:
                translations[group[0]["id"]] = en_source.strip()
            else:
                # Keep the author's translation rather than inventing one.
                # This is deliberately noisy so every mismatch is visible in
                # translation-fallbacks.csv for manual cleanup.
                for card in group:
                    translations[card["id"]] = en_source.strip()
                    fallbacks.append(
                        {
                            "id": card["id"],
                            "chapter": str(chapter),
                            "text": card["text"],
                            "source_portuguese": pt_source,
                            "source_english": en_source,
                            "reason": f"{len(group)} PT cards vs {len(en_parts)} EN sentence(s)",
                        }
                    )
            pos = end + 1

        if pos != len(cards):
            missing = [c["id"] for c in cards[pos:] if c["id"] not in translations]
            raise RuntimeError(
                f"Chapter {chapter}: failed to map {len(missing)} aligned card(s): {missing[:10]}"
            )

    return translations, fallbacks


def yaml_quote(s: str) -> str:
    # JSON string syntax is valid YAML and avoids multiline/colon surprises.
    import json
    return json.dumps(s, ensure_ascii=False)


def write_deck(rows: list[dict[str, str]], translations: dict[str, str]) -> None:
    lines = ["deck: tesouro-listening", "model: words", "cards:"]
    for row in rows:
        cid = row["id"]
        ch = int(row["chapter"])
        pt = row["text"]
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


def write_fallbacks(rows: list[dict[str, str]]) -> None:
    fields = ["id", "chapter", "text", "source_portuguese", "source_english", "reason"]
    with FALLBACKS.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    rows = load_alignment()
    translations, fallbacks = map_translations(rows)
    if len(translations) != len(rows):
        raise RuntimeError(f"Mapped {len(translations)} translations for {len(rows)} cards")
    write_deck(rows, translations)
    write_fallbacks(fallbacks)
    print(f"generated {len(rows)} cards")
    print(f"translation fallbacks needing review: {len(fallbacks)}")


if __name__ == "__main__":
    main()
