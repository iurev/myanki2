#!/usr/bin/env python3
"""Read A Cidadela Misteriosa out of the EPUB into a per-sentence inventory.

The EPUB ships the book twice:

* ``part-001-chapter-00N.xhtml`` — Portuguese only;
* ``part-002-chapter-00N.xhtml`` — the interlinear edition: each Portuguese
  sentence (glossed word spans and endnote markers) followed by its English
  translation.

So the book does carry translations, and they are the translator's own. The
Portuguese list is taken from part-001, because that is the edition the recording
narrates: a probe of the audio found all four places where the two editions
differ, and in every one the part-001 sentence is in the recording. The English is
then read off part-002 sentence by sentence, with two hand-checked reassignments
(see ``english-reassignments.json``) where the interlinear edition keeps a
translation on the following line, and a translation step for whatever is left.

    python3 tools/cidadela_inventory.py --chapters 1-5
"""
from __future__ import annotations

import argparse
import html
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRACTED = ROOT / "extracted2" / "OEBPS"
WORK = ROOT / "cidadela" / "work"
OUT = WORK / "text-inventory.json"
REASSIGNMENTS = WORK / "english-reassignments.json"
FILLS = WORK / "english-fills.json"
NEEDED = WORK / "english-needed.json"


def paragraphs(path: Path) -> list[tuple[str, str, str]]:
    """Every <p> in the body text as (class, kind, text).

    Endnote markers are dropped whole: their visible text is a footnote number
    that would otherwise land inside the sentence ("vive na1 capital").
    """
    source = path.read_text(encoding="utf-8")
    body = source.split('<div class="text"', 1)[1]
    rows = []
    for match in re.finditer(r"<p\b([^>]*)>(.*?)</p>", body, flags=re.S):
        attributes, inner = match.group(1), match.group(2)
        inner = re.sub(r"<sup>.*?</sup>", "", inner, flags=re.S)
        translation = "<i>" in inner
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", inner))).strip()
        kind = "translation" if translation else "portuguese"
        rows.append((attributes, kind, text))
    return rows


def sentences(path: Path) -> list[str]:
    """The Portuguese sentences of a chapter, in order, without the audio marker."""
    return [text for _, _, text in paragraphs(path) if text and not text.startswith("áudio")]


def translated_pairs(path: Path) -> list[dict]:
    """Pair each Portuguese sentence with the English that follows it."""
    pairs = []
    pending = None
    for _, kind, text in paragraphs(path):
        if not text or text.startswith("áudio"):
            continue
        if kind == "translation":
            if pending is not None:
                pairs.append({"portuguese_text": pending, "english_text": text})
                pending = None
        else:
            pending = text
    return pairs


