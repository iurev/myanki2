#!/usr/bin/env python3
"""English side of the words2 deck: one gloss and one example sentence per word.

Takes the Portuguese words found by `cidadela_chapter_vocab.py` and asks a model
for the pair of things a cards front needs: the English word that means it, and a
short simple English sentence that uses that English word.

Each request carries the book's own sentence for the word when the word occurs in
the ventences the listening deck was built from, so the example stays in the
story's world instead of being invented from nothing. The book's sentence is a
hint, not a source: the sentence written back must use the *English* word, which
the book's sentence does not always do.

The reply is checked in code, not trusted: a sentence that does not contain the
word it is meant to teach is flagged, as is a gloss that is empty, a bare
definition, or more than a few words.

    python3 tools/words2_words.py --dry-run
    python3 tools/words2_words.py --sample 6     # six words, printed, to look at
    python3 tools/words2_words.py                # all of them
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path

from cidadela_glossary_gap import plain

ROOT = Path(__file__).resolve().parents[1]
WORDS = ROOT / "cidadela" / "work" / "chapter-vocab.json"
INVENTORY = ROOT / "cidadela" / "work" / "text-inventory.json"
OUT_JSON = ROOT / "cidadela" / "work" / "words2-glosses.json"
OUT_MD = ROOT / "cidadela" / "words2-glosses.md"
CACHE = ROOT / "cidadela" / "work" / "words2-gloss-raw"
MODEL = "deepseek/deepseek-v4.1-flash"
BATCH = 25
# Replies are cached per prompt version. Raising this when the instructions
# change is what stops an old, weaker reply from being reused as if it were the
# new one.
PROMPT_VERSION = "v3"

INSTRUCTIONS = """You write English study cards for a Portuguese learner of English.

For each Portuguese word you are given, give:
- "en": the everyday English word (or two-word phrase at most) that means it. The
  natural word a person would say, never a definition or an explanation, and
  never with "to" in front of a verb: "ride", not "to ride". Give the word's own
  usual meaning, even where the book's sentence uses it in a narrower way.
- "sentence": one short, simple English sentence (level A2, at most 12 words) that
  uses that exact English word, with the word written in CAPITAL LETTERS in the
  sentence.

The sentence must show what the word MEANS. Someone who does not know the word
should be able to work out its meaning from the sentence alone, so the sentence
has to carry a real context: a named person, place or object, or a concrete
situation. Put the word in a different word and the sentence should fall apart.

  GOOD: "Magellan set off on an ADVENTURE."     - shows what an adventure is
  GOOD: "The WITCH turned the prince into a frog." - shows what a witch does
  BAD:  "I see an adventurer."                  - true of any word, teaches nothing
  BAD:  "This SWORD is for you."                - no sign of what a sword is
  BAD:  "I am not an ADVENTURER."               - says nothing about adventurers

If a sentence from the book is given with the word, use its meaning, but write
English that stands on its own: if the book's sentence only makes sense to
someone who has read the book, replace it with a fact or a plain situation that
shows the meaning without the story.

Reply with JSON only, no prose and no code fences:
{"cards":[{"pt":"...","en":"...","sentence":"..."}]}
Return one entry for every word given, in the same order."""


def book_sentence(word: str, sentences: list[dict]) -> dict | None:
    """The book's own sentence for a word, if the listening deck has one."""
    key = plain(word)
    shape = key[:-1] if len(key) > 3 and key.endswith(("s", "a")) else key
    for row in sentences:
        text = plain(row["portuguese_text"])
        if re.search(rf"\b{re.escape(key)}\b", text):
            return row
        if len(shape) >= 5 and shape in text:
            return row
    return None


def ask(rows: list[str], sentences: list[dict], first: bool) -> dict:
    lines = []
    for word in rows:
        row = book_sentence(word, sentences)
        hint = f'  book sentence: "{row["portuguese_text"]}" = "{row["english_text"]}"' if row else ""
        lines.append(f"- {word}{hint}")
    body = {"model": MODEL, "response_format": {"type": "json_object"}, "max_tokens": 8000,
            # This task is copying words and writing one-line sentences. Left to
            # think freely the model spent its whole output allowance on reasoning
            # and emitted nothing at all.
            "reasoning": {"enabled": False},
            "messages": [{"role": "system", "content": INSTRUCTIONS},
                         {"role": "user", "content": "\n".join(lines)}]}
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                 "Content-Type": "application/json"})
    reply = json.load(urllib.request.urlopen(request, timeout=900))
    choice = reply["choices"][0]
    return {"words": rows, "content": choice["message"].get("content"),
            "finish_reason": choice.get("finish_reason"), "usage": reply.get("usage", {})}


def parse(content: str | None) -> list[dict]:
    if not content:
        return []
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [row for row in data.get("cards", []) if isinstance(row, dict) and row.get("pt")]


# A sentence that would read just as well with another word swapped in teaches
# nothing about this one: "I see a ...", "This is a ...", "He is a ...". Short
# and framed is the give-away; a long sentence that opens the same way usually has
# real context in it ("The airport is ten kilometres away, so it is quite FAR"),
# so length is what separates the two.
PLUG_IN = re.compile(
    r"^(this is|that is|it is|it's|i see|i have|i've got|i am|i'm|he is|she is|they are|"
    r"we have|you have|here is|there is|there are|the \w+ is|do you have|i like|i want|i need)\b",
    re.I)
