#!/usr/bin/env python3
"""One-way sync: YAML card configs -> Anki (via AnkiConnect).

Normal cards keep using the existing `id`, `word`, `front`, `back` format.
TA listening cards may additionally use:
  * `ta_id`: stable TA card number
  * `audio`: one local media path or a list of paths

For TA cards, detailed backs are loaded from ta/details/*.yaml. Their stable Anki
ids are `ta0001` ... `ta0200`, so they can never collide with the numeric ids in
the original vocabulary/level0 deck.
"""
import base64
import glob
import json
import os
import sys
import urllib.request

import yaml

ANKI_URL = "http://localhost:8765"


def anki(action, **params):
    payload = json.dumps({"action": action, "version": 6, "params": params}).encode()
    req = urllib.request.Request(
        ANKI_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    if resp.get("error"):
        raise RuntimeError(f"{action}: {resp['error']}")
    return resp["result"]


def assign_ids(cards):
    """Fill blank ids. TA cards use a stable namespaced id; others stay numeric."""
    used = {str(c["id"]).zfill(4) for c in cards if c.get("id") not in (None, "")}
    nums = [int(i) for i in used if i.isdigit()]
    nxt = (max(nums) if nums else 0) + 1
    changed = False

    for c in cards:
        if c.get("id") in (None, ""):
            if c.get("ta_id") not in (None, ""):
                new = f"ta{int(c['ta_id']):04d}"
            else:
                while f"{nxt:04d}" in used:
                    nxt += 1
                new = f"{nxt:04d}"
                nxt += 1
            c["id"] = new
            used.add(new)
            changed = True
        else:
            value = str(c["id"])
            c["id"] = value.zfill(4) if value.isdigit() else value
    return changed


def br(s):
    """Normalize both real newlines and old literal \\n markers to HTML breaks."""
    return str(s).replace("\\n", "<br>").replace("\n", "<br>")


def find_note(deck, card_id):
    ids = anki("findNotes", query=f'deck:"{deck}" "id:{card_id}"')
    return ids[0] if ids else None


def read_md(yaml_path, word):
    """Return companion <yaml-stem>/<word>.md content, or None if absent."""
    if not word:
        return None
    stem = os.path.splitext(os.path.basename(yaml_path))[0]
    md = os.path.join(os.path.dirname(os.path.abspath(yaml_path)), stem, f"{word}.md")
    if os.path.isfile(md):
        return open(md, encoding="utf-8").read().strip()
    return None


def load_ta_details(yaml_path):
    """Load the hand-written TA translations/explanations keyed by ta_id."""
    if os.path.basename(yaml_path) != "ta.yaml":
        return {}

    root = os.path.dirname(os.path.abspath(yaml_path))
    details = {}
    for detail_path in sorted(glob.glob(os.path.join(root, "ta", "details", "*.yaml"))):
        with open(detail_path, encoding="utf-8") as f:
            part = yaml.safe_load(f) or {}
        if not isinstance(part, dict):
            raise ValueError(f"TA details file is not a mapping: {detail_path}")
        for key, value in part.items():
            details[int(key)] = str(value)
    return details


def audio_markup(yaml_path, audio):
    """Store local audio files in Anki media and return [sound:...] markup."""
    if not audio:
        return ""

    paths = audio if isinstance(audio, list) else [audio]
    root = os.path.dirname(os.path.abspath(yaml_path))
    markup = []

    for rel in paths:
        rel = str(rel)
        local_path = rel if os.path.isabs(rel) else os.path.join(root, rel)
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"Audio file not found: {local_path}")

        # Anki media is flat; keep the source path in the name to avoid collisions.
        media_name = rel.replace("\\", "_").replace("/", "_")
        with open(local_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        stored_name = anki("storeMediaFile", filename=media_name, data=data)
        markup.append(f"[sound:{stored_name}]")

    return "<br>".join(markup)


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
    if only_id is not None:
        only_id = str(only_id)
        if only_id.isdigit():
            only_id = only_id.zfill(4)
    return path, only_id


def sync_file(path, only_id):
    """Upsert cards from one YAML file. Returns (added, updated)."""
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict) or "cards" not in cfg:
        return 0, 0

    deck, model, cards = cfg["deck"], cfg["model"], cfg["cards"]

    # Do this before single-id filtering so blank TA ids become targetable stable ids.
    if assign_ids(cards):
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=1000)
        print(f"assigned new ids, rewrote {path}")

    if only_id and only_id not in {str(c.get("id", "")) for c in cards}:
        return 0, 0

    ta_details = load_ta_details(path)
    if ta_details:
        missing = [int(c["ta_id"]) for c in cards if c.get("ta_id") and int(c["ta_id"]) not in ta_details]
        if missing:
            raise ValueError(f"Missing TA explanations for ta_id: {missing}")

    if deck not in anki("deckNames"):
        anki("createDeck", deck=deck)
        print(f"created deck '{deck}'")

    added = updated = 0
    for c in cards:
        if only_id and c["id"] != only_id:
            continue

        ta_id = c.get("ta_id")
        word = c.get("word")
        if not word:
            word = f"ta-{int(ta_id):03d}" if ta_id not in (None, "") else c["id"]

        back = c.get("back")
        if back in (None, "") and ta_id not in (None, ""):
            back = ta_details.get(int(ta_id), "")
        if back in (None, ""):
            raise ValueError(f"Card {c['id']} has no back/explanation")

        extra = read_md(path, word)
        if extra:
            back = f"{back}<br><br><hr><br><br>{extra}"

        front = br(c["front"])
        if c.get("audio"):
            media = audio_markup(path, c["audio"])
            if media:
                front = f"{front}<br><br>{media}"

        fields = {
            "id": c["id"],
            "word": word,
            "front": front,
            "back": br(back),
        }

        tags = [str(tag) for tag in c.get("tags", [])]
        if ta_id not in (None, ""):
            for tag in ("ta", "listening"):
                if tag not in tags:
                    tags.append(tag)

        note_id = find_note(deck, c["id"])
        if note_id:
            anki("updateNoteFields", note={"id": note_id, "fields": fields})
            if tags:
                anki("addTags", notes=[note_id], tags=" ".join(tags))
            updated += 1
            print(f"  ~ {c['id']} {word}")
        else:
            note_id = anki(
                "addNote",
                note={
                    "deckName": deck,
                    "modelName": model,
                    "fields": fields,
                    "tags": tags,
                    "options": {"allowDuplicate": False},
                },
            )
            note_cards = anki("findCards", query=f"nid:{note_id}")
            if note_cards:
                anki("changeDeck", cards=note_cards, deck=deck)
            added += 1
            print(f"  + {c['id']} {word}")

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
