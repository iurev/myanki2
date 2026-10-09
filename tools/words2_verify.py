#!/usr/bin/env python3
"""Check the words2 deck against its spec, read-only, from Anki's side.

The spec says what the deck should hold; this reads the deck back out of Anki and
compares, so the deck is judged by what Anki actually has rather than by what the
sync said it did:

* the note type exists with exactly the fields and templates the spec names;
* every card in the spec is in the deck, once, matched on the Portuguese field;
* every field holds what the spec says, clip tags included;
* every clip a field names is served by Anki, byte for byte the same as on disk.

Nothing is written. `--self-test` shows each check can fail, because a check that
cannot fail proves nothing.

    python3 tools/words2_verify.py --spec cidadela/work/words2-spec-pilot.json
    python3 tools/words2_verify.py --self-test
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from words2_anki import AUDIO, anki, fields_of  # noqa: E402  (shares the same Anki calls)

ROOT = Path(__file__).resolve().parents[1]
FIELD = re.compile(r"\[sound:([^\]]+)\]")


def compare(spec: dict, notes: list[dict], media: dict[str, str], disk: dict[str, str],
            fields_have: list[str], templates: dict, subset: bool = False) -> list[str]:
    """Every way the deck differs from the spec, as plain sentences.

    `subset` is for a spec that covers part of the deck rather than all of it - the
    deck is built chapter by chapter, so the spec being checked holds one chapter's
    words while the deck also holds the others. What the spec does name is still
    checked in full: every card in it, every field of it, every clip of it. Only
    the complaint that the deck holds words the spec never mentions is dropped,
    because that is expected then.
    """
    problems = []
    if fields_have != spec["fields"]:
        problems.append(f'note type fields are {fields_have}, spec wants {spec["fields"]}')
    # This note type has one card template, so its name is the only entry Anki
    # returns; the spec names the two sides rather than the template.
    only_template = next(iter(templates.values())) if templates else {}
    for name, template in spec["templates"].items():
        if only_template.get(name) != template:
            problems.append(f'{name} template is not the spec\'s')

    by_word: dict[str, list[dict]] = {}
    for note in notes:
        by_word.setdefault(note["fields"]["Portuguese"]["value"], []).append(note)
    for card in spec["cards"]:
        wanted = fields_of(card)
        group = by_word.get(card["portuguese"], [])
        if not group:
            problems.append(f'{card["portuguese"]}: missing from the deck')
            continue
        if len(group) > 1:
            problems.append(f'{card["portuguese"]}: {len(group)} notes claim this word')
        for name, value in wanted.items():
            if group[0]["fields"][name]["value"] != value:
                problems.append(f'{card["portuguese"]} {name}: holds '
                                f'{group[0]["fields"][name]["value"]!r}, expected {value!r}')
        for name, value in wanted.items():
            for clip in FIELD.findall(value):
                if clip not in media:
                    problems.append(f'{card["portuguese"]} {name}: Anki has no {clip}')
                elif clip not in disk:
                    problems.append(f'{card["portuguese"]} {name}: {clip} is not on disk')
                elif media[clip] != disk[clip]:
                    problems.append(f'{card["portuguese"]} {name}: Anki serves different '
                                    f'bytes than the file on disk ({clip})')
    known = {card["portuguese"] for card in spec["cards"]}
    for word in by_word:
        if word not in known and not subset:
            problems.append(f"{word}: in the deck but not in the spec")
    return problems


def read_media(cards: list[dict]) -> dict[str, str]:
    names = sorted({clip for card in cards for value in fields_of(card).values()
                    for clip in FIELD.findall(value)})
    digests = {}
    for name in names:
        payload = anki("retrieveMediaFile", filename=name)
        if payload:
            digests[name] = hashlib.sha1(base64.b64decode(payload)).hexdigest()
    return digests


def read_disk(cards: list[dict]) -> dict[str, str]:
    """The clips the spec names, hashed as they are on disk."""
    return {clip: hashlib.sha1((AUDIO / clip).read_bytes()).hexdigest()
            for card in cards for value in fields_of(card).values()
            for clip in FIELD.findall(value) if (AUDIO / clip).is_file()}


def self_test() -> int:
    """Show that compare() fails on each way this deck could be wrong."""
    spec = {"fields": ["English", "EnglishAudio", "SentenceAudio", "Portuguese",
                       "PortugueseAudio", "LettersAudio", "AnimalsAudio", "SentenceText",
                       "Chapter", "EnglishSentence"],
            "templates": {"Front": "{{English}}", "Back": "{{English}}"},
            "cards": [{"portuguese": "ogre", "english": "ogre", "sentence": "An OGRE.",
                       "media": {"english": "w2_ogre_en.mp3", "sentence": "w2_ogre_sent.mp3",
                                 "portuguese": "w2_ogre_pt.mp3",
                                 "letters": "w2_ogre_letters.mp3",
                                 "animals": "w2_ogre_animals.mp3"}}]}
    good_note = {"noteId": 1, "fields": {name: {"value": value}
                                         for name, value in fields_of(spec["cards"][0]).items()}}
    # The front plays the merged clip, so the files this deck expects include it.
    files = {f"w2_ogre_{k}.mp3": hashlib.sha1(b"x").hexdigest()
             for k in ("en", "sent", "pt", "letters", "animals", "merged")}

    def run(**overrides):
        notes = overrides.get("notes", [json.loads(json.dumps(good_note))])
        return compare(spec, notes, overrides.get("media", files), files,
                       overrides.get("fields", spec["fields"]),
                       {"Card 1": overrides.get("templates", spec["templates"])})

    def broken(field: str, value: str) -> list[dict]:
        notes = [json.loads(json.dumps(good_note))]
        notes[0]["fields"][field]["value"] = value
        return notes

    cases = {
        "correct deck": run(),
        "wrong text": run(notes=broken("English", "giant")),
        "wrong English sentence": run(notes=broken("EnglishSentence", "An OGRE ate the town.")),
        "sentence shown nowhere": run(notes=broken("EnglishSentence", "")),
        "wrong clip": run(notes=broken("PortugueseAudio", "[sound:w2_ogre_en.mp3]")),
        "no clip": run(notes=broken("LettersAudio", "")),
        "missing note": run(notes=[]),
        "extra note": run(notes=[json.loads(json.dumps(good_note))]
                          + [dict(json.loads(json.dumps(good_note)),
                                  fields={**good_note["fields"], "Portuguese": {"value": "troll"}})]),
        "changed bytes": run(media={**files,
                                     "w2_ogre_pt.mp3": hashlib.sha1(b"y").hexdigest()}),
        "wrong fields": run(fields=spec["fields"][:-1]),
        "wrong template": run(templates={"Front": "{{Portuguese}}", "Back": "{{English}}"}),
    }
    failures = 0
    for name, problems in cases.items():
        expected_ok = name == "correct deck"
        ok = (not problems) == expected_ok
        failures += 0 if ok else 1
        print(f'  {"PASS" if ok else "FAIL"}  {name}: {len(problems)} problem(s)')
    print(f'self-test {"PASSED" if not failures else "FAILED"}')
    return failures


def merged_spec() -> dict:
    """The whole deck's expected state: twelve chapters in order, then the pilot words.

    The deck is built by uploading one chapter at a time, and a word that appears in more
    than one chapter keeps the last chapter's fields - so the expectation is the union with
    the later chapter winning, not the first. The pilot specs predate the book sentence and
    only own the words no chapter mentions; they fill gaps rather than overwriting, because
    they have no `book_sentence` and would blank the text side of a chapter's note.
    """
    work = ROOT / "cidadela" / "work"
    expected: dict[str, dict] = {}
    spec: dict = {}
    # Chapters in numeric order, then the 10-word pilot deck for the words no chapter owns
    # (`andar`). The glob must not be read after the chapters: sorted by name it runs ch1,
    # ch10, ch11, ch12, ch2, ..., and re-applies every chapter, which once made ch7 beat
    # ch11 and produced 184 differences that were the check's own fault.
    for path in [*(work / f"words2-spec-ch{n}.json" for n in range(1, 13)),
                 work / "words2-spec-pilot.json"]:
        if not path.exists():
            raise SystemExit(f"missing spec {path}")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        spec = spec or loaded
        chapter = "-ch" in path.name
        for card in loaded["cards"]:
            if chapter or card["portuguese"] not in expected:
                expected[card["portuguese"]] = card
    out = dict(spec)
    out["cards"] = [expected[word] for word in sorted(expected)]
    print(f"expectation: {len(out['cards'])} word(s) from 12 chapters in order, "
          f"pilot words filling gaps")
    # words2-spec.json is the superseded aggregate from before the book sentence existed. It
    # names words that are not notes in this deck, and they are not in the other Portuguese
    # decks either. Reported here rather than treated as authority, and rather than dropped
    # in silence: whether those words belong in words2 is a decision, not a check.
    stale = json.loads((work / "words2-spec.json").read_text(encoding="utf-8"))["cards"]
    absent = sorted(c["portuguese"] for c in stale if c["portuguese"] not in expected)
    if absent:
        print(f"note: the older aggregate words2-spec.json names {len(absent)} word(s) this "
              f"deck does not hold: {absent}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", default=str(ROOT / "cidadela" / "work" / "words2-spec.json"))
    parser.add_argument("--all", action="store_true",
                        help="check the whole deck: all twelve chapters plus the pilot words")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--subset", action="store_true",
                        help="the spec covers part of the deck; other words are expected")
    args = parser.parse_args()
    if args.self_test:
        sys.exit(1 if self_test() else 0)

    spec = merged_spec() if args.all else json.loads(Path(args.spec).read_text(encoding="utf-8"))
    notes = anki("notesInfo", notes=anki("findNotes", query=f'deck:"{spec["deck"]}"'))
    problem_list = compare(spec, notes, read_media(spec["cards"]), read_disk(spec["cards"]),
                           anki("modelFieldNames", modelName=spec["model"]),
                           anki("modelTemplates", modelName=spec["model"]), args.subset)
    clips = sum(len(FIELD.findall(value)) for card in spec["cards"]
                for value in fields_of(card).values())
    print(f'deck "{spec["deck"]}": {len(notes)} note(s) in Anki, {len(spec["cards"])} in the '
          f'spec, {clips} clip(s) named by the spec')
    for problem in problem_list:
        print(f"  PROBLEM {problem}")
    print(f'{"PASS" if not problem_list else "FAIL"}: {len(problem_list)} problem(s)')
    sys.exit(1 if problem_list else 0)


if __name__ == "__main__":
    main()
