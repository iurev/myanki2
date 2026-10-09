"""Give a gloss to the few chapter words the earlier runs never covered.

The whole book's vocabulary was glossed once, but the chapter scan is re-run for each
batch of chapters and it does find words the earlier list missed. This asks for those
words only and appends them, because re-running the gloss tool rebuilds the file from
its reply cache, which is keyed by batch position - with a changed word list that reads
the wrong batches and drops cards the deck already depends on.

Usage: python3 tools/words2_gloss_fill.py 6 7 8
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import words2_words as gloss_tool  # noqa: E402
from cidadela_glossary_gap import plain  # noqa: E402
from words2_plan import cards_of_chapters  # noqa: E402

GLOSSES = pathlib.Path(__file__).resolve().parent.parent / "cidadela" / "work" / "words2-glosses.json"


def fill(chapters: list[int]) -> list[dict]:
    """Add the missing words of these chapters, and return the cards that were added."""
    data = json.loads(GLOSSES.read_text(encoding="utf-8"))
    cards = data["cards"]
    known = set()
    for card in cards:
        known.add(plain(card["pt"]))
        known.add(plain(card["pt"].replace("-se", "")))
    wanted = cards_of_chapters(chapters)
    missing = [word for word in wanted if plain(word) not in known]
    print(f"chapters {chapters}: {len(wanted)} words, {len(missing)} without a gloss")
    if not missing:
        return []

    sentences = json.loads(gloss_tool.INVENTORY.read_text(encoding="utf-8"))
    reply = gloss_tool.ask(missing, sentences, True)
    if not reply["content"]:
        raise SystemExit(f'model returned no content (finish_reason={reply["finish_reason"]})')
    fresh = [gloss_tool.judged(row) for row in gloss_tool.parse(reply["content"])]
    wanted_plain = {plain(word) for word in missing}
    fresh = [card for card in fresh if plain(card["pt"]) in wanted_plain]

    cards.extend(fresh)
    data["cards"] = cards
    data["missing"] = [word for word in missing
                       if plain(word) not in {plain(card["pt"]) for card in cards}]
    GLOSSES.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"added {len(fresh)} card(s); the file now holds {len(cards)}")
    for card in fresh:
        flag = " PROBLEM " + ", ".join(card["problems"]) if card["problems"] else ""
        print(f'  {card["pt"]:16s} -> {card["en"]:18s} | {card["sentence"]}{flag}')
    print("still without a gloss:", data["missing"])
    return fresh


if __name__ == "__main__":
    numbers = [int(n) for n in sys.argv[1:]] or [6]
    fill(numbers)
