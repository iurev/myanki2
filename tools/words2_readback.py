"""Listen to the Portuguese word clips and report the ones a blind ear doubts.

This is the recorder's own listen-back, run over one chapter at a time and reported
instead of enforced. A doubtful word is not a failure of the deck: it is the shortlist
to re-record by hand later, which is what the user asked to be told rather than have
hidden. The verdict goes into the repository, because the previous copy lived in /tmp
and /tmp does not survive.

Only the Portuguese word clips are heard. The English clips and the sentences were
verified as they were made, and re-hearing them here would only cost money.

Usage: python3 tools/words2_readback.py 6 7 8   (default: every chapter that has a spec)
"""
import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from words2_audio import OUT, build_clips, transcribe, verdict_of  # noqa: E402
from cidadela_glossary_gap import plain  # noqa: E402

WORK = pathlib.Path(__file__).resolve().parent.parent / "cidadela" / "work"
REPORT = WORK / "words2-readback.json"
WORKERS = 2


def hear_one(clip: dict) -> dict:
    """What a blind ear makes of one Portuguese word clip.

    A call that fails is reported as a clip that could not be heard, not as a clip that
    says the wrong word. Those are different findings, and blaming the voice for a
    timeout would send someone looking for a pronunciation fault that is not there.
    """
    path = OUT / clip["audio"]
    if not path.is_file():
        return {**clip, "ok": False, "missing_file": True}
    try:
        heard = transcribe(path, "pt")
    except Exception as error:
        return {**clip, "wanted": clip["speech"], "heard": "", "ok": False,
                "not_heard": f"{type(error).__name__}: {error}"}
    row = verdict_of(clip, heard)
    # The recorder's ear compares the letters of the word with the letters of the
    # transcript, so it calls a clip doubtful when the transcript simply wrote the
    # accents the word has: "coracao" against "Coração". That is the right word, so it
    # counts as heard, and the row says which way it passed.
    if not row["ok"] and plain(heard.lower()) == plain(clip["speech"].lower()):
        row["ok"] = True
        row["ok_by_spelling"] = True
    return row


def save(rows: list[dict]) -> None:
    """Write the report as it stands, so a run that dies keeps what it heard."""
    unsure = [row for row in rows if not row.get("ok")]
    REPORT.write_text(json.dumps({
        "checked": len(rows),
        "doubtful": [row for row in unsure if not row.get("not_heard") and not row.get("missing_file")],
        "unheard": [row for row in unsure if row.get("not_heard") or row.get("missing_file")],
        "clips": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def readback(chapters: list[int]) -> int:
    rows = []
    # One card can be named by several chapters (a word that recurs), and its audio is
    # one file, so each file is heard once and attributed to the first chapter to name it.
    heard_files: set[str] = set()
    for chapter in chapters:
        spec_path = WORK / f"words2-spec-ch{chapter}.json"
        if not spec_path.is_file():
            print(f"ch{chapter}: no spec, skipping")
            continue
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        clips = [clip for clip in build_clips(spec)
                 if clip["language"] == "pt" and clip["kind"] == "word"
                 and clip["audio"] not in heard_files]
        heard_files |= {clip["audio"] for clip in clips}
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            heard = list(pool.map(hear_one, clips))
        for clip, row in zip(clips, heard):
            row["chapter"] = chapter
            rows.append(row)
            if not row.get("ok"):
                print(f'?? ch{chapter} {row["key"]:28s} wanted {row.get("wanted") or row.get("speech")!r} '
                      f'heard {row.get("heard")!r} | second ear: {row.get("second_opinion")!r}'
                      f'{row.get("not_heard") or ""}',
                      flush=True)
        passed = sum(1 for row in rows if row.get("chapter") == chapter and row.get("ok"))
        print(f"ch{chapter}: {passed}/{len(clips)} Portuguese word clips came back as the word",
              flush=True)
        save(rows)

    unsure = [row for row in rows if not row.get("ok")]
    doubtful = [row for row in unsure if not row.get("not_heard") and not row.get("missing_file")]
    unheard = [row for row in unsure if row.get("not_heard") or row.get("missing_file")]
    print(f"\n{len(rows) - len(unsure)}/{len(rows)} clips came back as the word, "
          f"{len(doubtful)} doubtful, {len(unheard)} could not be heard")
    print("doubtful words: " + ", ".join(
        f'{row.get("wanted") or row.get("speech")} (ch{row["chapter"]})' for row in doubtful))
    if unheard:
        print("not heard (a call failed, not a voice fault): " + ", ".join(
            f'{row.get("wanted") or row.get("speech")} ({row.get("not_heard") or "file missing"})'
            for row in unheard))
    print(f"wrote {REPORT.relative_to(WORK.parent.parent)}")
    return 0


if __name__ == "__main__":
    numbers = [int(n) for n in sys.argv[1:]] or list(range(1, 13))
    raise SystemExit(readback(numbers))
