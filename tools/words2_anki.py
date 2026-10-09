#!/usr/bin/env python3
"""Put a words2 spec into Anki: one notetype, then one note per card.

The deck needs a note type of its own, because the whole point of this deck is
that each clip lives in its own field: the word and its recording, the example
sentence's recording, the Portuguese word, its recording, the spelling by
letters, and the spelling by animals. Separate fields can be hidden, emptied or
re-recorded one at a time; a single blob of audio could not.

Creating a note type changes the collection's schema, which makes AnkiWeb want a
full sync rather than a fast one. That is the cost of the separate fields, and it
is paid once.

Notes are matched on the Portuguese field, so re-running updates the same notes
instead of adding a second copy, and a note's media is uploaded before the field
mentions it.

    python3 tools/words2_anki.py --spec cidadela/work/words2-spec.json --dry-run
    python3 tools/words2_anki.py --spec cidadela/work/words2-spec-pilot.json
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / "cidadela" / "audio2"
STATE = ROOT / "cidadela" / "work" / "words2-anki-state.json"
ANKI_URL = os.environ.get("ANKI_URL", "http://127.0.0.1:56666")
CSS = """.card {
  font-family: arial;
  font-size: 24px;
  text-align: center;
  color: black;
  background-color: white;
}
hr#answer { border: 0; border-top: 1px solid #ccc; margin: 12px 0; }
"""


def anki(action: str, **params):
    payload = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(ANKI_URL, data=payload,
                                     headers={"Content-Type": "application/json"})
    response = json.loads(urllib.request.urlopen(request, timeout=180).read())
    if response.get("error"):
        raise RuntimeError(f"{action}: {response['error']}")
    return response["result"]


def fields_of(card: dict) -> dict[str, str]:
    """The fields of one note: the clips named from the card's media, and the text.

    The front plays the word and then the example sentence as a single recording,
    so the merged clip goes in `SentenceAudio` and `EnglishAudio` is left empty.
    Both of its halves are still in `cidadela/audio2` and still hashed in
    `work/words2-merge-state.json`; only the card stops pointing at them, because
    a field that names a clip is a field that plays it.

    The book's own sentence and its chapter are plain text on the back, not audio:
    the sentence is there to be read after answering, and the chapter says where in
    the book it came from. The English example sentence is text on the front, under
    the word: the merged clip speaks it, and reading it beside the recording is the
    point of having it, so `EnglishSentence` carries the sentence the clip was made
    from rather than a second wording of it.
    """
    media = card["media"]
    english = media["english"]
    if not english.endswith("_en.mp3"):
        raise SystemExit(f'unexpected media name {english!r} for {card["portuguese"]!r}')
    merged = english[: -len("_en.mp3")] + "_merged.mp3"
    return {
        "English": card["english"],
        "EnglishAudio": "",
        "SentenceAudio": f"[sound:{merged}]",
        "Portuguese": card["portuguese"],
        "PortugueseAudio": f'[sound:{media["portuguese"]}]',
        "LettersAudio": f'[sound:{media["letters"]}]',
        "AnimalsAudio": f'[sound:{media["animals"]}]',
        "SentenceText": card.get("book_sentence", ""),
        "Chapter": str(card.get("book_chapter") or ""),
        "EnglishSentence": card.get("sentence", ""),
    }


def ensure_model(spec: dict) -> None:
    """Create the note type, or add fields and refresh the template it has grown into.

    Adding a field changes the collection's schema, which AnkiWeb will only accept
    with a full sync - so this happens once, deliberately, when the deck grows a
    field, and never silently. Anki appends new fields, so the spec's order has to
    start with what is already there for the two to line up.
    """
    fields = spec["fields"]
    if spec["model"] not in anki("modelNames"):
        anki("createModel", modelName=spec["model"], inOrderFields=fields, css=CSS,
             cardTemplates=[{"Name": "Card 1", "Front": spec["templates"]["Front"],
                             "Back": spec["templates"]["Back"]}])
        print(f'created note type "{spec["model"]}" with {len(fields)} fields')
        return
    have = [name for name in anki("modelFieldNames", modelName=spec["model"])]
    if have != fields:
        if have != fields[: len(have)] or len(have) > len(fields):
            raise SystemExit(f'note type "{spec["model"]}" has fields {have}, spec wants '
                             f"{fields}. Refusing to reshape a note type that is in use.")
        for name in fields[len(have):]:
            anki("modelFieldAdd", modelName=spec["model"], fieldName=name)
            print(f'added field "{name}" to note type "{spec["model"]}" - this needs one '
                  "full sync (Anki asks; choose Upload if this machine is the newest)")
    templates = {name: row for name, row in anki("modelTemplates",
                                                modelName=spec["model"]).items()}
    if (templates["Card 1"]["Front"] != spec["templates"]["Front"]
            or templates["Card 1"]["Back"] != spec["templates"]["Back"]):
        anki("updateModelTemplates", model={"name": spec["model"], "templates": {
            "Card 1": {"Front": spec["templates"]["Front"],
                       "Back": spec["templates"]["Back"]}}})
        print(f'rewrote the "Card 1" template of "{spec["model"]}"')


def upload_media(cards: list[dict]) -> int:
    """Put every clip Anki does not hold into its media folder, newest take last.

    The clips come from the fields the note is about to have, not from the spec's
    media names: a field is what plays, so a clip a field names and Anki lacks is
    silence on the card, and a clip no field names no longer has to travel. The
    merged clip is why this matters - the spec's media predates it, and uploading
    from the spec left every updated card pointing at a file Anki did not have.
    """
    have = set(anki("getMediaFilesNames", pattern="w2_*"))
    uploaded = 0
    for card in cards:
        named = sorted({name for value in fields_of(card).values()
                        for name in re.findall(r"\[sound:([^\]]+)\]", value)})
        for name in named:
            path = AUDIO / name
            if not path.is_file():
                raise SystemExit(f"missing media file {path}")
            digest = hashlib.sha1(path.read_bytes()).hexdigest()
            if name in have:
                served = anki("retrieveMediaFile", filename=name)
                if served and hashlib.sha1(base64.b64decode(served)).hexdigest() == digest:
                    continue
                print(f"replacing {name}: Anki holds an older take")
            anki("storeMediaFile", filename=name, path=str(path))
            uploaded += 1
    return uploaded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", default=str(ROOT / "cidadela" / "work" / "words2-spec.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    cards = spec["cards"]
    if args.dry_run:
        print(f'{len(cards)} card(s) -> deck "{spec["deck"]}", note type "{spec["model"]}"')
        for card in cards[:3]:
            for name, value in fields_of(card).items():
                print(f'   {name:16s} {value}')
            print()
        return

    ensure_model(spec)
    anki("createDeck", deck=spec["deck"])
    uploaded = upload_media(cards)
    if uploaded:
        print(f"uploaded {uploaded} media file(s)")

    deck_id = anki("deckNamesAndIds")[spec["deck"]]
    # Existing notes are found by tag, not by deck: a note whose card landed in
    # Default is invisible to a deck query, and matching by deck would then add a
    # second copy of every card. (`model:` is not a search field in Anki either.)
    existing = anki("notesInfo", notes=anki("findNotes", query="tag:words2"))
    by_word = {note["fields"]["Portuguese"]["value"]: note for note in existing}
    added, updated = 0, 0
    for card in cards:
        fields = fields_of(card)
        note = by_word.get(card["portuguese"])
        if note is None:
            anki("addNotes", notes=[{"deckName": spec["deck"], "modelName": spec["model"],
                                     "fields": fields, "tags": ["words2"],
                                     "options": {"allowDuplicate": True}}])
            added += 1
        elif any(note["fields"][name]["value"] != value for name, value in fields.items()):
            anki("updateNoteFields", note={"id": note["noteId"], "fields": fields})
            updated += 1
    print(f"done: {added} added, {updated} updated")

    # A deck created moments ago is not in AnkiConnect's cache yet, so notes
    # added to it land in Default instead. Move any card that landed elsewhere.
    strays = [card["cardId"] for card in
              anki("cardsInfo", cards=[card for note in anki("findNotes", query="tag:words2")
                                       for card in anki("findCards", query=f"nid:{note}")])
              if card["deckName"] != spec["deck"]]
    if strays:
        anki("changeDeck", cards=strays, deck=spec["deck"])
        print(f"moved {len(strays)} card(s) into {spec['deck']} (they landed in Default)")

    notes = anki("notesInfo", notes=anki("findNotes", query=f'deck:"{spec["deck"]}"'))
    media = set(anki("getMediaFilesNames", pattern="w2_*"))
    # Every clip a note names must be one Anki can serve, or the card plays silence.
    without = []
    for note in notes:
        named = [name for field in note["fields"].values()
                 for name in re.findall(r"\[sound:([^\]]+)\]", field["value"])]
        absent = [name for name in named if name not in media]
        if absent:
            without.append(f'{note["fields"]["Portuguese"]["value"]}: {absent}')
    ids = sorted(note["noteId"] for note in notes)
    STATE.write_text(json.dumps({"deck": spec["deck"], "model": spec["model"],
                                 "notes": ids, "fields": spec["fields"]},
                                ensure_ascii=False, indent=2) + "\n")
    print(f'deck "{spec["deck"]}": {len(notes)} note(s), {len(media)} clip(s) in Anki, '
          f'deck id {deck_id}, {len(without)} without all their clips')


if __name__ == "__main__":
    main()
