"""How long until every card in a deck has been passed at least once.

The question sounds like a forecast but it is mostly a count. "Passed at least once" is
not a prediction: every answer is already in the review log, so how many cards have never
been passed is a fact, not an estimate. What is left to work out is how quickly the cards
that are left get introduced, and how much study is stacked up behind them.

The first pass happens in the same sitting as the first answer - a card's learning steps
are minutes long - so "cards never passed" and "cards never seen" are nearly the same
number, and everything turns on new cards per day. Two things decide that, and the report
prints both rather than assuming either:

  * what you actually do, counted from the log - new cards per day, over recent windows,
  * the cap Anki is set to for the deck, read from the deck's options.

A deck built yesterday has no pace of its own (dividing three cards by one day produces a
number that is worse than useless), so the pace comes from the collection and from the
deck that has been running for months. Anki's own per-day cap is only useful if it is a
real cap: 9999 is how Anki spells "no limit", and saying "0 days at 9999 a day" would be
arithmetically true and completely misleading.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from pt_stats import ROLLOVER_HOUR, day_of  # the 4am boundary, one definition
from words2_anki import anki

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "pt-stats" / "raw.json"
DATA = ROOT / "pt-stats" / "data.json"

DECKS = ["words2", "listening2"]
SUSPENDED = -1
PASS = 2  # ease >= 2 is a pass; 1 is Again

RECENT_DAYS = 14   # "what you have been doing lately"
HABIT_DAYS = 30    # "what you normally do", long enough to survive a week off
MIN_ACTIVE_DAYS = 5  # below this a deck has no pace worth dividing by
NO_CAP = 1000      # Anki writes 9999 for "no limit"; anything this high is not a cap

# Paces worth showing even when the measured habit sits elsewhere - round numbers are
# how people actually decide to work.
ROUND_PACES = [10, 20, 40, 80]


def load(path: pathlib.Path = RAW) -> dict:
    if not path.exists():
        raise SystemExit(f"{path} is missing - run: python3 tools/pt_stats.py --pull")
    return json.loads(path.read_text())


def card_state(cards: list[dict], reviews: list[dict]) -> dict:
    """How many cards are left, split by what is actually stopping each one.

    Three different problems hide behind "not finished": never introduced (a matter of
    days), introduced but never passed (worth a look), or suspended (nothing will fix it
    by itself).
    """
    passed = {r["card"] for r in reviews if r["ease"] >= PASS}
    seen = {r["card"] for r in reviews}
    suspended = {c["cardId"] for c in cards if c["queue"] == SUSPENDED}
    all_ids = {c["cardId"] for c in cards}
    left = all_ids - passed
    return {
        "cards": len(all_ids),
        "passed": len(passed & all_ids),
        "seen_not_passed": len((seen - passed) & all_ids),
        "never_seen": len(all_ids - seen),
        "suspended": len(suspended),
        "suspended_never_passed": len(suspended - passed),
        "left": len(left),
        "left_studyable": len(left - suspended),
    }


def introductions_per_day(reviews: list[dict]) -> Counter:
    """Cards met for the first time, by the day they were first answered."""
    first: dict[int, int] = {}
    for row in reviews:
        card = row["card"]
        if card not in first or row["t"] < first[card]:
            first[card] = row["t"]
    return Counter(day_of(t) for t in first.values())


def pace_in(days: Counter, today: str, window: int) -> dict:
    """New cards per day over the last `window` days.

    Divided by the window, not by the number of active days, because days off are part of
    the pace you actually keep. The active-day figure is printed beside it: one answers
    "will I finish", the other answers "how hard do I work when I sit down".
    """
    today_ordinal = datetime.date.fromisoformat(today).toordinal()
    inside = {d: n for d, n in days.items()
              if 0 <= today_ordinal - datetime.date.fromisoformat(d).toordinal() < window}
    total = sum(inside.values())
    active = len(inside)
    return {"per_day": total / window, "per_active_day": total / max(1, active),
            "total": total, "active_days": active, "window": window}


def deck_options(deck: str) -> dict | None:
    """Anki's own new-cards-per-day limit for the deck, if Anki is reachable."""
    try:
        config = anki("getDeckConfig", deck=deck)
    except Exception as error:  # Anki closed, or the call shape changed
        print(f"  (could not read {deck} options: {error})")
        return None
    new, rev = config.get("new", {}), config.get("rev", {})
    per_day = new.get("perDay")
    return {"new_per_day": per_day, "capped": bool(per_day and per_day < NO_CAP),
            "review_per_day": rev.get("perDay"),
            "learning_steps": new.get("delays") or []}


def days_to_finish(left: int, per_day: float) -> float | None:
    if per_day <= 0:
        return None
    return left / per_day


def finish_date(today: str, days: float) -> str:
    return (datetime.date.fromisoformat(today)
            + datetime.timedelta(days=round(days))).isoformat()