PLUG_IN_WORDS = 7


def judged(row: dict) -> dict:
    """The card, with the checks the model's own output has to pass."""
    english = str(row.get("en") or "").strip()
    # The model sometimes answers "to ride"; the card shows the word itself.
    english = re.sub(r"^to\s+", "", english)
    sentence = str(row.get("sentence") or "").strip()
    problems = []
    if not english:
        problems.append("no English word")
    if len(english.split()) > 2:
        problems.append("English word is a phrase")
    if not sentence:
        problems.append("no sentence")
    elif english and plain(english) not in plain(sentence):
        problems.append("sentence does not use the English word")
    elif sentence.count(english.upper()) == 0 and plain(english) not in plain(sentence):
        problems.append("word is not capitalised in the sentence")
    elif PLUG_IN.match(sentence) and len(sentence.split()) <= PLUG_IN_WORDS:
        problems.append("sentence is a plug-in frame that would fit any word")
    return {"pt": str(row["pt"]).strip(), "en": english, "sentence": sentence,
            "problems": problems}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sample", type=int, default=0, help="only this many words, printed")
    parser.add_argument("--report", action="store_true", help="rebuild from cached replies")
    args = parser.parse_args()

    words = [card["word"] for card in json.loads(WORDS.read_text(encoding="utf-8"))["candidates"]]
    sentences = json.loads(INVENTORY.read_text(encoding="utf-8"))
    grounded = sum(1 for word in words if book_sentence(word, sentences))
    if args.dry_run:
        print(f"{len(words)} words, {grounded} of them have the book's own sentence to lean on")
        print(f"{(len(words) + BATCH - 1) // BATCH} request(s) of up to {BATCH} words")
        return

    if args.sample:
        words = words[: args.sample]
        CACHE.mkdir(parents=True, exist_ok=True)
        reply = ask(words, sentences, True)
        (CACHE / "sample.json").write_text(json.dumps(reply, ensure_ascii=False, indent=2) + "\n")
        if not reply["content"]:
            raise SystemExit(f'model returned no content (finish_reason={reply["finish_reason"]}, '
                             f'{reply["usage"].get("completion_tokens")} output tokens)')
        for row in parse(reply["content"]):
            card = judged(row)
            flag = "PROBLEM " + ", ".join(card["problems"]) + " — " if card["problems"] else ""
            print(f'{flag}{card["pt"]:16s} -> {card["en"]:16s} | {card["sentence"]}')
        print(f'\nusage: {reply["usage"].get("prompt_tokens")} in, {reply["usage"].get("completion_tokens")} out')
        return

    CACHE.mkdir(parents=True, exist_ok=True)
    cards: list[dict] = []
    for index in range(0, len(words), BATCH):
        cache = CACHE / f"batch{index // BATCH:02d}.{PROMPT_VERSION}.json"
        cached = json.loads(cache.read_text()) if cache.is_file() else {}
        if not cached.get("content"):
            if args.report and cache.is_file():
                print(f"batch {index // BATCH}: cached reply has no content "
                      f'(finish_reason={cached.get("finish_reason")})')
                continue
            reply = ask(words[index:index + BATCH], sentences, index == 0)
            if not reply["content"]:
                raise SystemExit(f'batch {index // BATCH}: model returned no content '
                                 f'(finish_reason={reply["finish_reason"]}, '
                                 f'{reply["usage"].get("completion_tokens")} output tokens)')
            cache.write_text(json.dumps(reply, ensure_ascii=False, indent=2) + "\n")
            print(f"batch {index // BATCH}: {len(reply['words'])} words asked, "
                  f'{reply["usage"].get("completion_tokens")} tokens out')
        for row in parse(json.loads(cache.read_text())["content"]):
            cards.append(judged(row))

    missing = [word for word in words if word not in {card["pt"] for card in cards}]
    flagged = [card for card in cards if card["problems"]]
    report = {"model": MODEL, "words": len(words), "cards": cards,
              "missing": missing, "flagged": len(flagged),
              "grounded_in_book": grounded}
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = [f"# words2 — the English side of {len(cards)} cards", "",
             f"Written by `{MODEL}`, one request per {BATCH} words, each request given the book's "
             f"own sentence for the word where one exists ({grounded} of {len(words)} words have "
             "one).", ""]
    for card in sorted(cards, key=lambda c: c["pt"]):
        flag = " ⚠️ " + ", ".join(card["problems"]) if card["problems"] else ""
        lines.append(f'- **{card["pt"]}** — {card["en"]} — *{card["sentence"]}*{flag}')
    if missing:
        lines += ["", "## Words the model did not answer for", ""] + [f"- {w}" for w in missing]
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(f"cards {len(cards)}/{len(words)}, flagged {len(flagged)}, missing {len(missing)}")
    print(f"wrote {OUT_MD.relative_to(ROOT)} and {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
