#!/usr/bin/env python3
"""One-way sync: config.yaml -> Anki (via AnkiConnect).

For every card in config.yaml we upsert a note in the target deck, keyed by the
`id` field:
  * if a note with that id already exists -> update its fields
  * otherwise -> add a new note

Cards left without an `id` get the next free 4-digit id auto-assigned, and the
yaml file is rewritten so the assignment is persisted (ids stay stable).

Sync is one-directional: Anki is never read back into the yaml. The yaml is the
single source of truth; edits made directly in Anki are overwritten on next run.

Usage:
    python3 sync.py [path/to/config.yaml]
"""
import json
import sys
import urllib.request

import yaml

ANKI_URL = "http://localhost:8765"


def anki(action, **params):
    payload = json.dumps({"action": action, "version": 6, "params": params}).encode()
    req = urllib.request.Request(ANKI_URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
    if resp.get("error"):
        raise RuntimeError(f"{action}: {resp['error']}")
    return resp["result"]


def assign_ids(cards):
    """Fill blank ids with the next free 4-digit value. Returns True if changed."""
    used = {str(c["id"]).zfill(4) for c in cards if c.get("id") not in (None, "")}
    nums = [int(i) for i in used if i.isdigit()]
    nxt = (max(nums) if nums else 0) + 1
    changed = False
    for c in cards:
        if c.get("id") in (None, ""):
            new = f"{nxt:04d}"
            c["id"] = new
            used.add(new)
            nxt += 1
            changed = True
        else:
            c["id"] = str(c["id"]).zfill(4)
    return changed


def find_note(deck, card_id):
    ids = anki("findNotes", query=f'deck:"{deck}" "id:{card_id}"')
    return ids[0] if ids else None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    deck, model, cards = cfg["deck"], cfg["model"], cfg["cards"]

    if assign_ids(cards):
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=1000)
        print(f"assigned new ids, rewrote {path}")

    if deck not in anki("deckNames"):
        anki("createDeck", deck=deck)
        print(f"created deck '{deck}'")

    added = updated = 0
    for c in cards:
        fields = {"id": c["id"], "word": c["word"],
                  "front": c["front"], "back": c["back"]}
        note_id = find_note(deck, c["id"])
        if note_id:
            anki("updateNoteFields", note={"id": note_id, "fields": fields})
            updated += 1
            print(f"  ~ {c['id']} {c['word']}")
        else:
            anki("addNote", note={"deckName": deck, "modelName": model,
                                  "fields": fields,
                                  "options": {"allowDuplicate": False}})
            added += 1
            print(f"  + {c['id']} {c['word']}")

    print(f"done: {added} added, {updated} updated, {len(cards)} total")


if __name__ == "__main__":
    main()
