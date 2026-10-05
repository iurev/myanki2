#!/usr/bin/env python3
"""Check the listening deck against the package, after an upload.

Everything is read back from Anki: the notes, their fields, and the actual bytes
of every media file the cards reference. A note that merely reports success is
not evidence that the deck now plays the validated audio.
"""
from __future__ import annotations

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
    if record["chapter"] > 10:
        return LOCAL / f"ch{record['chapter']:02d}" / f"{record['id']}.mp3"
    for candidate in (ROOT / "tesouro" / "suspended-fixed-all" / f"{record['id']}.mp3",
                      ROOT / "tesouro" / "audio" / f"ch{record['chapter']:02d}" / f"{record['id']}.mp3"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(record["id"])


def main() -> None:
    records = {r["id"]: r for r in json.loads(INVENTORY.read_text())}
    notes = [n for n in invoke("notesInfo", notes=invoke("findNotes", query="tesouro"))
             if n["modelName"] == MODEL]
    problems: list[str] = []
    seen: dict[str, int] = {}
    checks = {"notes": 0, "pt_media": 0, "en_media": 0, "pt_bytes": 0, "en_bytes": 0}
    for note in notes:
        sid = note["fields"]["id"]["value"]
        seen[sid] = seen.get(sid, 0) + 1
        record = records.get(sid)
        if record is None:
            problems.append(f"{sid}: note has no package record")
            continue
        checks["notes"] += 1
        front, back = note["fields"]["front"]["value"], note["fields"]["back"]["value"]
        en_name = f"tesouro_en_{sid}.mp3"
        pt_name = f"tesouro_audio_ch{record['chapter']:02d}_{sid}.mp3"
        expected_back = f"[sound:{en_name}]<br><b>{record['portuguese_text']}</b><br>{record['english_text']}"
        if back != expected_back:
            problems.append(f"{sid}: back field differs from the package text")
        if f"[sound:{pt_name}]" not in front:
            problems.append(f"{sid}: front does not play {pt_name}")
        served_pt = base64.b64decode(invoke("retrieveMediaFile", filename=pt_name))
        served_en = base64.b64decode(invoke("retrieveMediaFile", filename=en_name))
        if not served_pt:
            problems.append(f"{sid}: {pt_name} missing from the media collection")
        if not served_en:
            problems.append(f"{sid}: {en_name} missing from the media collection")
        checks["pt_media"] += 1
        checks["en_media"] += 1
        checks["pt_bytes"] += len(served_pt)
        checks["en_bytes"] += len(served_en)
        # Anki may re-encode nothing, so the served bytes must equal the
        # validated local clip exactly.
        if sha256(served_pt) != sha256(portuguese_source(record).read_bytes()):
            problems.append(f"{sid}: {pt_name} served by Anki is not the validated clip")
        if sha256(served_en) != sha256((ENGLISH / f"{sid}.mp3").read_bytes()):
            problems.append(f"{sid}: {en_name} served by Anki is not the generated English clip")
        if len(note["cards"]) != 1:
            problems.append(f"{sid}: {len(note['cards'])} cards")
    for sid, count in seen.items():
        if count > 1:
            problems.append(f"{sid}: {count} duplicate notes")
    missing = sorted(set(records) - set(seen))
    if missing:
        problems.append(f"missing notes: {missing[:10]} (and {len(missing) - 10} more)")

    cards = [card for note in notes for card in note["cards"]]
    decks: dict[str, int] = {}
    for info in invoke("cardsInfo", cards=cards):
        decks[info["deckName"]] = decks.get(info["deckName"], 0) + 1
    print(json.dumps({"checks": checks, "decks": decks, "problems": problems[:20],
                      "problem_count": len(problems)}, ensure_ascii=False, indent=2))
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
