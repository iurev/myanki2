#!/usr/bin/env python3
"""Ask DeepSeek which chapter words are missing from the yaml decks.

The book's own glossary turned out not to list everything, so it cannot be the
source of truth for "what do I still not know". This reads the chapters
themselves instead and asks a model, once per chapter, to name the words in that
chapter that the yaml decks do not hold.

What is sent, per request:

* one chapter's Portuguese text, from `extracted2/OEBPS/part-001-chapter-00N.xhtml`
  (the Portuguese-only edition - `part-002-*` is the interlinear one, and
  `extracted/` is a different book entirely);
* every headword held in the yaml files, as one word per line.

What comes back is a list of lemmas, and for each one the sentence it was found in
and the chapter that sentence came from. Only then is every claim checked in code,
because a model asked for "words not in this list" can still name a word that is
in it, or a word that is not in the chapter at all:

* reported as `in yaml` when the word is held after all;
* reported as `variant of held` when it is a feminine or plural form of a held word;
* reported as `not vocabulary` when it is not a word at all;
* otherwise it is a real candidate, listed with the form the chapter used.

The quote is what makes the claim checkable. Its words are looked for in the
chapter text: found means the evidence is real and the word is confirmed even when
the stem search above missed an irregular form; not found means the model was
asked for the closest sentence in the chapter instead, and the distance is printed
so a quote that is nearly right (a dash, a comma) reads differently from one that
was invented.

Raw replies are cached under `cidadela/work/chapter-vocab-raw/`, so a re-run only
pays for chapters that have not been asked about yet.

    python3 tools/cidadela_chapter_vocab.py                     # chapters 1-5
    python3 tools/cidadela_chapter_vocab.py --chapters 1-12
    python3 tools/cidadela_chapter_vocab.py --dry-run           # sizes only
    python3 tools/cidadela_chapter_vocab.py --report            # rebuild from cache
"""
from __future__ import annotations

import argparse
import difflib
import html
import json
import os
import re
import time
import urllib.request
from pathlib import Path

from cidadela_glossary_gap import plain, read_yaml_words, strip_article, terms

ROOT = Path(__file__).resolve().parents[1]
EXTRACTED = ROOT / "extracted2" / "OEBPS"
RAW_DIR = ROOT / "cidadela" / "work" / "chapter-vocab-raw"
OUT_JSON = ROOT / "cidadela" / "work" / "chapter-vocab.json"
OUT_MD = ROOT / "cidadela" / "chapter-vocab.md"
MODEL = "deepseek/deepseek-v4.1-flash"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
# Replies are cached per prompt version: the shape of the answer changed from a
# bare word list to a word with its sentence, so the old replies must not be read
# as if they had sentences in them.
PROMPT_VERSION = "v2"
# A chapter's own recording marker, and nothing else, so far: not a word to learn.
NON_WORDS = {"audio"}

INSTRUCTIONS = """You are helping build Portuguese study cards from a children's book.

You will be given (1) a list of Portuguese words the learner ALREADY HAS, and (2) one
chapter of the book in Portuguese.

Return the words in the chapter that are NOT in the list, as base forms (lemmas):
a verb as its infinitive, a noun/adjective as its masculine singular.

Rules, in order of importance:
- Do NOT return any word that is in the list, including any inflected form of a listed
  word (if "dizer" is listed, do not return "dizem", "disse", "dito").
- Do NOT return masculine/feminine or singular/plural variants of a listed word
  (if "bonito" is listed, do not return "bonita"; if "casa" is listed, not "casas").
- Do NOT return articles, contractions or prepositions: a, o, as, os, um, uma, em,
  no, na, nos, nas, de, do, da, dos, das, por, pelo, para, com, e, ou, que, se.
- Do NOT return proper names of people or places.
- Do NOT return numbers or words that only appear inside a proper name.
- Only words that actually occur in the chapter text given to you.

For every word, also give the sentence you found it in:
- Copy the sentence from the chapter EXACTLY as it is written there: same words, same
  punctuation, nothing shortened, nothing reworded, no words added or removed.
- The sentence must contain the word you are reporting.
- If the word appears in more than one sentence, give the first one.
- Never write a sentence that is not in the chapter, and never build one from parts of
  another. A made-up sentence is worse than no answer.
- "chapter" is the chapter number you were given.

Reply with JSON only, no prose and no code fences, in exactly this shape:
{"words": [{"word": "<lemma>", "printed": "<the form as it appears in the chapter>",
  "sentence": "<that sentence, copied exactly>", "chapter": <chapter number>}]}
"""


