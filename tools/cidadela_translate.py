#!/usr/bin/env python3
"""Translate the few sentences the book's own interlinear edition left out.

A Cidadela Misteriosa prints its English translation beside the Portuguese, so
almost nothing needs translating: of the first five chapters only four lines have
no English anywhere. Those four are translated here, chapter by chapter as the
book is, by ``deepseek/deepseek-v4.1-flash`` at high reasoning effort, and every
translation is then put to ``typesafe/jev-router`` for a second opinion.

The prompt asks for what the book does — a close, plain rendering that keeps the
printed quotation marks — rather than a polished one.

    python3 tools/cidadela_translate.py --dry-run
    python3 tools/cidadela_translate.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "cidadela" / "work"
NEEDED = WORK / "english-needed.json"
OUT = WORK / "english-fills.json"

TRANSLATOR = "deepseek/deepseek-v4.1-flash"
CHECKER = "typesafe/jev-router"

STYLE = """You are helping build a Portuguese reading deck from the book \
"A Cidadela Misteriosa", an A2-level Portuguese reader. The book prints its own \
English translation beside nearly every Portuguese sentence; these few sentences \
are the ones it left without one. Translate them the way that book translates: a \
close, plain, literal rendering that stays with the Portuguese wording, not a \
polished or literary one. Keep the printed quotation marks exactly as they are \
('...' where the Portuguese uses them, “...” where it uses those). A short line \
printed in capitals is a sign or a label, so translate it as the sign reads in \
English, in capitals. This book renders "pensão" as "guesthouse" ("He sleeps in \
guesthouses."), so use that same word rather than a cognate.

Answer with a JSON object {"translations": ["...", "..."]} holding exactly one \
English string per numbered item, in the same order. Each numbered item is ONE \
translation even when it holds several sentences: join them into that one string, \
in the same order, and do not split an item into two entries."""


def call(model: str, messages: list[dict], reasoning: bool = False, attempts: int = 4) -> dict:
    body: dict = {"model": model, "messages": messages, "temperature": 0}
    if reasoning:
        body["reasoning"] = {"effort": "high"}
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                 "Content-Type": "application/json"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read()[:400].decode(errors="replace")
            if attempt == attempts - 1:
                raise SystemExit(f"{model}: HTTP {error.code}: {detail}")
            time.sleep(2 ** attempt)
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)
    raise SystemExit(f"{model}: unreachable")


def content(reply: dict) -> str:
    return reply["choices"][0]["message"].get("content") or ""


def json_block(text: str):
    """Pull the first JSON value out of a reply that may wrap it in prose/fences."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = min((text.index(ch) for ch in "[{" if ch in text), default=-1)
    if start < 0:
        raise ValueError(f"no JSON in reply: {text[:200]!r}")
    for end in range(len(text), start, -1):
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            continue
    raise ValueError(f"unparsable JSON in reply: {text[:200]!r}")


def translate(chapter: int, sentences: list[str]) -> list[dict]:
    listing = "\n".join(f"{index + 1}. {sentence}" for index, sentence in enumerate(sentences))
    reply = call(TRANSLATOR, [
        {"role": "system", "content": STYLE},
        {"role": "user", "content": f"Chapter {chapter}. Translate these {len(sentences)} sentences:\n\n{listing}"},
    ], reasoning=True)
    payload = json_block(content(reply))
    rows = payload["translations"] if isinstance(payload, dict) else payload
    if len(rows) != len(sentences):
        raise SystemExit(f"chapter {chapter}: got {len(rows)} translations for {len(sentences)} sentences")
    out = []
    for sentence, row in zip(sentences, rows):
        english = row.get("en", "") if isinstance(row, dict) else row
        if not str(english).strip():
            raise SystemExit(f"chapter {chapter}: empty translation for {sentence!r}")
        out.append({"chapter": chapter, "portuguese_text": sentence, "english_text": str(english).strip(),
                    "translator": TRANSLATOR, "reasoning": "high"})
    return out


def check(row: dict) -> dict:
    """A second model's verdict: does this English say what the Portuguese says?"""
    prompt = (
        "A Portuguese reader prints its own English translation beside the Portuguese text. "
        "One sentence had no translation, so this one was made by another model. "
        "Judge it as a reader of that book would: is it a faithful, close translation of the "
        "Portuguese, keeping the same meaning, tense and quotation marks, with nothing added, "
        "dropped or invented? Reply with JSON: "
        '{"faithful": true|false, "meaningful": true|false, "reason": "one short sentence"}. '
        "Set meaningful to false if the English is not a usable English sentence at all.\n\n"
        f"Portuguese: {row['portuguese_text']}\n"
        f"English: {row['english_text']}"
    )
    reply = call(CHECKER, [{"role": "user", "content": prompt}])
    verdict = json_block(content(reply))
    if not isinstance(verdict, dict) or "faithful" not in verdict:
        raise SystemExit(f"checker gave an unusable verdict: {verdict!r}")
    return {"checker": CHECKER, "faithful": bool(verdict.get("faithful")),
            "meaningful": bool(verdict.get("meaningful")), "reason": str(verdict.get("reason", ""))[:300]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    needed = json.loads(NEEDED.read_text())
    if not needed:
        raise SystemExit("nothing needs translating")
    by_chapter: dict[int, list[str]] = {}
    for row in needed:
        by_chapter.setdefault(row["chapter"], []).append(row["portuguese_text"])

    if args.dry_run:
        print(json.dumps({"needed": len(needed), "chapters": {k: v for k, v in by_chapter.items()}},
                         ensure_ascii=False, indent=2))
        print(f"translator={TRANSLATOR} reasoning=high  checker={CHECKER}")
        return

    fills = []
    for chapter in sorted(by_chapter):
        rows = translate(chapter, by_chapter[chapter])
        for row in rows:
            row["verification"] = check(row)
        fills.extend(rows)
        print(json.dumps({"chapter": chapter, "translated": len(rows),
                          "faithful": sum(1 for r in rows if r["verification"]["faithful"])},
                         ensure_ascii=False))
    if OUT.is_file():
        # This file is rebuilt from the sentences that still need a translation,
        # so a re-run would otherwise drop every fill it did not translate again
        # (it dropped four on 2026-10-07). Carry them over instead.
        fresh = {row["portuguese_text"] for row in fills}
        fills = [row for row in json.loads(OUT.read_text()) if row["portuguese_text"] not in fresh] + fills
    OUT.write_text(json.dumps(fills, ensure_ascii=False, indent=2) + "\n")
    bad = [r for r in fills if not (r["verification"]["faithful"] and r["verification"]["meaningful"])]
    print(json.dumps({"written": str(OUT.relative_to(ROOT)), "rows": len(fills), "rejected": bad},
                     ensure_ascii=False, indent=2))
    if bad:
        raise SystemExit("a translation was rejected by the checker; fix it before building the deck")


if __name__ == "__main__":
    main()