def cross_check(cards: list[dict], state: dict) -> list[tuple[str, bool, str]]:
    """Check the passed count against Anki's own card phases.

    "Passed at least once" is derived from the review log, so it is worth confirming by a
    route that never looks at the log: Anki keeps a card's phase on the card itself, and a
    card cannot be in the learning or review phase unless it was answered and passed on
    the way there. A card that is still `new` has, by definition, never been answered.
    Two independent counts that agree are worth more than one count repeated.
    """
    phases = Counter(c["type"] for c in cards)
    studied = phases[1] + phases[2] + phases[3]
    return [
        (f"passed {state['passed']} = cards in learning or review ({studied})",
         state["passed"] == studied,
         f"learning {phases[1]} + review {phases[2]} + relearning {phases[3]}"),
        (f"never answered {state['never_seen']} = cards still new ({phases[0]})",
         state["never_seen"] == phases[0],
         "a new card has no answers by definition"),
    ]


def self_test() -> None:
    """Prove the pieces can say no before trusting them on real data."""
    checks = [
        ("a card answered only with Again has not passed",
         card_state([{"cardId": 1, "queue": 0}], [{"card": 1, "ease": 1, "t": 1}])["passed"] == 0, True),
        ("that card counts as passed once it is answered Good",
         card_state([{"cardId": 1, "queue": 0}],
                    [{"card": 1, "ease": 1, "t": 1}, {"card": 1, "ease": 3, "t": 2}])["passed"] == 1, True),
        ("a card passed twice is still one passed card",
         card_state([{"cardId": 1, "queue": 0}],
                    [{"card": 1, "ease": 3, "t": 1}, {"card": 1, "ease": 4, "t": 2}])["passed"] == 1, True),
        ("a suspended card is not studyable",
         card_state([{"cardId": 1, "queue": -1}], [])["left_studyable"] == 0, True),
        ("a suspended card is still outstanding",
         card_state([{"cardId": 1, "queue": -1}], [])["left"] == 1, True),
        ("introductions count once per card, on its earliest day",
         sum(introductions_per_day([{"card": 1, "t": 86_400_000 * 3},
                                    {"card": 1, "t": 86_400_000 * 4}]).values()) == 1, True),
        ("no pace gives no estimate rather than a number",
         days_to_finish(100, 0) is None, True),
        ("ten a day finishes a hundred cards in ten days",
         days_to_finish(100, 10) == 10, True),
        ("Anki's 9999 is not read as a real cap", deck_cap_is_real(9999) is False, True),
        ("a genuine cap of 20 is read as a real cap", deck_cap_is_real(20) is True, True),
        ("the cross-check catches a log that disagrees with the card phases",
         cross_check([{"cardId": 1, "type": 2}], card_state([{"cardId": 1, "queue": 2}], []))[0][1] is False,
         True),
        ("the day boundary is Anki's 4am, not midnight", ROLLOVER_HOUR == 4, True),
    ]
    problems = [f"{name}: got {got!r}, wanted {want!r}"
                for name, got, want in checks if got != want]
    print(f"self-test: {len(checks) - len(problems)}/{len(checks)} checks passed")
    for problem in problems:
        print(f"  FAIL {problem}")
    if problems:
        raise SystemExit(1)


def deck_cap_is_real(per_day: int | None) -> bool:
    return bool(per_day and per_day < NO_CAP)


