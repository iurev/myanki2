#!/usr/bin/env python3
"""Compare book2's own glossary with the words already in the yaml decks.

The book is *A Cidadela Misteriosa* (book2), whose extraction is `extracted2/`.
Take care with the other extraction: `extracted/`, `book.epub` and everything
named `upart-*` belong to *O Tesouro Submerso*, the first book, whose glossary
shares the series' vocabulary and so would flatter the overlap enormously.

Book2's glossary is not a word list with sections -- it is the book's endnotes,
one numbered entry per glossed item, grouped under a heading per chapter, each
entry a headword, a gloss, and often an example sentence:

    <h2 ...>3. The poisoned apple</h2>
    <div id="part-2-chapter-3-endnote-8-text" class="endnote-text">
      <p class="first"><span ...><a ...>8</a></span><b>rir-se</b>: to laugh (reflexive verb)</p>
      <p class="subsq"><i>... (He laughs.)</i></p>

Matching, stated plainly because the count depends on it:

* accents and case are ignored, so `será que` matches `sera que`;
* a leading article is dropped, so `a senhora` is `senhora`;
* an entry naming two words (`um, uma`) is two terms;
* a yaml headword naming alternatives (`um / uma`, `dia (m)`) is several terms.

Each unheld entry is then put in one of two groups, because "not in the yaml" is
not the same as "a word to learn":

* *pattern* -- some word in the headword is already held, so this is a
  construction with words already in the decks (`ter + de + infinitive`,
  `voltar para casa` when `voltar` and `casa` are held);
* *new vocabulary* -- no word in the headword is held.

Writes `glossary-gap.md` and `work/glossary-gap.json`.

    python3 tools/cidadela_glossary_gap.py
"""
from __future__ import annotations

import html
import json
import re
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GLOSSARY = ROOT / "extracted2" / "OEBPS" / "part-004-glossary.xhtml"
OUT_JSON = ROOT / "cidadela" / "work" / "glossary-gap.json"
OUT_MD = ROOT / "cidadela" / "glossary-gap.md"
DECK_CHAPTERS = 5
YAML_FILES = ("nouns.yaml", "verbs.yaml", "adjectives.yaml", "phrases.yaml", "location.yaml",
              "numbers.yaml", "level0.yaml", "ta.yaml", "tesouro-listening.yaml")
ARTICLES = {"a", "o", "as", "os", "um", "uma"}
YAML_ANNOTATION = re.compile(r"\s*\([^)]*\)")


def plain(text: str) -> str:
    """Lower case, no accents, no markup, no stray spaces."""
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def readable(text: str) -> str:
    """The printed words, markup removed, spelling and case kept."""
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\s+", " ", text).strip()


def terms(text: str) -> list[str]:
    """The separate headwords a printed entry names."""
    found = []
    for chunk in re.split(r"[/,]", YAML_ANNOTATION.sub(" ", text)):
        # The glossary draws some headwords with their own punctuation inside the
        # bold run ("já não (verb) há:"), which is not part of the word.
        chunk = plain(chunk).strip(" :;.,-–—")
        if chunk:
            found.append(chunk)
    return found


def strip_article(term: str) -> str:
    words = term.split()
    return " ".join(words[1:]) if len(words) > 1 and words[0] in ARTICLES else term


def read_glossary() -> list[dict]:
    source = GLOSSARY.read_text(encoding="utf-8")
    body = source[source.find("<body"):]
    chapters = re.split(r"<h2[^>]*>(.*?)</h2>", body)
    entries = []
    for index in range(1, len(chapters), 2):
        chapter = readable(chapters[index])
        number = int(match.group(1)) if (match := re.match(r"(\d+)\.", chapter)) else 0
        for block in re.findall(r'<div[^>]*class="endnote-text"[^>]*>(.*?)</div>', chapters[index + 1], re.S):
            first = re.search(r'<p class="first">(.*?)</p>', block, re.S)
            if not first:
                continue
            bold = re.findall(r"<b>(.*?)</b>", first.group(1), re.S)
            endnote = re.search(r">(\d+)</a>", first.group(1))
            gloss = readable(re.sub(re.escape(bold[0]), " ", first.group(1), count=1)) if bold else ""
            example = re.search(r'<p class="subsq"><i>(.*?)</i>', block, re.S)
            entries.append({
                "chapter": chapter,
                "chapter_number": number,
                "endnote": int(endnote.group(1)) if endnote else None,
                "printed": readable(bold[0]) if bold else readable(first.group(1)),
                "gloss": re.sub(r"^\d+\s*", "", gloss).lstrip(": ").strip(),
                "example": readable(example.group(1)) if example else "",
            })
    return entries


