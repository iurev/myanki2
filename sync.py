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

If a card has a companion markdown file at `<yaml-stem>/<word>.md` (e.g.
`verbs/permanecer.md` for verbs.yaml), its contents are appended to the back of
the card (after an <hr>). No extra Anki field is created.

Usage:
    python3 sync.py [path/to/config.yaml | all] [id]
    python3 sync.py verbs.yaml            # sync every card in one file
    python3 sync.py all                   # sync every *.yaml in the script dir
    python3 sync.py verbs.yaml 0128       # sync only the card with id 0128
    python3 sync.py all 0128              # find id 0128 across all files, sync it
    python3 sync.py all --id 0128         # same
"""
import glob
import json
import os
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


def br(s):
    """Anki renders HTML; real newlines collapse to a space. Use <br> instead."""
    return str(s).replace("\n", "<br>")


def find_note(deck, card_id):
    ids = anki("findNotes", query=f'deck:"{deck}" "id:{card_id}"')
    return ids[0] if ids else None


def read_md(yaml_path, word):
    """Return the companion <yaml-stem>/<word>.md content, or None if absent."""
    stem = os.path.splitext(os.path.basename(yaml_path))[0]
    md = os.path.join(os.path.dirname(os.path.abspath(yaml_path)), stem, f"{word}.md")
    if os.path.isfile(md):
        return open(md, encoding="utf-8").read().strip()
    return None


def parse_args(argv):
    """Return (path, only_id). Accepts `path [id]` or `path --id ID`."""
    args = list(argv[1:])
    only_id = None
    if "--id" in args:
        i = args.index("--id")
        only_id = args[i + 1]
        del args[i:i + 2]
    path = args[0] if args else "config.yaml"
    if len(args) > 1:
        only_id = args[1]
    return path, (str(only_id).zfill(4) if only_id is not None else None)


def sync_file(path, only_id):
    """Upsert the cards of one yaml file. Returns (added, updated)."""
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict) or "cards" not in cfg:
        return 0, 0                                  # not a card file, skip

    deck, model, cards = cfg["deck"], cfg["model"], cfg["cards"]

    # when targeting a single id, skip files that don't hold it (no noise/rewrite)
    if only_id and only_id not in {str(c.get("id", "")).zfill(4) for c in cards}:
        return 0, 0

    if assign_ids(cards):
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=1000)
        print(f"assigned new ids, rewrote {path}")

    if deck not in anki("deckNames"):
        anki("createDeck", deck=deck)
        print(f"created deck '{deck}'")

    added = updated = 0
    for c in cards:
        if only_id and c["id"] != only_id:
            continue
        back = c["back"]
        extra = read_md(path, c["word"])
        if extra:
            back = f"{back}\n\n<hr>\n\n{extra}"
        fields = {"id": c["id"], "word": c["word"],
                  "front": br(c["front"]), "back": br(back)}
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
    return added, updated


def main():
    path, only_id = parse_args(sys.argv)
    if path == "all":
        here = os.path.dirname(os.path.abspath(__file__))
        files = sorted(glob.glob(os.path.join(here, "*.yaml")))
    else:
        files = [path]

    added = updated = 0
    for f in files:
        a, u = sync_file(f, only_id)
        added += a
        updated += u

    scope = f"id {only_id}" if only_id else f"{len(files)} file(s)"
    print(f"done: {added} added, {updated} updated ({scope})")


if __name__ == "__main__":
    main()
