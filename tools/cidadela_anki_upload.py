#!/usr/bin/env python3
"""Build the `listening2` deck from the A Cidadela Misteriosa clips.

Each note carries two independent files: the Portuguese sentence cut from the
book's own recording, and the English sentence spoken by Gemini TTS. The card
shows the chapter on both sides, because the deck is meant to be worked through
in book order and the chapter is what tells you where you are.

The note model is the existing `listening` model, so the cards look and behave
exactly like the first listening deck's, and nothing about the model is changed.
Media names are prefixed `cidadela_` so both decks can live in one Anki media
folder without either one's file shadowing the other's.

    python3 tools/cidadela_anki_upload.py            # report the plan
    python3 tools/cidadela_anki_upload.py --apply    # write to Anki
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "cidadela" / "work"
INVENTORY = WORK / "text-inventory.json"
PT_AUDIO = ROOT / "cidadela" / "audio"
EN_AUDIO = ROOT / "cidadela" / "audio-en"
STATE = ROOT / "cidadela" / "anki-listening2-state.json"
# Lines the book prints but the narration never speaks. Each entry carries the
# evidence, so a line cannot be skipped here without proving it is not read.
NOT_NARRATED_PATH = WORK / "not-narrated.json"
NOT_NARRATED = json.loads(NOT_NARRATED_PATH.read_text()) if NOT_NARRATED_PATH.is_file() else {}
MODEL = "listening"
DECK = "listening2"


def invoke(action: str, **params):
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request("http://127.0.0.1:56666", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = json.loads(response.read())
    if payload.get("error"):
        raise RuntimeError(f"{action}: {payload['error']}")
    return payload["result"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def portuguese_media(record: dict) -> str:
    return f"cidadela_audio_ch{record['chapter']:02d}_{record['id']}.mp3"


def english_media(record: dict) -> str:
    return f"cidadela_en_{record['id']}.mp3"


def chapter_label(record: dict) -> str:
    return f"Chapter {record['chapter']} — {record['chapter_title']}"


def front_field(record: dict) -> str:
    return f"<i>{chapter_label(record)}</i><br><br>[sound:{portuguese_media(record)}]"


def back_field(record: dict) -> str:
    return (f"[sound:{english_media(record)}]<br>"
            f"<b>{record['portuguese_text']}</b><br>{record['english_text']}<br><br>"
            f"<i>{chapter_label(record)}</i>")


def plan_notes(records: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    """The notes to add, plus anything that stops the build."""
    notes, problems, skipped = [], [], []
    for record in records:
        sid = record["id"]
        if sid in NOT_NARRATED:
            # The book prints a line the narration never speaks, so there is no
            # audio to cut for it and no card to make. It is skipped by name,
            # with the evidence for that, rather than failing the build.
            skipped.append(f"{sid}: {NOT_NARRATED[sid]}")
            continue
        pt = PT_AUDIO / f"ch{record['chapter']:02d}" / f"{sid}.mp3"
        en = EN_AUDIO / f"{sid}.mp3"
        for path in (pt, en):
            if not path.is_file() or path.stat().st_size == 0:
                problems.append(f"{sid}: missing or empty {path}")
        notes.append({
            "record": record, "pt": pt, "en": en,
            "fields": {"id": sid, "word": sid, "front": front_field(record),
                       "back": back_field(record), "chapter": chapter_label(record)},
            "tags": [f"chapter{record['chapter']:02d}", "listening2", "cidadela"],
        })
    return notes, problems, skipped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write to Anki; otherwise only report the plan")
    args = parser.parse_args()

    records = sorted(json.loads(INVENTORY.read_text()), key=lambda row: row["id"])
    notes, problems, skipped = plan_notes(records)
    if skipped:
        print(json.dumps({"skipped_not_narrated": skipped}, ensure_ascii=False, indent=2))
    if problems:
        print(json.dumps(problems, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    already = [n for n in invoke("notesInfo", notes=invoke("findNotes", query=f'deck:"{DECK}"'))]
    deck_exists = DECK in invoke("deckNames")
    # Cards, not notes: a note can exist while its card sits in another deck.
    # AnkiConnect resolved the just-created deck to Default the first time this
    # ran, so the deck is enforced below rather than trusted from addNotes.
    in_deck_ids = {n["fields"]["id"]["value"] for n in already}
    everywhere = invoke("notesInfo", notes=invoke("findNotes", query="note:listening"))
    existing_ids = {n["fields"]["id"]["value"] for n in everywhere}
    stray = [n for n in everywhere if n["fields"]["id"]["value"] in {row["id"] for row in records}
             and n["fields"]["id"]["value"] not in in_deck_ids]
    summary = {
        "deck": DECK, "model": MODEL, "notes": len(notes),
        "chapters": sorted({n["record"]["chapter"] for n in notes}),
        "already_in_deck": len(already),
        "deck_exists": deck_exists,
        "add": len(notes) - len([n for n in notes if n["fields"]["id"] in existing_ids]),
        "skip_existing": len([n for n in notes if n["fields"]["id"] in existing_ids]),
        "stray_cards_to_move": len(stray),
        "pt_audio_bytes": sum(n["pt"].stat().st_size for n in notes),
        "en_audio_bytes": sum(n["en"].stat().st_size for n in notes),
        "first_front": notes[0]["fields"]["front"],
        "first_back": notes[0]["fields"]["back"],
        "last_front": notes[-1]["fields"]["front"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.apply:
        return

    # The deck has to exist before notes can be filed into it: addNotes reports
    # "deck was not found" rather than creating one.
    if not deck_exists:
        invoke("createDeck", deck=DECK)
        print(json.dumps({"created_deck": DECK}))

    # Media first: a note must never point at a file that is not there yet.
    todo = [note for note in notes if note["fields"]["id"] not in existing_ids]
    stored = {"pt": 0, "en": 0}
    for note in todo:
        invoke("storeMediaFile", filename=portuguese_media(note["record"]),
               data=base64.b64encode(note["pt"].read_bytes()).decode())
        stored["pt"] += 1
        invoke("storeMediaFile", filename=english_media(note["record"]),
               data=base64.b64encode(note["en"].read_bytes()).decode())
        stored["en"] += 1
    print(json.dumps({"stored_media": stored}))

    payload = [{"deckName": DECK, "modelName": MODEL, "fields": note["fields"], "tags": note["tags"],
                "options": {"allowDuplicate": False}} for note in todo]
    added = invoke("addNotes", notes=payload) if payload else []
    failed = [note["fields"]["id"] for note, note_id in zip(todo, added) if note_id is None]
    print(json.dumps({"added": sum(1 for note_id in added if note_id), "failed": failed}, ensure_ascii=False))
    if failed:
        raise SystemExit(1)

    # Move any card that is not home in this deck, whether it was just added or
    # was left behind by an earlier run.
    moved = 0
    new_notes = invoke("notesInfo", notes=[note_id for note_id in added if note_id]) if added else []
    for note in new_notes + stray:
        info = invoke("cardsInfo", cards=note["cards"])
        elsewhere = [card["cardId"] for card in info if card["deckName"] != DECK]
        if elsewhere:
            invoke("changeDeck", cards=elsewhere, deck=DECK)
            moved += len(elsewhere)
    print(json.dumps({"moved_cards": moved}))

    state_notes = invoke("notesInfo", notes=invoke("findNotes", query=f'deck:"{DECK}"'))
    state_ids = {n["fields"]["id"]["value"] for n in state_notes}
    missing = [note["fields"]["id"] for note in notes if note["fields"]["id"] not in state_ids]
    if missing:
        raise SystemExit(f"{len(missing)} notes are still not in {DECK}: {missing[:5]}")

    STATE.write_text(json.dumps([{
        "noteId": next(n["noteId"] for n in state_notes if n["fields"]["id"]["value"] == note["fields"]["id"]),
        "id": note["fields"]["id"], "chapter": note["record"]["chapter"],
        "chapter_label": chapter_label(note["record"]),
        "fields": note["fields"], "tags": note["tags"],
        "pt_media": portuguese_media(note["record"]), "pt_sha256": sha256(note["pt"]),
        "en_media": english_media(note["record"]), "en_sha256": sha256(note["en"]),
    } for note in notes], ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"state": str(STATE), "notes_in_deck": len(state_notes)}))


if __name__ == "__main__":
    main()
