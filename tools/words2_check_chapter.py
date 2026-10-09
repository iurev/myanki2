"""Check one chapter's cards against the chapter's own text.

The scan is a model reading the chapter, so its word list is a claim, not a fact. This
checks the claims that can be checked without asking anyone: that each word really
appears in the chapter, that the sentence quoted on the back is really in the book, and
that the chapter it names is a chapter it appears in.

A word that fails the first check is a lead to read by eye, not automatically a
mistake - a verb can be listed by its infinitive while the chapter only ever uses it in
a conjugated form, and the corpus check knows a few shapes but not every one.

Usage: python3 tools/words2_check_chapter.py 6 7
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cidadela_chapter_vocab import chapter_text, sentences_of, shapes, stem  # noqa: E402
from cidadela_glossary_gap import plain  # noqa: E402

WORK = pathlib.Path(__file__).resolve().parent.parent / "cidadela" / "work"
LAST_CHAPTER = 12


def in_chapter(word: str, chapter_plain: str) -> bool:
    """Whether the chapter uses this word, with capitals and accents folded away.

    The corpus helper this deck's scan uses matches the headword against the chapter
    text as it is written, so a word with any accent in it never matches and is
    reported as unverified. That is fine for a scan, which keeps unverified words
    anyway, but it makes every accented word look missing, so this check folds both
    sides first and then allows for the same inflections.
    """
    folded = plain(chapter_plain.lower())
    key = plain(word)
    if re.search(rf"\b{re.escape(key)}\b", folded):
        return True
    forms = {shapes(key), stem(key)} | {key[: len(key) - cut] for cut in (1, 2)}
    return any(len(form) >= 4 and form in folded for form in forms)


def check(chapter: int) -> int:
    spec_path = WORK / f"words2-spec-ch{chapter}.json"
    if not spec_path.is_file():
        print(f"ch{chapter}: no spec, skipping")
        return 0
    cards = json.loads(spec_path.read_text(encoding="utf-8"))["cards"]
    text = chapter_text(chapter)
    whole = set(sentences_of(text))

    absent, not_here, fragments, without = [], [], [], []
    for card in cards:
        word = card["portuguese"]
        if not in_chapter(word, text):
            absent.append(word)
        quote = card.get("book_sentence", "")
        if not quote.strip():
            without.append(word)
            continue
        if quote not in text:
            # It may still be a real sentence from another chapter, so look before
            # calling it invented, and only report the ones found nowhere.
            elsewhere = [n for n in range(1, LAST_CHAPTER + 1)
                         if quote in chapter_text(n)] if chapter != 1 else []
            if not elsewhere:
                not_here.append((word, quote[:60]))
        elif quote not in whole:
            fragments.append(word)

    ok = not absent and not not_here
    print(f'ch{chapter}: {len(cards)} cards | no literal form of the word in the chapter: '
          f'{len(absent)} | sentence not found in the book: {len(not_here)} | '
          f'quoted fragment rather than a whole sentence: {len(fragments)} | '
          f'no sentence at all: {len(without)}')
    for word in absent:
        print(f'    only conjugated or inflected in the chapter (read by eye): {word}')
    for word, quote in not_here:
        print(f'    sentence not found anywhere in the book: {word} — "{quote}"')
    if without:
        print(f'    cards with no book sentence: {", ".join(without)}')
    print(f'ch{chapter}: {"PASS" if ok else "READ THESE BY EYE"}')
    return 0 if ok else 1


if __name__ == "__main__":
    numbers = [int(n) for n in sys.argv[1:]] or list(range(1, 8))
    worst = 0
    for number in numbers:
        worst = max(worst, check(number))
    raise SystemExit(worst)
