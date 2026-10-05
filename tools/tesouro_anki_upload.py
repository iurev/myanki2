#!/usr/bin/env python3
"""Update the listening deck: English audio on every card, plus chapters 11-30.

Existing cards keep the Portuguese audio they already play. Their `back` field
is rewritten to carry the English audio and both texts, in the order the deck
uses: English audio, Portuguese text, English text. Chapters 11-30 are added as
new notes of the same model, deck and tags. Nothing else is touched: no
scheduling, no deck options, no note model changes.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / "tesouro" / "full-book-local"
INVENTORY = LOCAL / "text-inventory.json"
ENGLISH = LOCAL / "audio-en"
MODEL = "listening"
DECK = "listening"


def invoke(action: str, **params):
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request("http://127.0.0.1:56666", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = json.loads(response.read())
    if payload.get("error"):
        raise RuntimeError(f"{action}: {payload['error']}")
    return payload["result"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def portuguese_source(record: dict) -> Path:
    """The clip this card must play.

    Chapters 1-10 are already live in Anki and are not regenerated: the file
    that Anki serves is the one that ships. Chapters 11-30 use the fresh cuts.
    """
    if record["chapter"] > 10:
        return LOCAL / f"ch{record['chapter']:02d}" / f"{record['id']}.mp3"
    for candidate in (ROOT / "tesouro" / "suspended-fixed-all" / f"{record['id']}.mp3",
                      ROOT / "tesouro" / "audio" / f"ch{record['chapter']:02d}" / f"{record['id']}.mp3"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"{record['id']}: no chapters 1-10 clip")


def portuguese_media_name(record: dict) -> str:
    return f"tesouro_audio_ch{record['chapter']:02d}_{record['id']}.mp3"


def english_media_name(record: dict) -> str:
    return f"tesouro_en_{record['id']}.mp3"


def back_field(record: dict) -> str:
    return (f"[sound:{english_media_name(record)}]<br>"
            f"<b>{record['portuguese_text']}</b><br>{record['english_text']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write to Anki; otherwise only report the plan")
    args = parser.parse_args()

    records = json.loads(INVENTORY.read_text())
    existing = [n for n in invoke("notesInfo", notes=invoke("findNotes", query="tesouro"))
                if n["modelName"] == MODEL]
    existing_ids = {n["fields"]["id"]["value"] for n in existing}
    plan = {"update": [], "add": [], "problems": []}
    backup = []

    for record in records:
        sid = record["id"]
        pt_source = portuguese_source(record)
        en_source = ENGLISH / f"{sid}.mp3"
        if not en_source.is_file():
            plan["problems"].append(f"{sid}: missing English audio")
            continue
        entry = {"id": sid, "chapter": record["chapter"], "pt_source": str(pt_source),
                 "pt_sha256": sha256(pt_source.read_bytes()), "en_sha256": sha256(en_source.read_bytes()),
                 "back": back_field(record)}
        if sid in existing_ids:
            plan["update"].append(entry)
        else:
            plan["add"].append(entry)

    if plan["problems"]:
        print(json.dumps(plan["problems"], ensure_ascii=False, indent=2))
        raise SystemExit(1)

    summary = {"existing_notes": len(existing), "records": len(records),
               "update": len(plan["update"]), "add": len(plan["add"]),
               "add_chapters": sorted({e["chapter"] for e in plan["add"]})}
    print(json.dumps(summary, ensure_ascii=False))
    if not args.apply:
        return

    (LOCAL / "anki-note-backup.json").write_text(json.dumps(
        [{"noteId": n["noteId"], "id": n["fields"]["id"]["value"], "front": n["fields"]["front"]["value"],
          "back": n["fields"]["back"]["value"], "tags": n["tags"]} for n in existing],
        ensure_ascii=False, indent=2) + "\n")

    # Media first: a note must never point at a file that is not there yet.
    stored = {"pt": 0, "en": 0}
    for entry in plan["add"]:
        record = next(r for r in records if r["id"] == entry["id"])
        name = portuguese_media_name(record)
        payload = base64.b64encode(Path(entry["pt_source"]).read_bytes()).decode()
        invoke("storeMediaFile", filename=name, data=payload)
        stored["pt"] += 1
    for entry in plan["update"] + plan["add"]:
        record = next(r for r in records if r["id"] == entry["id"])
        name = english_media_name(record)
        payload = base64.b64encode((ENGLISH / f"{entry['id']}.mp3").read_bytes()).decode()
        invoke("storeMediaFile", filename=name, data=payload)
        stored["en"] += 1
    print(json.dumps({"stored_media": stored}))

    by_id = {n["fields"]["id"]["value"]: n for n in existing}
    updated = 0
    for entry in plan["update"]:
        invoke("updateNoteFields", note={"id": by_id[entry["id"]]["noteId"], "fields": {"back": entry["back"]}})
        updated += 1
    print(json.dumps({"updated": updated}))

    notes = []
    for entry in plan["add"]:
        record = next(r for r in records if r["id"] == entry["id"])
        notes.append({
            "deckName": DECK, "modelName": MODEL,
            "fields": {"id": record["id"], "word": record["id"],
                       "front": f"<br><br>[sound:{portuguese_media_name(record)}]",
                       "back": entry["back"], "chapter": ""},
            "tags": [f"chapter{record['chapter']:02d}", "listening", "tesouro"],
            "options": {"allowDuplicate": False},
        })
    added = invoke("addNotes", notes=notes)
    failed = [note["fields"]["id"] for note, note_id in zip(notes, added) if note_id is None]
    print(json.dumps({"added": sum(1 for note_id in added if note_id), "failed": failed}, ensure_ascii=False))


if __name__ == "__main__":
    main()