def pair_english(chapter: int, portuguese: list[str], pairs: list[dict]) -> list[tuple[str | None, str]]:
    """Give every narrated sentence its English, with the source of that English.

    The two editions have drifted apart in four places, so an alignment is not
    trusted to land the translations by itself: the equal blocks carry part-002's
    English across, and the four disagreements are handled by name.
    """
    reassignments = {f"{row['chapter']}:{row['portuguese_text']}": row['english_text']
                     for row in json.loads(REASSIGNMENTS.read_text())}
    fills = {f"{row['chapter']}:{row['portuguese_text']}": row
             for row in (json.loads(FILLS.read_text()) if FILLS.is_file() else [])}

    from_part_002: dict[int, str] = {}
    matcher = SequenceMatcher(None, portuguese, [pair["portuguese_text"] for pair in pairs], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                from_part_002[i1 + offset] = pairs[j1 + offset]["english_text"]

    # A reassignment takes an English sentence off the line it was printed on,
    # so the line it came from is left without one of its own. Those lines are
    # sign and label text the interlinear edition never translated separately.
    for sentence in portuguese:
        reassigned = reassignments.get(f"{chapter}:{sentence}")
        if not reassigned:
            continue
        holding = [index for index, pair in enumerate(pairs) if pair["english_text"] == reassigned]
        if len(holding) != 1:
            raise SystemExit(f"chapter {chapter}: reassignment matches {len(holding)} lines, expected 1: {sentence!r}")
        for index, english in list(from_part_002.items()):
            if english == reassigned:
                del from_part_002[index]

    out: list[tuple[str | None, str]] = []
    for index, sentence in enumerate(portuguese):
        key = f"{chapter}:{sentence}"
        if key in reassignments:
            out.append((reassignments[key], "part-002 (kept on the following line)"))
        elif key in fills:
            out.append((fills[key]["english_text"], "translated"))
        elif index in from_part_002:
            out.append((from_part_002[index], "part-002"))
        else:
            out.append((None, "missing"))
    return out


def chapter_title(path: Path) -> str:
    match = re.search(r"<title>([^<]*)</title>", path.read_text(encoding="utf-8"))
    title = html.unescape(match.group(1)) if match else ""
    return re.sub(r"^Chapter\s+\d+:\s*", "", title).strip()


def parse_chapters(text: str) -> list[int]:
    chapters = []
    for part in text.split(","):
        if "-" in part:
            low, high = part.split("-")
            chapters.extend(range(int(low), int(high) + 1))
        else:
            chapters.append(int(part))
    return chapters


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapters", default="1-5")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    records, differences, report, needed = [], [], [], []
    for chapter in parse_chapters(args.chapters):
        portuguese = sentences(EXTRACTED / f"part-001-chapter-{chapter:03d}.xhtml")
        pairs = translated_pairs(EXTRACTED / f"part-002-chapter-{chapter:03d}.xhtml")
        if not pairs:
            raise SystemExit(f"chapter {chapter}: no translated pairs found")
        if any(not pair["english_text"] for pair in pairs):
            raise SystemExit(f"chapter {chapter}: a pair is missing its English text")

        # Where the two editions differ, the difference is written out rather
        # than quietly resolved: it is also what the audio was probed against.
        matcher = SequenceMatcher(None, portuguese, [pair["portuguese_text"] for pair in pairs], autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            report.append({
                "chapter": chapter, "change": tag,
                "part_001_only": portuguese[i1:i2],
                "part_002_only": [pair["portuguese_text"] for pair in pairs][j1:j2],
            })

        title = chapter_title(EXTRACTED / f"part-002-chapter-{chapter:03d}.xhtml")
        for sentence, (english, provenance) in zip(portuguese, pair_english(chapter, portuguese, pairs)):
            records.append({"chapter": chapter, "chapter_title": title,
                            "portuguese_text": sentence, "english_text": english,
                            "english_source": provenance})
            if english is None:
                needed.append({"chapter": chapter, "portuguese_text": sentence})
        differences.append({"chapter": chapter, "part_001_sentences": len(portuguese),
                            "pairs": len(pairs), "title": title})

    for index, record in enumerate(records, start=1):
        record["id"] = f"cm{index:04d}"
    records = [{"id": r["id"], "chapter": r["chapter"], "chapter_title": r["chapter_title"],
                "portuguese_text": r["portuguese_text"], "english_text": r["english_text"],
                "english_source": r["english_source"]} for r in records]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    (args.out.parent / "part-divergences.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    NEEDED.write_text(json.dumps(needed, ensure_ascii=False, indent=2) + "\n")
    sources: dict[str, int] = {}
    for record in records:
        sources[record["english_source"]] = sources.get(record["english_source"], 0) + 1
    print(json.dumps({
        "chapters": differences,
        "records": len(records),
        "english_missing": sum(1 for r in records if not r["english_text"]),
        "english_sources": sources,
        "duplicate_pt": len(records) - len({r["portuguese_text"] for r in records}),
        "divergences": len(report),
        "needs_translation": needed,
        "out": str(args.out.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