def chapter_text(number: int) -> str:
    path = EXTRACTED / f"part-001-chapter-{number:03d}.xhtml"
    body = path.read_text(encoding="utf-8")
    body = body[body.find("<body"):]
    # The title ends in a full stop of its own, or the chapter's first sentence
    # reads as one long sentence starting with the title.
    body = HEADING_END.sub(". ", body)
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    text = re.sub(r"\s+", " ", text).strip()
    # The recording marker each chapter opens with ("áudio 05:04") is not text.
    return re.sub(r"\báudio\s+\d+:\d+", "", text, flags=re.I).strip()


def ask(chapter: int, text: str, held: list[str]) -> dict:
    body = {
        "model": MODEL,
        "reasoning": {"effort": "high"},
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": INSTRUCTIONS},
            {"role": "user", "content": "WORDS THE LEARNER ALREADY HAS:\n"
                                        + "\n".join(held)
                                        + f"\n\nCHAPTER {chapter}:\n" + text},
        ],
    }
    request = urllib.request.Request(
        API_URL, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                 "Content-Type": "application/json"})
    # A request that dies on the way (the connection is reset, the endpoint is busy)
    # costs nothing and should not throw away a whole run of chapters. A reply that
    # arrives with no words in it is retried for the same reason, and after the last
    # attempt it is an error rather than an empty chapter: recording silence as
    # "chapter 4 adds nothing" would be the one result nobody could notice.
    for attempt in range(5):
        try:
            reply = json.load(urllib.request.urlopen(request, timeout=900))
            content = reply["choices"][0]["message"]["content"]
            if content and content.strip():
                break
            reason = f"the reply had no content ({reply.get('usage')})"
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"
        if attempt == 4:
            raise SystemExit(f"chapter {chapter}: {reason}, after 5 attempts")
        time.sleep(5 * (attempt + 1))
    usage = reply.get("usage", {})
    return {"chapter": chapter, "content": content, "usage": usage,
            "cost": reply.get("usage", {}).get("cost")}


def answered(cache: Path) -> bool:
    """Whether a cache file holds a real reply and not just the husk of a failed one.

    A reply that came back with no content is not an answer. Treating it as one makes
    a chapter that could not be read look like a chapter with nothing new in it, which
    is the mistake nobody would catch.
    """
    if not cache.is_file():
        return False
    try:
        reply = json.loads(cache.read_text())
    except json.JSONDecodeError:
        return False
    return bool((reply.get("content") or "").strip())


def parse(content: str) -> list[dict]:
    """The words a reply names, however the model wrapped its JSON."""
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    words = data.get("words") or []
    return [word for word in words if isinstance(word, dict) and word.get("word")]


def stem(word: str) -> str:
    """A verb lemma without its ending, so "conseguir" can find "conseguiu"."""
    plain_word = plain(word)
    for ending in ("ar", "er", "ir", "se"):
        if plain_word.endswith(ending) and len(plain_word) > len(ending) + 2:
            return plain_word[: -len(ending)]
    return plain_word


def shapes(word: str) -> str:
    """A word with its plural marker and feminine ending taken off.

    Used to find a lemma in a chapter that only uses an inflected form: the
    chapter says "pensões" and "silenciosa", and both must count as evidence for
    "pensão" and "silencioso".
    """
    if len(word) > 2 and word.endswith("s"):
        word = word[:-1]
    if len(word) > 2 and word.endswith("a"):
        word = word[:-1] + "o"
    return word


def appears(word: str, chapter_plain: str) -> bool:
    """Whether a lemma is in the chapter text, allowing for its inflections.

    Portuguese hides a lemma behind its endings - the chapter says "pensões" and
    "silenciosa" - so a whole word is matched at a word boundary, and then the
    shorter pieces of it (its plural/feminine shape, a verb stem, or a prefix cut
    by one or two letters) are looked for inside longer words. Pieces have to be
    at least four letters, because shorter ones match half the language.

    This is evidence, not proof: when nothing matches, the word is reported as
    unverified rather than dropped, since an irregular form can hide its lemma
    completely ("voz" against a chapter that says "vozes").
    """
    key = plain(word)
    if re.search(rf"\b{re.escape(key)}\b", chapter_plain):
        return True
    forms = {shapes(key), stem(key)}
    forms |= {key[: len(key) - cut] for cut in (1, 2)}
    return any(len(form) >= 4 and form in chapter_plain for form in forms)


