#!/usr/bin/env python3
"""Assemble the complete 30-chapter Tesouro listening package locally.

Portuguese chapters 1-10 are copied from the already generated clips and must
still match their frozen hashes: those cards are live in Anki and are not to be
regenerated. Chapters 11-30 come from the fresh cuts. English audio is the
generated Algieba set. Nothing here touches Anki.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / "tesouro" / "full-book-local"
INVENTORY = LOCAL / "text-inventory.json"
FROZEN = LOCAL / "ch01-10-anki-live-sha256.json"
SUSPENDED = ROOT / "tesouro" / "suspended-fixed-all"
REMAINING = ROOT / "tesouro" / "remaining-book-prepared"
ENGLISH = LOCAL / "audio-en"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def portuguese_source(record: dict) -> Path:
    """The clip this card plays.

    Chapters 1-10 are not regenerated: the file Anki already serves is the one
    that ships. Chapters 11-30 come from the fresh cuts.
    """
    if record["chapter"] > 10:
        return LOCAL / f"ch{record['chapter']:02d}" / f"{record['id']}.mp3"
    for candidate in (SUSPENDED / f"{record['id']}.mp3",
                      ROOT / "tesouro" / "audio" / f"ch{record['chapter']:02d}" / f"{record['id']}.mp3"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"{record['id']}: no chapters 1-10 clip found")


def english_back(record: dict) -> str:
    return (f"[sound:tesouro_en_{record['id']}.mp3]<br>"
            f"<b>{record['portuguese_text']}</b><br>{record['english_text']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "tesouro" / "full-book-prepared")
    args = parser.parse_args()
    records = json.loads(INVENTORY.read_text())
    frozen = json.loads(FROZEN.read_text())
    out = args.out
    audio_pt, audio_en = out / "audio-pt", out / "audio-en"
    for directory in (audio_pt, audio_en):
        directory.mkdir(parents=True, exist_ok=True)

    manifest, failures = [], []
    for record in records:
        sid = record["id"]
        pt_source = portuguese_source(record)
        en_source = ENGLISH / f"{sid}.mp3"
        if not en_source.is_file():
            failures.append(f"{sid}: missing English audio")
            continue
        pt_target, en_target = audio_pt / f"{sid}.mp3", audio_en / f"{sid}.mp3"
        shutil.copyfile(pt_source, pt_target)
        shutil.copyfile(en_source, en_target)
        pt_hash, en_hash = sha256(pt_target), sha256(en_target)
        # Chapters 1-10 are live in Anki; a changed byte means the frozen take
        # was regenerated and the live cards no longer match this package.
        if sid in frozen and frozen[sid] != pt_hash:
            failures.append(f"{sid}: Portuguese audio no longer matches the byte Anki serves")
        manifest.append({
            "id": sid, "chapter": record["chapter"], "source": "existing" if record["chapter"] <= 10 else "new",
            "portuguese_text": record["portuguese_text"], "english_text": record["english_text"],
            "portuguese_audio": f"audio-pt/{sid}.mp3", "portuguese_sha256": pt_hash,
            "english_audio": f"audio-en/{sid}.mp3", "english_sha256": en_hash,
            "back": english_back(record),
        })

    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (out / "records.json").write_text(json.dumps([
        {"id": row["id"], "chapter": row["chapter"],
         "front": {"portuguese_audio": row["portuguese_audio"]},
         "back": {"portuguese_text": row["portuguese_text"], "english_text": row["english_text"],
                  "english_audio": row["english_audio"]}}
        for row in manifest], ensure_ascii=False, indent=2) + "\n")
    sums = [f"{row['portuguese_sha256']}  {row['portuguese_audio']}" for row in manifest]
    sums += [f"{row['english_sha256']}  {row['english_audio']}" for row in manifest]
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n")

    new = sum(1 for row in manifest if row["source"] == "new")
    print(json.dumps({"records": len(manifest), "existing_chapters_1_10": len(manifest) - new,
                      "new_chapters_11_30": new, "failures": failures}, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
