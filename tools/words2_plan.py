#!/usr/bin/env python3
"""Plan the words2 cards: fields, media names, and the spelling sequences.

Turns `work/words2-glosses.json` (the English side) and the mnemonics deck's
animals into one spec file that says, for every card, exactly what text and which
clips it will hold. Nothing is generated here and nothing is sent anywhere: this
is the plan, so mistakes are found before 700 clips are recorded.

The spelling audio is built by joining one clip per letter, and the animal audio
by joining one clip per animal, so a fixed set of letter and animal clips is
recorded once and merged per word. Two rules follow from that:

* a letter with a mark on it (`ç`, `ã`, `ó`) has its own letter clip, because the
  word is spelled differently, but uses the *plain* letter's animal, because the
  animal stands for the key and the key is the same;
* every letter in a word needs an animal. The mnemonics deck has 21, leaving I, J,
  K, P and U, so those five are named here (K is included for completeness even
  though no word in this list uses it).

Media names are built from the word with accents and marks removed
(`maçã` -> `w2_maca_pt.mp3`), which could collide for two words that differ only
by an accent, so collisions are refused rather than silently overwritten.

Each card also carries the book's own sentence for its word and the chapter that
sentence comes from, as text on the back - the words were found by reading the
chapters, so the sentence that proved the word exists is the best example of it.

    python3 tools/words2_plan.py --sample 3      # print a few cards, write nothing
    python3 tools/words2_plan.py                 # write work/words2-spec.json
    python3 tools/words2_plan.py --chapters 1 --out cidadela/work/words2-spec-ch1.json
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

from cidadela_glossary_gap import plain

ROOT = Path(__file__).resolve().parents[1]
GLOSSES = ROOT / "cidadela" / "work" / "words2-glosses.json"
VOCAB = ROOT / "cidadela" / "work" / "chapter-vocab.json"
MNEMONICS = Path("/home/yu/my2/dota2/anki/mnemonics-spec.json")
OUT = ROOT / "cidadela" / "work" / "words2-spec.json"

# A letter is spoken as the character itself, and a marked letter as the character
# plus the mark's name. Anything else was tried and is worse: a name spelled out
# ("Ay") is the sound of a different letter, "ei"/"ey" come back as "Hey", and a
# carrier word ("letter A") is correct but says more than the letter. The takes
# are recorded as one list and cut apart, so these strings document the wording
# rather than drive it - see tools/words2_list_cut.py.
LETTER_SPEECH = {letter: letter.upper() for letter in "abcdefghijklmnopqrstuvwxyz"}
# A marked letter is said as the plain letter plus the mark's name, so it is heard
# as a different letter than the plain one, which is the point of spelling by
# letters; the animal stays the plain letter's.
MARKS = {"cedilla": "cedilla", "tilde": "tilde", "acute": "acute accent",
         "circumflex": "circumflex accent", "grave": "grave accent",
         "diaeresis": "diaeresis"}
ACCENT_FOR = {"ã": ("a", "tilde"), "õ": ("o", "tilde"), "ç": ("c", "cedilla"),
              "á": ("a", "acute"), "é": ("e", "acute"), "í": ("i", "acute"),
              "ó": ("o", "acute"), "ú": ("u", "acute"), "â": ("a", "circumflex"),
              "ê": ("e", "circumflex"), "ô": ("o", "circumflex"), "à": ("a", "grave"),
              "ü": ("u", "diaeresis")}
# No word in this list uses K, but the animals should cover the alphabet.
NEW_ANIMALS = {"i": "ibex", "j": "jaguar", "k": "kangaroo", "p": "penguin",
               "u": "urchin"}


def mnemonics_animals() -> dict[str, str]:
    spec = json.loads(MNEMONICS.read_text(encoding="utf-8"))["cards"]
    animals = {}
    for card in spec:
        if card["front"].endswith(" animal"):
            animals[card["front"].split()[0].lower()] = plain(card["back"].split("<")[0])
    return animals


def slug(word: str) -> str:
    """A file-name-safe form of a word: no accents, no marks, lower case."""
    return re.sub(r"[^a-z0-9]+", "_", plain(word)).strip("_")


def book_sentences() -> dict[str, dict]:
    """For each word, the first chapter it appears in and the sentence there.

    The chapter is the one the quote was actually found in, which is not always the
    chapter the word was first returned for: a sentence that could not be found in
    the text is replaced by the closest one, and the note should name the chapter
    that really holds the sentence.
    """
    found: dict[str, dict] = {}
    for entry in json.loads(VOCAB.read_text(encoding="utf-8"))["candidates"]:
        quote = entry.get("quote") or {}
        chapter = quote.get("chapter") if entry.get("in_quote") else entry["chapters"][0]
        for spelling in {entry["word"], entry["word"].replace("-se", "")}:
            found.setdefault(plain(spelling), {"sentence": entry["sentence"],
                                              "chapter": chapter or entry["chapters"][0]})
    return found


def book_for(word: str, book: dict[str, dict]) -> dict:
    """The book sentence for a word, whichever way it is spelled.

    A verb is returned by the chapter scan either as "casar" or as "casar-se",
    and the card is named whichever way the glosses file names it, so both
    spellings are tried before giving up.
    """
    for spelling in (word, word.replace("-se", ""), word + "-se"):
        if plain(spelling) in book:
            return book[plain(spelling)]
    return {}


def cards_of_chapters(numbers: list[int]) -> list[str]:
    """The words the chapter scan found in these chapters, in chapter order."""
    entries = json.loads(VOCAB.read_text(encoding="utf-8"))["candidates"]
    return [entry["word"] for entry in entries
            if any(number in entry["chapters"] for number in numbers)]


def letters_of(word: str) -> list[str]:
    """The word's letters as keys: plain, or "c_cedilla" for a marked letter."""
    keys = []
    for char in word.lower():
        if not char.isalpha():
            continue
        if char in ACCENT_FOR:
            base, mark = ACCENT_FOR[char]
            keys.append(f"{base}_{mark}")
        else:
            keys.append(unicodedata.normalize("NFD", char)[0])
    return keys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--only", default="",
                        help="comma-separated words; build the spec for just these")
    parser.add_argument("--chapters", default="",
                        help="comma-separated chapter numbers; build the spec for the words "
                             "the chapter scan found in them")
    parser.add_argument("--out", default="", help="write the spec here instead")
    args = parser.parse_args()

    cards = json.loads(GLOSSES.read_text(encoding="utf-8"))["cards"]
    book = book_sentences()
    if args.chapters:
        wanted = cards_of_chapters([int(n) for n in args.chapters.split(",") if n.strip()])
        by_plain: dict[str, dict] = {}
        for card in cards:
            by_plain.setdefault(plain(card["pt"]), card)
            by_plain.setdefault(plain(card["pt"].replace("-se", "")), card)
        missing = [word for word in wanted if plain(word) not in by_plain]
        if missing:
            raise SystemExit(f"chapter words with no gloss: {missing}")
        seen_cards = []
        for word in wanted:
            card = by_plain[plain(word)]
            if card not in seen_cards:
                seen_cards.append(card)
        cards = seen_cards
    if args.only:
        wanted = [word.strip() for word in args.only.split(",") if word.strip()]
        by_word = {card["pt"]: card for card in cards}
        unknown = [word for word in wanted if word not in by_word]
        if unknown:
            raise SystemExit(f"not in the glosses file: {unknown}")
        cards = [by_word[word] for word in wanted]
    animals = mnemonics_animals() | NEW_ANIMALS
    letter_keys = {}          # every distinct letter key across the whole deck
    for card in cards:
        for key in letters_of(card["pt"]):
            letter_keys.setdefault(key, card["pt"])

    planned = []
    for card in cards:
        keys = letters_of(card["pt"])
        name = slug(card["pt"])
        planned.append({
            "portuguese": card["pt"],
            "english": card["en"],
            "sentence": card["sentence"],
            "problems": card["problems"],
            "letters": keys,
            "book_sentence": book_for(card["pt"], book).get("sentence", ""),
            "book_chapter": book_for(card["pt"], book).get("chapter", 0),
            "animals": [animals[key.split("_")[0]] if key.split("_")[0] in animals
                        else None for key in keys],
            "media": {"english": f"w2_{name}_en.mp3", "sentence": f"w2_{name}_sent.mp3",
                      "portuguese": f"w2_{name}_pt.mp3", "letters": f"w2_{name}_letters.mp3",
                      "animals": f"w2_{name}_animals.mp3"},
        })

    # Two words that differ only by an accent would collide on one file name.
    seen: dict[str, str] = {}
    collisions = []
    for card in planned:
        for field, name in card["media"].items():
            if name in seen and seen[name] != card["portuguese"]:
                collisions.append(f"{name}: {seen[name]} and {card['portuguese']}")
            seen[name] = card["portuguese"]
    no_animal = sorted({key for card in planned for key, animal in
                        zip(card["letters"], card["animals"]) if animal is None})
    # A subset card may use a letter the full spec never needs; record it anyway.
    for card in planned:
        for key in card["letters"]:
            letter_keys.setdefault(key, card["portuguese"])
    if collisions:
        raise SystemExit("media name collisions:\n  " + "\n  ".join(collisions))
    if no_animal:
        raise SystemExit(f"letters with no animal: {no_animal}")

    spec = {
        "deck": "words2",
        "model": "words2",
        "fields": ["English", "EnglishAudio", "SentenceAudio", "Portuguese",
                   "PortugueseAudio", "LettersAudio", "AnimalsAudio", "SentenceText",
                   "Chapter", "EnglishSentence"],
        "templates": {
            # The front plays one recording per word: the word, then the sentence,
            # joined into the clip `words2_merge_audio.py` builds. The word's own
            # clip and the sentence's own clip stay in the media folder and in the
            # repo, but no field names them, so the pair cannot be heard twice.
            # The sentence is also written out under the word, because hearing a
            # sentence and reading it are not the same help, and the field is last
            # in the list only because Anki appends a field rather than inserting one.
            "Front": "{{English}}<br>"
                     "{{#EnglishSentence}}<i>{{EnglishSentence}}</i><br>{{/EnglishSentence}}"
                     "{{SentenceAudio}}",
            "Back": "{{FrontSide}}\n\n<hr id=answer>\n\n{{Portuguese}}<br>"
                    "{{PortugueseAudio}}<br>{{LettersAudio}}<br>{{AnimalsAudio}}"
                    "{{#SentenceText}}<br><br><i>{{SentenceText}}</i>"
                    "<br><small>Cap\u00edtulo {{Chapter}}</small>{{/SentenceText}}",
        },
        "letters": [{"key": key, "speech": letter_speech(key),
                     "audio": f"w2_letter_{key}.mp3"} for key in sorted(letter_keys)],
        "animals": [{"letter": key, "name": name, "speech": name.capitalize(),
                     "audio": f"w2_animal_{key}.mp3", "new": key in NEW_ANIMALS}
                    for key, name in sorted(animals.items())],
        "cards": planned,
    }

    if args.sample:
        for card in planned[: args.sample]:
            print(f'{card["portuguese"]} — {card["english"]}')
            print(f'   front text  : {card["english"]}')
            print(f'   front audio : english word, then "{card["sentence"]}"')
            print(f'   back text   : {card["portuguese"]}')
            print(f'   letters     : {card["letters"]}')
            print(f'   animals     : {card["animals"]}')
            print(f'   book text   : chapter {card["book_chapter"]}: {card["book_sentence"]}')
            print()
        return

    out = Path(args.out) if args.out else OUT
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n")
    print(f'{len(planned)} cards -> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}')
    print(f'letter clips needed: {len(letter_keys)} '
          f'({", ".join(sorted(letter_keys))})')
    print(f'animal clips needed: {len(animals)} ({len(NEW_ANIMALS)} of them new)')
    print(f'clips per card: 3 recorded + 2 merged; total recorded clips in this deck: '
          f'{len(planned) * 3 + len(letter_keys) + len(animals)}')


def letter_speech(key: str) -> str:
    """What the letter clip says: the plain letter, or the letter plus its mark."""
    if "_" in key:
        base, mark = key.split("_", 1)
        return f"{base.upper()} {MARKS[mark]}"
    return LETTER_SPEECH[key]


if __name__ == "__main__":
    main()
