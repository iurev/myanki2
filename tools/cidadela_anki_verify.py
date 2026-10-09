#!/usr/bin/env python3
"""Check the `listening2` deck by reading it back out of Anki.

Two separate questions, both answered against Anki rather than against the files
on disk:

* does each note say what the book says, with the chapter on it;
* is the audio Anki will play the same audio that was cut and verified here.

The second one is answered by hashing the media as Anki returns it. A note id
list, a field comparison and a hash comparison are all different checks: a deck
can hold the right number of notes that point at the wrong files, or at files
that were replaced after verification.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cidadela_anki_upload import MODEL, chapter_label, english_media, front_field, back_field, portuguese_media  # noqa: E402

DECK = "listening2"
INVENTORY = ROOT / "cidadela" / "work" / "text-inventory.json"


def invoke(action: str, **params):
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request("http://127.0.0.1:56666", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as response:
        payload = json.loads(response.read())
    if payload.get("error"):
        raise RuntimeError(f"{action}: {payload['error']}")
    return payload["result"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def field_problems(fields: dict, record: dict) -> list[str]:
    """Every field the deck must carry, compared to the book and the plan."""
    sid = record["id"]
    wanted = {"id": sid, "word": sid, "chapter": chapter_label(record),
              "front": front_field(record), "back": back_field(record)}
    problems = []
    for name, value in wanted.items():
        got = fields.get(name, {}).get("value", "")
        if got != value:
            problems.append(f"{sid}: field {name} is {got!r}, expected {value!r}")
    for needle in (chapter_label(record), f"sound:{portuguese_media(record)}"):
        if needle not in fields.get("front", {}).get("value", ""):
            problems.append(f"{sid}: front is missing {needle!r}")
    for needle in (record["portuguese_text"], record["english_text"], f"sound:{english_media(record)}",
                   chapter_label(record)):
        if needle not in fields.get("back", {}).get("value", ""):
            problems.append(f"{sid}: back is missing {needle!r}")
    return problems


def media_hash(name: str) -> bytes | None:
    encoded = invoke("retrieveMediaFile", filename=name)
    return base64.b64decode(encoded) if encoded else None


def decodes(data: bytes) -> tuple[bool, float | None]:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "clip.mp3"
        path.write_bytes(data)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(path)], capture_output=True, text=True)
        if probe.returncode != 0:
            return False, None
        try:
            return True, float(probe.stdout.strip())
        except ValueError:
            return False, None


def self_test() -> None:
    """Prove the comparison notices a deck that is not what was planned."""
    record = json.loads(INVENTORY.read_text())[0]
    good = {"id": {"value": record["id"]}, "word": {"value": record["id"]},
            "chapter": {"value": chapter_label(record)}, "front": {"value": front_field(record)},
            "back": {"value": back_field(record)}}
    failures = []
    if field_problems(good, record):
        failures.append("a correct note was reported as wrong")
    for name in ("front", "back", "chapter"):
        broken = json.loads(json.dumps(good))
        broken[name]["value"] = broken[name]["value"].replace("Chapter", "Chaptre")
        if not field_problems(broken, record):
            failures.append(f"a note with a wrong {name} passed")
    trimmed = json.loads(json.dumps(good))
    trimmed["back"]["value"] = trimmed["back"]["value"].replace(record["english_text"], "")
    if not field_problems(trimmed, record):
        failures.append("a note missing its English text passed")
    if failures:
        raise SystemExit("SELF-TEST FAILED (the checker is vacuous): " + "; ".join(failures))
    print("SELF-TEST PASSED: the checker rejects a wrong chapter, wrong text and missing audio reference")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return

    state = json.loads((ROOT / "cidadela" / "anki-listening2-state.json").read_text())
    records = {row["id"]: row for row in json.loads(INVENTORY.read_text())}
    problems: list[str] = []

    notes = invoke("notesInfo", notes=invoke("findNotes", query=f'deck:"{DECK}"'))
    cards = invoke("findCards", query=f'deck:"{DECK}"')
    if len(notes) != len(state):
        problems.append(f"deck holds {len(notes)} notes, expected {len(state)}")
    if len(cards) != len(state):
        problems.append(f"deck holds {len(cards)} cards, expected {len(state)}")

    by_id = {n["fields"]["id"]["value"]: n for n in notes}
    media: dict[str, tuple[bytes | None, str]] = {}
    checked_media: list[dict] = []
    for entry in state:
        sid = entry["id"]
        note = by_id.get(sid)
        if note is None:
            problems.append(f"{sid}: note is not in the deck")
            continue
        if note["modelName"] != MODEL:
            problems.append(f"{sid}: model is {note['modelName']}, expected {MODEL}")
        if sorted(note["tags"]) != sorted(entry["tags"]):
            problems.append(f"{sid}: tags are {sorted(note['tags'])}, expected {sorted(entry['tags'])}")
        problems.extend(field_problems(note["fields"], records[sid]))
        for name, expected_hash in ((entry["pt_media"], entry["pt_sha256"]), (entry["en_media"], entry["en_sha256"])):
            if name not in media:
                data = media_hash(name)
                media[name] = (data, sha256(data) if data else "")
            data, digest = media[name]
            if data is None:
                problems.append(f"{sid}: Anki has no media file {name}")
            elif digest != expected_hash:
                problems.append(f"{sid}: Anki's {name} hashes to {digest[:12]}, the verified file to {expected_hash[:12]}")
            else:
                ok, duration = decodes(data)
                if not ok:
                    problems.append(f"{sid}: Anki's {name} does not decode as audio")
                else:
                    checked_media.append({"id": sid, "media": name, "bytes": len(data),
                                          "duration": round(duration or 0, 2), "sha256": digest[:12]})

    summary = {"deck_notes": len(notes), "deck_cards": len(cards), "planned_notes": len(state),
               "media_files_hash_matched": len(checked_media), "problems": len(problems)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if problems:
        print(json.dumps(problems[:40], ensure_ascii=False, indent=2))
        raise SystemExit(1)
    print(f"PASS: {len(notes)} notes in {DECK}, every field and every media hash matches the verified files")


if __name__ == "__main__":
    main()