def read_yaml_words() -> dict[str, list[str]]:
    """Every headword held, and the files that hold it."""
    held: dict[str, list[str]] = {}
    for name in YAML_FILES:
        path = ROOT / name
        if not path.is_file():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for card in data.get("cards", []):
            word = card.get("word")
            if not word:
                continue
            for term in terms(str(word)):
                held.setdefault(strip_article(term), []).append(name)
    return held


def main() -> None:
    entries = read_glossary()
    held = read_yaml_words()

    kept: dict[str, dict] = {}
    for entry in entries:
        term = strip_article(terms(entry["printed"])[0]) if terms(entry["printed"]) else ""
        entry["term"] = term
        entry["files"] = sorted(set(held.get(term, [])))
        if term in held:
            entry["verdict"] = "held"
        elif any(word in held for word in re.split(r"[^\w-]+", term) if word):
            entry["verdict"] = "pattern"
        else:
            entry["verdict"] = "new vocabulary"
        kept.setdefault(term, entry)

    counts: dict[str, int] = {}
    for entry in kept.values():
        counts[entry["verdict"]] = counts.get(entry["verdict"], 0) + 1
    scoped = {term: entry for term, entry in kept.items() if entry["chapter_number"] <= DECK_CHAPTERS}
    scoped_counts: dict[str, int] = {}
    for entry in scoped.values():
        scoped_counts[entry["verdict"]] = scoped_counts.get(entry["verdict"], 0) + 1

    report = {
        "glossary_file": str(GLOSSARY.relative_to(ROOT)),
        "glossary_entries": len(entries),
        "distinct_headwords": len(kept),
        "verdicts": counts,
        "chapters_1_to_5": {"headwords": len(scoped), "verdicts": scoped_counts},
        "entries": [{"printed": entry["printed"], "term": entry["term"], "verdict": entry["verdict"],
                     "gloss": entry["gloss"], "chapter": entry["chapter"],
                     "chapter_number": entry["chapter_number"], "endnote": entry["endnote"],
                     "example": entry["example"], "files": entry["files"]}
                    for entry in kept.values()],
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    def by_chapter(selection: dict[str, dict]) -> list[str]:
        lines = []
        for number in range(1, 13):
            chapter = [entry for entry in selection.values() if entry["chapter_number"] == number]
            if not chapter:
                continue
            title = chapter[0]["chapter"].split(". ", 1)[-1]
            unheld = [entry for entry in chapter if entry["verdict"] != "held"]
            fresh = [entry for entry in chapter if entry["verdict"] == "new vocabulary"]
            lines.append(f"### Chapter {number} — {title}")
            lines.append(f"{len(chapter)} glossed items, {len(unheld)} not held, "
                         f"{len(fresh)} of them new vocabulary.")
            lines.append("")
            for entry in chapter:
                mark = {"held": "held", "pattern": "pattern", "new vocabulary": "**NEW**"}[entry["verdict"]]
                lines.append(f"- {mark} — **{entry['printed']}** — {entry['gloss']}")
            lines.append("")
        return lines

    lines = ["# Book2 glossary vs the yaml decks", "",
             f"Source: `{report['glossary_file']}` (the book's own endnote glossary, 12 chapters).",
             "",
             f"- entries: **{len(entries)}**, distinct headwords **{len(kept)}**",
             f"- already held in yaml: **{counts.get('held', 0)}**",
             f"- not held, but built on words already held (patterns): **{counts.get('pattern', 0)}**",
             f"- not held, no word in the entry held (new vocabulary): **{counts.get('new vocabulary', 0)}**",
             "",
             f"Chapters 1–5, the part the listening deck covers: **{len(scoped)}** headwords, "
             f"{scoped_counts.get('held', 0)} held, {scoped_counts.get('pattern', 0)} patterns, "
             f"{scoped_counts.get('new vocabulary', 0)} new vocabulary.",
             "",
             "A *pattern* means the entry is a construction whose words are already in the decks "
             "(`ter + de + infinitive`, `voltar para casa`); a *new vocabulary* entry has no held "
             "word in it at all.", "",
             "Known limits of the rule: it compares headwords as printed, so an inflected form of a "
             "held word is called new vocabulary (`dizem`, where `dizer` is held), and it does not "
             "know a clitic when it sees one (`atira-a`, `atacá-lo`). Read the lists below rather "
             "than trusting the totals alone.", "",
             "## Chapters 1–5 (this deck)", ""]
    lines += by_chapter(scoped)
    lines += ["## Chapters 6–12 (rest of the book)", ""]
    lines += by_chapter(kept)
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "entries"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
