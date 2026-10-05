#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XHTML = "{http://www.w3.org/1999/xhtml}"
EXISTING = ROOT / "tesouro" / "alignment-ch01-10.csv"
OUT = ROOT / "tesouro" / "full-book-local" / "text-inventory.json"


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def text_of(el: ET.Element) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def norm(text: str) -> str:
    text = html.unescape(text).casefold().replace("\u200e", "").replace("\u200f", "")
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE)


def split_sentences_verbatim(text: str) -> list[str]:
    """Split printed sentences while retaining punctuation and parentheticals."""
    starts = set("ABCDEFGHIJKLMNOPQRSTUVWXYZÁÀÂÃÉÊÍÓÔÕÚÇ0123456789“\"‘")
    parts: list[str] = []
    start = 0
    depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        if depth == 0 and char in ".!?":
            token_match = re.search(r"([\w.]+)$", text[:index + 1])
            token = token_match.group(1).casefold() if token_match else ""
            if char == "." and token in {"mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "sra.", "lit.", "e.g.", "i.e."}:
                index += 1
                continue
            look = index + 1
            while look < len(text) and text[look] in "’”\"":
                look += 1
            if look < len(text) and text[look].isspace():
                while look < len(text) and text[look].isspace():
                    look += 1
                boundary = look
                if look < len(text) and text[look] == "—":
                    look += 1
                    while look < len(text) and text[look].isspace():
                        look += 1
                if look < len(text) and text[look] in starts:
                    parts.append(text[start:boundary].strip())
                    start = boundary
                    index = boundary
                    continue
        index += 1
    parts.append(text[start:].strip())
    return [part for part in parts if part]


def story_groups(chapter: int) -> list[tuple[list[str], list[str]]]:
    path = ROOT / "extracted" / "OEBPS" / f"upart-002-chapter-{chapter}.xhtml"
    root = ET.parse(path).getroot()
    text_div = next(d for d in root.iter(f"{XHTML}div") if "text" in (d.get("class") or "").split())
    groups: list[tuple[list[str], list[str]]] = []
    raw: list[tuple[str, bool]] = []
    in_story = True

    def flush() -> None:
        nonlocal raw
        if raw:
            pt = [text for text, italic in raw if not italic]
            en = [text for text, italic in raw if italic and not text.lstrip().startswith("*")]
            if not en and len(pt) == 2 and norm(pt[0]) == norm(pt[1]):
                en, pt = [pt[1]], [pt[0]]
            if pt and en:
                groups.append((pt, en))
        raw = []

    for child in list(text_div):
        tag = local(child.tag)
        text = text_of(child)
        classes = set((child.get("class") or "").split())
        if tag == "h2":
            flush()
            in_story = text.startswith("Section ")
            continue
        if tag == "div":
            if in_story and text == "NOTES":
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
        if not text or text in {"...", "…", "* * *"} or text.startswith("(audio "):
            continue
        italic = any(local(desc.tag) == "i" for desc in child.iter())
        raw.append((text, italic))
    flush()
    return groups


def existing_by_chapter() -> dict[int, list[dict[str, str]]]:
    out: dict[int, list[dict[str, str]]] = {}
    with EXISTING.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            out.setdefault(int(row["chapter"]), []).append(row)
    return out


def reconcile_english(pt_units: list[str], en_nodes: list[str]) -> list[str]:
    if len(pt_units) == 1:
        return [" ".join(en_nodes)]
    en_units = [unit for node in en_nodes for unit in split_sentences_verbatim(node)]
    while len(en_units) > len(pt_units):
        merged = False
        for index in range(len(pt_units) - 1, -1, -1):
            if "…" not in pt_units[index] and "..." not in pt_units[index]:
                continue
            extra = len(en_units) - len(pt_units)
            en_index = index + extra - 1
            if 0 <= en_index < len(en_units) - 1:
                en_units[en_index:en_index + 2] = [f"{en_units[en_index]} {en_units[en_index + 1]}"]
                merged = True
                break
        if not merged:
            break
    return en_units


def partition_pt(pt_nodes: list[str], count: int) -> list[str]:
    units = [unit for node in pt_nodes for unit in split_sentences_verbatim(node)]
    if len(units) == count:
        return units
    if len(pt_nodes) == count:
        return pt_nodes
    raise RuntimeError(f"cannot partition Portuguese into {count}: nodes={pt_nodes!r}, units={units!r}")


def main() -> None:
    existing = existing_by_chapter()
    records: list[dict] = []
    next_id = 313
    diagnostics = []
    for chapter in range(1, 31):
        groups = story_groups(chapter)
        old = existing.get(chapter, [])
        pos = 0
        chapter_records = []
        for pt_nodes, en_nodes in groups:
            source_pt = " ".join(pt_nodes)
            if old:
                end = pos
                while end < len(old) and norm(" ".join(r["text"] for r in old[pos:end + 1])) != norm(source_pt):
                    end += 1
                if end >= len(old):
                    raise RuntimeError(f"chapter {chapter}: existing Portuguese mismatch at {pos}: {source_pt!r}")
                pt_units = [r["text"] for r in old[pos:end + 1]]
                ids = [r["id"] for r in old[pos:end + 1]]
                pos = end + 1
            else:
                pt_units = [unit for node in pt_nodes for unit in split_sentences_verbatim(node)]
                ids = [f"ts{number:04d}" for number in range(next_id, next_id + len(pt_units))]
                next_id += len(pt_units)
            en_units = reconcile_english(pt_units, en_nodes)
            if len(pt_units) != len(en_units):
                raise RuntimeError(
                    f"chapter {chapter}: PT/EN mismatch {len(pt_units)} != {len(en_units)}; "
                    f"PT={pt_units!r}; EN={en_units!r}"
                )
            for cid, pt, en in zip(ids, pt_units, en_units):
                chapter_records.append({"id": cid, "chapter": chapter, "portuguese_text": pt, "english_text": en})
        if old and pos != len(old):
            raise RuntimeError(f"chapter {chapter}: consumed {pos}/{len(old)} existing cards")
        records.extend(chapter_records)
        diagnostics.append({"chapter": chapter, "records": len(chapter_records)})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(records), "last_id": records[-1]["id"], "chapters": diagnostics}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
