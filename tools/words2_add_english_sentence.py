#!/usr/bin/env python3
"""Add the front's English sentence as text: a tenth field, plus the template that shows it.

The words2 front already says the English word and plays the merged clip that speaks the
word and then the example sentence. What it could not do is *show* the sentence, because no
field held it: `SentenceText` carries the book's own Portuguese sentence on the back, and the
English example sentence existed only inside the recording. This adds `EnglishSentence` and
wires it into the front, after the word and before the audio.

Three things make this safe rather than merely done:

  * `fields` grows by exactly one name, at the end, because Anki appends a new field and
    `words2_anki.py` refuses to reshape a note type whose existing fields are not a prefix
    of the spec's.
  * Every other key of every spec is hashed before and after the rewrite, and the tool exits
    non-zero if a single one of them moved. `cards` in particular must come through untouched:
    those specs are the source of truth for 396 notes and a rebuild of them once silently
    dropped four translations.
  * The originals are copied to `cidadela/work/backup-english-sentence/` first.

`--fill-missing` is the second half. The twelve chapter specs own 395 words; `andar` is owned
by the pilot specs alone, which predate the book sentence and have no `book_sentence` or
`book_chapter` - so re-uploading one of those specs wholesale would blank the notes' text
side. Instead their notes get the one new field set, and nothing else.

    python3 tools/words2_add_english_sentence.py --check
    python3 tools/words2_add_english_sentence.py
    python3 tools/words2_add_english_sentence.py --fill-missing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from words2_anki import anki  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORK = ROOT / "cidadela" / "work"
BACKUP = WORK / "backup-english-sentence"
FIELD = "EnglishSentence"
FRONT = ("{{English}}<br>"
         "{{#EnglishSentence}}<i>{{EnglishSentence}}</i><br>{{/EnglishSentence}}"
         "{{SentenceAudio}}")
DECK, MODEL = "words2", "words2"
PILOT_SPECS = ["words2-spec-pilot.json", "words2-spec.json"]


def specs() -> list[pathlib.Path]:
    return sorted(WORK.glob("words2-spec*.json"))


def digest(spec: dict, skip: tuple[str, ...]) -> dict:
    """A hash per top-level key, so "only these two changed" is proved, not claimed."""
    return {key: hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        for key, value in spec.items() if key not in skip}


def patch(spec: dict) -> dict:
    fields = list(spec["fields"])
    if FIELD not in fields:
        fields.append(FIELD)
    front = spec["templates"]["Front"]
    if FIELD not in front:
        front = FRONT
    out = dict(spec)
    out["fields"] = fields
    out["templates"] = dict(spec["templates"], Front=front)
    return out


def check() -> None:
    problems = []
    for path in specs():
        spec = json.loads(path.read_text(encoding="utf-8"))
        fields = spec.get("fields", [])
        if fields[-1:] != [FIELD]:
            problems.append(f"{path.name}: {FIELD} is not the last field ({fields[-1:]})")
        if FIELD not in spec.get("templates", {}).get("Front", ""):
            problems.append(f"{path.name}: the front template does not show {FIELD}")
        empty = [c.get("portuguese") for c in spec["cards"]
                 if not str(c.get("sentence", "")).strip()]
        if empty:
            problems.append(f"{path.name}: {len(empty)} card(s) have no English sentence "
                            f"to show, e.g. {empty[:5]}")
    print(f"specs: {len(specs())}, field {FIELD!r} last, shown on the front, "
          f"{'all cards have a sentence' if not problems else f'{len(problems)} problem(s)'}")
    for problem in problems:
        print(f"  FAIL {problem}")
    if problems:
        raise SystemExit(1)


def apply() -> None:
    BACKUP.mkdir(parents=True, exist_ok=True)
    changed = 0
    for path in specs():
        original = path.read_text(encoding="utf-8")
        spec = json.loads(original)
        after = patch(spec)
        before_hashes = digest(spec, skip=("fields", "templates"))
        after_hashes = digest(after, skip=("fields", "templates"))
        if before_hashes != after_hashes:
            raise SystemExit(f"{path.name}: rewriting would have moved a key it must not touch: "
                             f"{[k for k in before_hashes if before_hashes[k] != after_hashes.get(k)]}")
        if spec["templates"].get("Back") != after["templates"].get("Back"):
            raise SystemExit(f"{path.name}: the back template changed")
        if spec["cards"] != after["cards"]:
            raise SystemExit(f"{path.name}: the cards changed")
        if after == spec:
            continue
        backup = BACKUP / path.name
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        changed += 1
        print(f"{path.name}: fields {len(spec['fields'])} -> {len(after['fields'])}, "
              f"front now shows {FIELD}")
    print(f"{changed} spec file(s) rewritten, originals in "
          f"{BACKUP.relative_to(ROOT)}; every other key proved identical")


def fill_missing() -> None:
    """Set the new field on notes the chapter specs do not own, and only that field."""
    wanted = {}
    for name in PILOT_SPECS:
        path = WORK / name
        if path.exists():
            for card in json.loads(path.read_text(encoding="utf-8"))["cards"]:
                if str(card.get("sentence", "")).strip():
                    wanted.setdefault(card["portuguese"], card["sentence"])
    notes = anki("notesInfo", notes=anki("findNotes", query=f"tag:{DECK}"))
    print(f"deck: {len(notes)} note(s), {len(wanted)} word(s) known only to the pilot specs")
    filled = 0
    for note in notes:
        word = note["fields"]["Portuguese"]["value"]
        if word not in wanted:
            continue
        have = note["fields"].get(FIELD, {}).get("value", "")
        if have == wanted[word]:
            continue
        anki("updateNoteFields", note={"id": note["noteId"], "fields": {FIELD: wanted[word]}})
        print(f'  {word}: {have!r} -> {wanted[word]!r}')
        filled += 1
    print(f"{filled} note(s) filled")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="prove the specs are in the new shape")
    parser.add_argument("--fill-missing", action="store_true",
                        help="set the field on notes owned by the pilot specs only")
    args = parser.parse_args()
    if args.check:
        check()
    elif args.fill_missing:
        fill_missing()
    else:
        apply()
        check()


if __name__ == "__main__":
    main()
