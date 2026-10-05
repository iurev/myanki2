#!/usr/bin/env python3
"""Compare the audio live in Anki with the local candidate clips.

The chapters already in Anki are not to be regenerated, so the package has to
carry exactly the bytes the live cards play. Every candidate directory is
compared against the media Anki actually serves.
"""
import base64
import hashlib
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANKI = "http://127.0.0.1:56666"
CANDIDATES = {
    "original": lambda sid, ch: ROOT / "tesouro" / "audio" / f"ch{ch:02d}" / f"{sid}.mp3",
    "recut": lambda sid, ch: (ROOT / "tesouro" / "suspended-fixed-all" / f"{sid}.mp3",
                              ROOT / "tesouro" / "remaining-book-prepared" / f"{sid}.mp3"),
}


def invoke(action: str, **params):
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    request = urllib.request.Request(ANKI, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read())
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    return payload["result"]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve(sid: str, chapter: int, spec) -> str | None:
    paths = spec(sid, chapter) if callable(spec) else (spec,)
    if isinstance(paths, Path):
        paths = (paths,)
    for path in paths:
        if Path(path).is_file():
            return digest(Path(path).read_bytes())
    return None


def main() -> None:
    note_ids = invoke("findNotes", query="\"tesouro\"")
    info = invoke("notesInfo", notes=note_ids)
    media = {}
    for note in info:
        for field in note["fields"].values():
            for name in re.findall(r"\[sound:([^\]]+)\]", field.get("value", "")):
                media.setdefault(name, note["noteId"])
    print(json.dumps({"notes": len(info), "media": len(media)}))
    rows, unknown = [], []
    for name, note_id in sorted(media.items()):
        match = re.search(r"(ts\d{4})", name)
        chapter = re.search(r"ch(\d+)", name)
        if not match:
            unknown.append(name)
            continue
        sid = match.group(1)
        served = digest(base64.b64decode(invoke("retrieveMediaFile", filename=name)))
        row = {"media": name, "id": sid, "noteId": note_id, "anki": served}
        for label, spec in CANDIDATES.items():
            row[label] = resolve(sid, int(chapter.group(1)) if chapter else 0, spec)
        row["matches"] = [label for label in CANDIDATES if row[label] == served]
        rows.append(row)
    (ROOT / "tesouro" / "full-book-local" / "anki-live-media-hashes.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    summary = {}
    for row in rows:
        summary[tuple(row["matches"])] = summary.get(tuple(row["matches"]), 0) + 1
    print(json.dumps({"checked": len(rows), "match_breakdown": {str(k): v for k, v in summary.items()},
                      "unparsed_media": unknown}, ensure_ascii=False))


if __name__ == "__main__":
    main()