def quotable(text: str) -> str:
    """A sentence reduced to its words, so a quote is compared as a quote.

    Accents and case are folded, and punctuation is dropped: a model that writes a
    dash where the book has a comma has still quoted the book, and calling that
    "not found in the chapter" would report a real sentence as invented.
    """
    return re.sub(r"[^\w\s]", " ", plain(text)).strip()


# A chapter's title is glued to its first sentence otherwise (the title ends without a
# full stop), which makes a real quoted sentence look like a fragment.
HEADING_END = re.compile(r"</h[1-6]>|<br\s*/?>", re.I)
# "Sr. Adalberto" is not two sentences, so a full stop after one of these is not a
# sentence boundary.
ABBREVIATIONS = {"sr", "sra", "srª", "dr", "dra", "sta", "sto", "prof", "cap", "etc"}


def sentences_of(text: str) -> list[str]:
    """The chapter's sentences, kept as printed, for finding the closest one."""
    parts, start = [], 0
    for match in re.finditer(r"[.!?…]+\s+", text):
        before = re.findall(r"[A-Za-zÀ-ÿª]+", text[:match.start()][-12:])
        if before and plain(before[-1]) in ABBREVIATIONS:
            continue
        parts.append(text[start:match.end()].strip())
        start = match.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return [part for part in parts if part]


def quote_evidence(quote: str, chapters: dict[int, str], asked: int) -> dict:
    """Where the quoted sentence is, or how far the nearest real one is.

    The strongest answer is that the quote is a whole sentence of the chapter: word
    for word, ending where the chapter's sentence ends. Weaker but still real is a
    run of the chapter's words that is not one whole sentence - saying "the words
    are in the chapter, somewhere in a row" rather than "this sentence is in the
    chapter". Both are reported as they are, because the difference is exactly what
    tells a quote apart from a sentence that was stitched together or invented.
    Otherwise the closest sentence in the chapter is found and its similarity
    printed.
    """
    wanted = quotable(quote)
    if not wanted:
        return {"status": "absent", "chapter": 0, "similarity": 0.0, "closest": ""}
    for number, text in chapters.items():
        if any(wanted == quotable(sentence) for sentence in sentences_of(text)):
            return {"status": "sentence", "chapter": number, "similarity": 1.0,
                    "closest": quote}
    for number, text in chapters.items():
        if wanted in quotable(text):
            return {"status": "in chapter", "chapter": number, "similarity": 1.0,
                    "closest": quote}
    scored = [(difflib.SequenceMatcher(None, wanted, quotable(sentence)).ratio(), number, sentence)
              for number, text in chapters.items() for sentence in sentences_of(text)]
    similarity, number, sentence = max(scored, default=(0.0, asked, ""))
    # Three quarters of the words in the same order is a quote with something
    # small wrong with it; below that it is a different sentence.
    return {"status": "near" if similarity >= 0.75 else "absent", "chapter": number,
            "similarity": round(similarity, 3), "closest": sentence}


def quote_has(word: str, text: str) -> bool:
    """Is this word in that text, allowing for the hyphen a quote may drop?

    Portuguese puts a pronoun on the verb with a hyphen - "soltam-se" - and
    quotable() turns punctuation into spaces, so the word has to be compared the
    same way: "soltam se" against "...as cordas soltam se e a ponte...". Without
    this, a verb is reported as missing from the very sentence that proves it.
    """
    shape = quotable(word)
    return bool(shape) and re.search(rf"\b{re.escape(shape)}\b", quotable(text)) is not None