def main() -> None:
    if "--self-test" in sys.argv:
        self_test()
        return

    raw = load()
    data = raw["decks"]
    today = raw["generated"][:10]

    summaries = {}
    for deck in DECKS:
        cards, reviews = data[deck]["cards"], data[deck]["reviews"]
        summaries[deck] = card_state(cards, reviews)

    print(f"Cards that have never been passed  (Anki read {today})")
    print("=" * 78)
    print(f"{'deck':11s} {'cards':>6} {'passed':>7} {'never answered':>15} "
          f"{'suspended, never passed':>24}")
    for deck in DECKS:
        s = summaries[deck]
        print(f"{deck:11s} {s['cards']:6d} {s['passed']:7d} {s['never_seen']:15d} "
              f"{s['suspended_never_passed']:24d}")
        if s["seen_not_passed"]:
            print(f"{'':11s} and {s['seen_not_passed']} answered but never passed")
    both = sum(summaries[d]["left_studyable"] for d in DECKS)
    print(f"\nLeft to introduce across both decks: {both} cards "
          f"(out of {sum(summaries[d]['cards'] for d in DECKS)}).")

    print("\nChecked against the cards themselves")
    print("-" * 78)
    for deck in DECKS:
        for name, ok, note in cross_check(data[deck]["cards"], summaries[deck]):
            print(f"  {deck:11s} {'ok  ' if ok else 'DIFF'} {name}  ({note})")
            if not ok:
                raise SystemExit(f"{deck}: the log and the cards disagree - stop and look")

    # ---- what pace you actually keep -------------------------------------------------
    all_reviews = [r for d in data.values() for r in d["reviews"]]
    collection = introductions_per_day(all_reviews)
    words = introductions_per_day(data["words"]["reviews"])
    recent = pace_in(collection, today, RECENT_DAYS)
    habit = pace_in(collection, today, HABIT_DAYS)
    words_total = sum(words.values())
    words_active = {"per_active_day": words_total / max(1, len(words)),
                    "active_days": len(words), "total": words_total}

    print(f"\nThe pace you actually keep")
    print("-" * 78)
    print(f"  all five decks, last {habit['window']} days   {habit['total']:4d} new cards = "
          f"{habit['per_day']:.1f}/day over {habit['active_days']} active days")
    print(f"  all five decks, last {recent['window']} days   {recent['total']:4d} new cards = "
          f"{recent['per_day']:.1f}/day over {recent['active_days']} active days")
    print(f"  the words deck, per active day     {words_active['total']:4d} new cards = "
          f"{words_active['per_active_day']:.1f}/day over {words_active['active_days']} active days")

    # ---- does Anki pace it for you ---------------------------------------------------
    print(f"\nIs Anki pacing these decks?")
    print("-" * 78)
    for deck in DECKS:
        options = deck_options(deck)
        if not options:
            continue
        if options["capped"]:
            print(f"  {deck:11s} capped at {options['new_per_day']} new cards a day"
                  f" -> {days_to_finish(summaries[deck]['left_studyable'], options['new_per_day']):.0f} days")
        else:
            print(f"  {deck:11s} set to {options['new_per_day']} new cards a day, which is how "
                  f"Anki spells 'no limit'")
    print("  With no cap, nothing stops a whole deck arriving in one sitting - and that is")
    print("  what happened: words2 introduced 106 cards on 7 Oct and 33 the day before.")

    # ---- how long --------------------------------------------------------------------
    paces = [("your last month", habit["per_day"]), ("your last fortnight", recent["per_day"]),
             ("your words-deck habit", words_active["per_active_day"])]
    paces += [(f"{n} new a day", n) for n in ROUND_PACES]
    seen_paces: dict[float, str] = {}
    for name, per_day in paces:
        seen_paces.setdefault(round(per_day, 2), name)

    print(f"\nHow long, at each pace")
    print("-" * 78)
    print(f"  {'':28s} {'words2':>9} {'listening2':>12} {'both':>9}   {'both done around':>17}")
    for per_day, name in sorted(seen_paces.items(), key=lambda item: -item[0]):
        per_deck = []
        for deck in DECKS:
            days = days_to_finish(summaries[deck]["left_studyable"], per_day)
            per_deck.append(days)
        both_days = days_to_finish(both, per_day)
        cells = "".join(f"{f'{d:.1f} d':>{w}}" for d, w in zip(per_deck, (9, 12)))
        print(f"  {name:28s}{cells} {f'{both_days:.1f} d':>9}   {finish_date(today, both_days):>17}")
    print("  (words2 has "
          f"{summaries['words2']['left_studyable']}, listening2 has "
          f"{summaries['listening2']['left_studyable']}; both figures count only cards Anki will actually show.)")

    # ---- what "finished" leaves behind -----------------------------------------------
    built = json.loads(DATA.read_text()) if DATA.exists() else {}
    graduation = built.get("all", {}).get("graduation", {})
    summary = built.get("all", {}).get("summary", {})
    to_graduate = graduation.get("median") or 4
    seconds = summary.get("median_seconds") or 8
    answers = both * to_graduate
    hours = answers * seconds / 3600
    print(f"\nWhat 'passed once' does not mean")
    print("-" * 78)
    print(f"  A card is not learned because it was passed once. From your own log, a card")
    print(f"  takes a median {to_graduate} answers over {graduation.get('median_days') or 5} days to become a scheduled")
    print(f"  review, and then keeps coming back. Introducing all {both} cards therefore")
    print(f"  costs about {answers:,} answers, roughly {hours:.1f} hours at your median "
          f"{seconds:.1f}s per answer,")
    print(f"  before any of those cards returns for the first time.")
    per_card = summary_answers_per_card(data)
    if per_card:
        print(f"  And they do return: your words deck, {per_card['cards']} cards, costs "
              f"{per_card['per_card']:.3f} answers")
        print(f"  per card per study day, so a finished {both}-card pair behaves like the words")
        print(f"  deck does now - about {both * per_card['per_card']:.0f} answers on every day you study.")


def summary_answers_per_card(data: dict) -> dict | None:
    """Answers per card per active day, measured on the deck that is furthest along.

    This is the empirically honest way to talk about the load a finished deck carries: it
    is what the one deck that is already mostly mature costs its owner, not a guess about
    intervals.
    """
    words = data.get("words")
    if not words or not words["cards"]:
        return None
    days: Counter = Counter(day_of(r["t"]) for r in words["reviews"])
    if not days:
        return None
    return {"cards": len(words["cards"]),
            "per_card": sum(days.values()) / len(days) / len(words["cards"])}


if __name__ == "__main__":
    main()