def judge(word: dict, number: int, chapters: dict[int, str], held: dict[str, list[str]]) -> dict:
    """Check the model's claim against the yaml words and the chapter text."""
    lemma = str(word["word"]).strip()
    printed = str(word.get("printed") or "").strip()
    sentence = str(word.get("sentence") or "").strip()
    key = strip_article(plain(lemma))
    variant = next((other for other in held
                    if other != key and shapes(other) == shapes(key) and len(key) > 3), None)
    quote = quote_evidence(sentence, chapters, number)
    # The word has to be in the sentence it is claimed to come from, or the quote
    # proves nothing about it. Both forms are tried: the lemma, and the form the
    # chapter actually printed, which is how a pronoun like seu is found in a
    # sentence that says "sua", and how "soltar-se" is found in "soltam-se".
    in_quote = (quote["status"] in ("sentence", "in chapter")
                and (quote_has(key, sentence)
                     or (printed and quote_has(plain(printed), sentence))))
    if key in NON_WORDS:
        verdict = "not vocabulary"
    elif key in held:
        verdict = "in yaml"
    elif variant:
        # The learner's own rule: a feminine or plural form of a word already
        # held is not a new word.
        verdict = "variant of held"
    elif (appears(key, chapters[number]) or in_quote
          or (printed and appears(plain(printed), chapters[number]))):
        verdict = "candidate"
    else:
        verdict = "unverified"
    return {"word": lemma, "printed": printed, "sentence": sentence, "asked_chapter": number,
            "verdict": verdict, "quote": quote, "in_quote": in_quote,
            "yaml_files": held.get(key, []), "held_as": variant or ""}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapters", default="1-5")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", action="store_true",
                        help="use the cached replies only, never ask again")
    args = parser.parse_args()
    wanted = [int(n) for n in re.split(r"[,\-]", args.chapters) if n.strip().isdigit()]
    if "-" in args.chapters:
        low, _, high = args.chapters.partition("-")
        wanted = list(range(int(low), int(high or low) + 1))

    held = read_yaml_words()
    chapter_plain = {n: plain(chapter_text(n)) for n in wanted}

    if args.dry_run:
        list_words = len(held)
        for number in wanted:
            print(f"chapter {number}: {len(chapter_plain[number].split())} words of text, "
                  f"word list {list_words} headwords")
        return

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    spent = 0.0
    for number in wanted:
        cache = RAW_DIR / f"ch{number:02d}.{PROMPT_VERSION}.json"
        if answered(cache) or args.report:
            continue
        reply = ask(number, chapter_text(number), sorted(held))
        cache.write_text(json.dumps(reply, ensure_ascii=False, indent=2) + "\n")
        spent += reply.get("cost") or 0.0
        print(f"chapter {number}: asked {MODEL} "
              f'({reply["usage"].get("prompt_tokens")} prompt tokens, '
              f'{reply["usage"].get("completion_tokens")} out)')

    missing_cache = [n for n in wanted
                     if not answered(RAW_DIR / f"ch{n:02d}.{PROMPT_VERSION}.json")]
    if missing_cache:
        raise SystemExit(f"no cached reply for chapter(s) {missing_cache}")

    results = {}
    for number in wanted:
        reply = json.loads((RAW_DIR / f"ch{number:02d}.{PROMPT_VERSION}.json").read_text())
        words = [judge(word, number, chapter_plain, held) for word in parse(reply["content"])]
        results[number] = words

    seen: dict[str, dict] = {}
    for number, words in results.items():
        for word in words:
            if word["verdict"] not in ("candidate", "unverified"):
                continue
            entry = seen.setdefault(plain(word["word"]), {"word": word["word"], "chapters": [],
                                                          "printed": [], "unverified": True,
                                                          "sentence": "", "in_quote": False,
                                                          "quote": None})
            entry["chapters"].append(number)
            entry["unverified"] = entry["unverified"] and word["verdict"] == "unverified"
            if word["printed"] and word["printed"] not in entry["printed"]:
                entry["printed"].append(word["printed"])
            # A sentence that was really found in the chapter is better evidence
            # than an earlier one that was not, so it replaces it.
            if word["in_quote"] and not entry["in_quote"]:
                entry["sentence"], entry["in_quote"], entry["quote"] = (
                    word["sentence"], True, word["quote"])
            elif not entry["sentence"]:
                entry["sentence"], entry["quote"] = word["sentence"], word["quote"]

    marked = [word for words in results.values() for word in words
              if word["verdict"] not in ("candidate", "unverified")]
    fresh = [word for words in results.values() for word in words
             if word["verdict"] in ("candidate", "unverified")]
    report = {
        "model": MODEL,
        "reasoning": "high",
        "prompt_version": PROMPT_VERSION,
        "chapters": wanted,
        "held_headwords": len(held),
        "candidates": sorted(seen.values(), key=lambda e: (e["chapters"][0], e["word"])),
        "rejected": marked,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    lines = [f"# Words in chapters {wanted[0]}–{wanted[-1]} that the yaml decks do not hold", "",
             f"Found by asking `{MODEL}` (reasoning effort: high) once per chapter, with the "
             f"{len(held)} yaml headwords in the prompt, and the sentence each word was found "
             "in. Every claim is then checked in code: a word already held, a feminine or "
             "plural variant of one, or a non-word is set aside at the bottom instead of being "
             "counted, and every quoted sentence is looked for in the chapter text. A sentence "
             "that is really there is quoted below; one that is not is replaced by the closest "
             "sentence in the chapter, with how close it is. A word marked `?` is one neither "
             "the text search nor a real quote could confirm.", ""]
    for number, words in results.items():
        fresh_here = [word for word in words if word["verdict"] in ("candidate", "unverified")]
        unsure = [word for word in fresh_here if word["verdict"] == "unverified"]
        lines.append(f"### Chapter {number}")
        lines.append(f"{len(fresh_here)} new word(s)"
                     + (f", {len(unsure)} of them not found in the chapter text." if unsure else "."))
        lines.append("")
        for word in fresh_here:
            mark = "? " if word["verdict"] == "unverified" else ""
            printed = f" — as printed: *{', '.join(sorted(set([word['printed']]))) }*" if word["printed"] else ""
            lines.append(f"- {mark}**{word['word']}**{printed}")
            if word["sentence"]:
                quote = word["quote"] or {}
                if quote.get("status") == "sentence":
                    lines.append(f"  - > {word['sentence']}")
                elif quote.get("status") == "in chapter":
                    lines.append(f"  - part of a sentence only: > {word['sentence']}")
                else:
                    lines.append(f"  - QUOTE {quote.get('status', 'absent')} "
                                 f"(closest {quote.get('similarity', 0):.2f}): „{word['sentence']}“")
                    if quote.get("closest"):
                        lines.append(f"  - chapter {number} actually says: „{quote['closest']}“")
            else:
                lines.append("  - the model gave no sentence for this one")
        lines.append("")
    per_chapter = {number: [word for word in results[number]
                            if word["verdict"] in ("candidate", "unverified")] for number in wanted}
    quoted = sum(1 for word in fresh if word["in_quote"])
    whole = sum(1 for word in fresh if (word["quote"] or {}).get("status") == "sentence")
    lines += ["", "## Summary", "",
              f"**{len(seen)}** distinct new words across chapters "
              f"{wanted[0]}–{wanted[-1]}: "
              + ", ".join(f"{len(per_chapter[n])} in chapter {n}" for n in wanted) + ".", "",
              f"Every one of them was returned with a sentence, and **{whole} of {len(fresh)}** "
              f"of those sentences are a whole sentence of the book, word for word "
              f"({quoted} have at least their words in a row in the chapter). The rest are "
              f"listed below with the closest sentence instead.", "",
              "The same list in chapter order, ignoring which chapter each came from. A word "
              "followed by `?` is one the code check could not find in the text.", ""]
    for entry in report["candidates"]:
        where = ", ".join(str(n) for n in sorted(set(entry["chapters"])))
        mark = "? " if entry.get("unverified") else ""
        lines.append(f'- {mark}**{entry["word"]}** — chapter(s) {where}')
        if entry["sentence"]:
            lines.append(f'  - > {entry["sentence"]}')
    if marked:
        lines += ["", "## Set aside", "",
                  "Named by the model, but not counted as a new word for the reason given: "
                  "`in yaml` is held already, `variant of held` is a feminine or plural form of a "
                  "held word, `not vocabulary` is not a word at all.", ""]
        for word in marked:
            held_as = f", held as **{word['held_as']}**" if word.get("held_as") else ""
            files = f" ({', '.join(sorted(set(word['yaml_files'])))}{held_as})" if word["yaml_files"] else held_as
            lines.append(f"- {word['verdict']} — **{word['word']}**{files}")
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(f"candidates: {len(seen)}, rejected claims: {len(marked)}, spent ${spent:.4f}")
    print(f"quotes that are a whole sentence of the book: {whole}/{len(fresh)}")
    for word in fresh:
        if not word["in_quote"] or (word["quote"] or {}).get("status") != "sentence":
            status = (word["quote"] or {}).get("status", "absent")
            similarity = (word["quote"] or {}).get("similarity", 0.0)
            print(f'   quote {status:10s} {similarity:.2f}  {word["word"]}: "{word["sentence"][:90]}"')
    print(f"wrote {OUT_MD.relative_to(ROOT)} and {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
