#!/usr/bin/env python3
"""Pull the Portuguese decks' study history out of Anki, and turn it into numbers.

Two steps, so that the slow part can be re-read without asking Anki again:

    python3 tools/pt_stats.py --pull     -> pt-stats/raw.json   (what Anki says)
    python3 tools/pt_stats.py --build    -> pt-stats/data.json  (what it means)

Only the Portuguese decks are here. `qtarot` is a Russian tarot deck and is not part
of learning Portuguese, so it is left out on purpose.

`raw.json` holds, for each deck: every card's current state (maturity, interval, ease,
reps, lapses, due date) and the whole review log - one row per answer ever given, with
the button pressed, the interval before and after, the ease, how long the answer took
and whether it was a learning step or a review. `cardReviews` returns those as
`[reviewTime, cardId, usn, ease, newIvl, lastIvl, factor, timeTaken, type]`; the sync
counter (`usn`) means nothing outside Anki and is dropped.
"""
from __future__ import annotations

import argparse
import bisect
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
# Reuse the one helper that knows how this AnkiConnect expects its arguments.
from words2_anki import anki  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATS = ROOT / "pt-stats"
RAW = STATS / "raw.json"
DATA = STATS / "data.json"

DECKS = ["words", "words2", "listening", "listening2", "mnemonics"]

# Asked for in chunks: one call for eleven hundred cards is a lot of collection work
# to hold in a single reply, and a failure halfway would cost the whole deck.
CARD_CHUNK = 250

# The bits of a card worth keeping. The question and answer HTML is not among them -
# it is most of the payload and none of the numbers.
CARD_KEYS = ("cardId", "note", "deckName", "modelName", "type", "queue", "due",
             "interval", "factor", "reps", "lapses", "left", "mod")

# Anki's revlog `type`: 0 first learning, 1 scheduled review, 2 relearning after a lapse,
# 3 cramming, 4 a manual change (edited, rescheduled, set due date). Only 0-2 are the
# user answering a card, so only those count as study.
LEARNING, REVIEW, RELEARNING = 0, 1, 2
STUDY_TYPES = (LEARNING, REVIEW, RELEARNING)
# A card's own `type` is a different code for the same ideas: a card in its review phase
# is 2, where the log row that put it there was 1. Mixing the two makes every card look
# like it is still learning, which is how it was before this was written down.
CARD_NEW, CARD_LEARNING, CARD_REVIEW, CARD_RELEARNING = 0, 1, 2, 3


def is_review_card(card: dict) -> bool:
    """True when a card is in its review phase and has an interval to talk about."""
    return card["type"] == CARD_REVIEW and card["interval"] >= 1
PASS = 2            # ease 1 is "Again"; 2 Hard, 3 Good, 4 Easy all pass
MATURE_DAYS = 21    # Anki's own line between a young card and a mature one
DAY_SECONDS = 86_400
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# Anki starts a new study day at 4am by default: a review answered at 1am belongs to the
# day before, and so does the due date it schedules. Measured here rather than assumed -
# with a midnight boundary every card last answered between 00:00 and 02:59 sat exactly
# one day off the schedule Anki had written (237 of 1661 cards, and not one card outside
# those hours), and with this one every card agrees.
ROLLOVER_HOUR = 4


def label_of(card: dict) -> str:
    """What to call a card in a list of hardest words: a word, or the sentence it asks.

    A listening card is named `ts0042` or `cm0042`, which tells a reader nothing. Its
    sentence does: the decks put the Portuguese line in bold in the answer, so that is
    the label when the id is all the word field holds.
    """
    fields = {k: v.get("value", "") for k, v in card.get("fields", {}).items()}
    for name in ("word", "Portuguese", "English", "Front"):
        value = tidy(fields.get(name, ""))
        if value and not re.fullmatch(r"[a-z]{2}\d{4}", value):
            return value[:60]
    for name in ("back", "front"):
        bold = re.search(r"<b>(.*?)</b>", fields.get(name, ""), re.S)
        if value := tidy(bold.group(1) if bold else fields.get(name, "")):
            return value[:60]
    return str(card["cardId"])


def tidy(text: str) -> str:
    """Display text with the markup and the sound tags taken out."""
    text = re.sub(r"\[sound:[^\]]+\]", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def chapter_of(card: dict) -> str:
    """The chapter a card came from: the note's field, or its `chapterNN` tag.

    The newer deck carries the chapter as a field and the older one as a tag, so both
    are read before giving up. The tag is the more durable of the two - a field gets
    rewritten by whatever last touched the note.
    """
    fields = card.get("fields", {})
    for name in ("Chapter", "chapter"):
        value = (fields.get(name) or {}).get("value", "").strip()
        if value:
            return value.replace("\n", " ")[:80]
    for tag in card.get("tags") or []:
        if m := re.fullmatch(r"chapter0*(\d+)", tag):
            return f"Chapter {m.group(1)}"
    return ""


def tags_of(cards: list[dict]) -> dict[int, list[str]]:
    """Each card's tags, by card id - `cardsInfo` does not carry them."""
    notes = [c["note"] for c in cards if c.get("note")]
    out: dict[int, list[str]] = {}
    for start in range(0, len(notes), CARD_CHUNK):
        for note in anki("notesInfo", notes=notes[start:start + CARD_CHUNK]):
            for card_id in note.get("cards", []):
                out[card_id] = note.get("tags", [])
    return out


def cards_of(deck: str) -> list[dict]:
    """Every card in one deck, with its current scheduling state."""
    ids = anki("findCards", query=f"deck:{deck}")
    cards = []
    for start in range(0, len(ids), CARD_CHUNK):
        for card in anki("cardsInfo", cards=ids[start:start + CARD_CHUNK]):
            row = {key: card.get(key) for key in CARD_KEYS if key in card}
            row["label"] = label_of(card)
            cards.append(row)
    tags = tags_of(cards)
    for card in cards:
        card["tags"] = tags.get(card["cardId"], [])
        if chapter := chapter_of(card):
            card["chapter"] = chapter
    return cards


def pull() -> dict:
    out: dict = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "source": "AnkiConnect", "decks": {}}
    for deck in DECKS:
        cards = cards_of(deck)
        rows = anki("cardReviews", deck=deck, startID=0)
        # [reviewTime, cardId, usn, ease, newIvl, lastIvl, factor, timeTaken, type]
        reviews = [{"t": r[0], "card": r[1], "ease": r[3], "new": r[4], "last": r[5],
                    "factor": r[6], "ms": r[7], "type": r[8]} for r in rows]
        out["decks"][deck] = {
            "cards": cards, "reviews": reviews,
            "notes_in_deck": len(anki("findNotes", query=f"deck:{deck}")),
        }
        span = ""
        if reviews:
            span = (f'{time.strftime("%Y-%m-%d", time.localtime(min(r["t"] for r in reviews) / 1000))}'
                    f' .. {time.strftime("%Y-%m-%d", time.localtime(max(r["t"] for r in reviews) / 1000))}')
        print(f'  {deck:12s} cards={len(cards):5d} reviews={len(reviews):6d}  {span}', flush=True)
    return out


def median(values: list[float]) -> float:
    """The middle value, and for an even count the midpoint of the middle two."""
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    return (ordered[middle] if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) / 2)


def day_of(ms: int) -> str:
    """The study day a review belongs to - Anki's day, which starts at 4am."""
    return time.strftime("%Y-%m-%d", time.localtime(ms / 1000 - ROLLOVER_HOUR * 3600))


def week_of(ms: int) -> str:
    """The Monday of the week a review belongs to - the week's label."""
    stamp = time.localtime(ms / 1000)
    monday = time.mktime((stamp.tm_year, stamp.tm_mon, stamp.tm_mday, 12, 0, 0, 0, 0, -1)) \
        - stamp.tm_wday * DAY_SECONDS
    return time.strftime("%Y-%m-%d", time.localtime(monday))


def bucket(value: float, edges: list[float], labels: list[str]) -> str:
    """The name of the bucket a value falls in. The last label catches everything."""
    for edge, name in zip(edges, labels):
        if value <= edge:
            return name
    return labels[-1]


# How long a card had been left alone, against how often it was still known. The
# question this answers is the learner's: does the word survive two weeks, a month?
INTERVAL_EDGES = [1, 3, 7, 14, 30, 60, 120, 240]
INTERVAL_LABELS = ["1d", "2-3d", "4-7d", "8-14d", "15-30d", "31-60d", "61-120d",
                   "121-240d", "240d+"]
# How long one answer takes. Anki stops its own timer at a minute, so the top bucket is
# a floor, not a measurement.
TIME_EDGES = [2, 5, 10, 20, 40]
TIME_LABELS = ["under 2s", "2-5s", "5-10s", "10-20s", "20-40s", "over 40s"]
EASE_EDGES = [140, 160, 180, 200, 220, 240, 260]
EASE_LABELS = ["under 140%", "140-159%", "160-179%", "180-199%", "200-219%",
               "220-239%", "240-259%", "260%+"]
# Anki reports a card's ease factor in tenths of a percent: 2500 is 250%.
EASE_SCALE = 10
LAPSE_EDGES = [0, 1, 2, 3, 5, 10]
LAPSE_LABELS = ["0", "1", "2", "3-4", "5-9", "10+"]


def reviews_by_card(reviews: list[dict]) -> dict[int, list[dict]]:
    """The log cut up per card, each card's answers in the order they happened."""
    out: dict[int, list[dict]] = {}
    for row in sorted(reviews, key=lambda r: r["t"]):
        out.setdefault(row["card"], []).append(row)
    return out


def summarise(cards: list[dict], reviews: list[dict]) -> dict:
    """The headline numbers for one deck, or for all of them together."""
    per_card = reviews_by_card(reviews)
    studied = [r for r in reviews if r["type"] in STUDY_TYPES]
    answers = [r["ms"] for r in studied if r["ms"] > 0]
    days = sorted({day_of(r["t"]) for r in studied})

    # Current standing comes from the cards, not the log: only a card knows whether it
    # is suspended, and how long its interval has grown to.
    standing = {"new": 0, "learning": 0, "young": 0, "mature": 0, "suspended": 0}
    for card in cards:
        if card["queue"] == -1:
            standing["suspended"] += 1
        elif card["type"] in (CARD_LEARNING, CARD_RELEARNING) or card["queue"] in (1, 3):
            standing["learning"] += 1
        elif not is_review_card(card):
            standing["new"] += 1
        elif card["interval"] >= MATURE_DAYS:
            standing["mature"] += 1
        else:
            standing["young"] += 1

    answered = len(studied)
    return {
        "cards": len(cards), "reviews": len(reviews), "answers": answered,
        "seconds": round(sum(r["ms"] for r in studied) / 1000),
        "hours": round(sum(r["ms"] for r in studied) / 3_600_000, 1),
        "median_seconds": round(median(answers) / 1000, 1) if answers else 0,
        "mean_seconds": round(sum(answers) / len(answers) / 1000, 1) if answers else 0,
        "active_days": len(days), "first_day": days[0] if days else None,
        "last_day": days[-1] if days else None,
        "started": len(per_card), "never_seen": len(cards) - len(per_card),
        "pass_rate": round(100 * sum(1 for r in studied if r["ease"] >= PASS) / answered, 1)
                     if answered else 0,
        "standing": standing,
        "mature_pct": round(100 * standing["mature"] / len(cards), 1) if cards else 0,
        "reviews_per_active_day": round(answered / len(days), 1) if days else 0,
        "minutes_per_active_day": round(sum(answers) / 60_000 / len(days), 1) if days else 0,
    }


def daily_series(reviews: list[dict]) -> list[dict]:
    """One row per day studied: what was answered, how long it took, what was new."""
    days: dict[str, dict] = {}
    seen: set[int] = set()
    for row in sorted(reviews, key=lambda r: r["t"]):
        if row["type"] not in STUDY_TYPES:
            continue
        day = days.setdefault(day_of(row["t"]), {
            "d": day_of(row["t"]), "reviews": 0, "ms": [], "new": 0, "learn": 0,
            "review": 0, "again": 0, "hard": 0, "good": 0, "easy": 0})
        day["reviews"] += 1
        day["ms"].append(row["ms"])
        day["learn"] += 1 if row["type"] in (LEARNING, RELEARNING) else 0
        day["review"] += 1 if row["type"] == REVIEW else 0
        day["again"] += 1 if row["ease"] == 1 else 0
        day["hard"] += 1 if row["ease"] == 2 else 0
        day["good"] += 1 if row["ease"] == 3 else 0
        day["easy"] += 1 if row["ease"] == 4 else 0
        if row["card"] not in seen:
            seen.add(row["card"])
            day["new"] += 1
    out, started, total = [], 0, 0
    for day in sorted(days.values(), key=lambda d: d["d"]):
        started += day["new"]
        total += day["reviews"]
        day["seconds"] = round(sum(day.pop("ms")) / 1000)
        day["minutes"] = round(day["seconds"] / 60, 1)
        day["cards_started"] = started
        day["reviews_total"] = total
        out.append(day)
    return out


def buttons(reviews: list[dict]) -> dict:
    """Which button gets pressed, named as Anki names them."""
    names = {1: "again", 2: "hard", 3: "good", 4: "easy"}
    counts = {name: 0 for name in names.values()}
    for row in reviews:
        if row["type"] in STUDY_TYPES and (name := names.get(row["ease"])):
            counts[name] += 1
    return counts


def graduation(reviews: list[dict]) -> dict:
    """How many answers it took each card to leave the learning steps for the first time.

    This is the plainest reading of "how fast do I learn": a card graduates when it is
    first answered as a scheduled review rather than as a learning step. A card still in
    its steps has not graduated yet and is not counted.
    """
    counts, days = [], []
    for rows in reviews_by_card(reviews).values():
        steps = 0
        for row in rows:
            if row["type"] == REVIEW:
                counts.append(steps)
                days.append((row["t"] - rows[0]["t"]) / 1000 / DAY_SECONDS)
                break
            if row["type"] in (LEARNING, RELEARNING):
                steps += 1
    histogram: dict[str, int] = {}
    for count in counts:
        key = str(count) if count < 6 else "6+"
        histogram[key] = histogram.get(key, 0) + 1
    return {"n": len(counts), "histogram": dict(sorted(histogram.items())),
            "median": median(counts),
            "mean": round(sum(counts) / len(counts), 2) if counts else 0,
            "median_days": round(median(days), 1), "no_answer_yet": None}


def interval_step(reviews: list[dict]) -> list[dict]:
    """What interval a card is given next, against the interval it has just survived.

    This is the multiplier the scheduler is working with, and the taper is the point: a
    card one day old jumps out to a week, a card two months old barely moves. Only
    successful answers count towards the median - a lapse takes the interval back down
    on purpose, and averaging that in would say the scheduler was shrinking cards.
    """
    buckets: dict[str, dict] = {}
    for row in reviews:
        if row["type"] != REVIEW or row["last"] <= 0:
            continue
        name = bucket(row["last"], INTERVAL_EDGES, INTERVAL_LABELS)
        b = buckets.setdefault(name, {"last": name, "asked": 0, "passed": 0, "next": [],
                                      "factors": []})
        b["asked"] += 1
        if row["ease"] < PASS or row["new"] <= 0:
            continue
        b["passed"] += 1
        b["next"].append(row["new"])
        b["factors"].append(row["new"] / row["last"])
    out = []
    for name in INTERVAL_LABELS:
        if name not in buckets:
            continue
        b = buckets[name]
        b["median_next"] = round(median(b.pop("next")), 1)
        b["median_factor"] = round(median(b.pop("factors")), 2)
        b["pass_rate"] = round(100 * b["passed"] / b["asked"], 1)
        out.append(b)
    return out


def maturity_over_time(reviews: list[dict]) -> list[dict]:
    """How many cards stood at each stage, week by week, replayed from the log.

    Every answer records the interval the card was given, so the history can be replayed
    rather than guessed: on any date, each card's interval is whatever its last answer
    before that date set it to. This is the honest reading of "cards learned" - not how
    many were started, but how many were still waiting three weeks out at the time.
    """
    history = []
    for rows in reviews_by_card(reviews).values():
        marks = [(r["t"], r["new"] if r["new"] > 0 else 0)
                 for r in rows if r["type"] in STUDY_TYPES]
        if marks:
            history.append(([m[0] for m in marks], marks))
    if not history:
        return []
    first = min(times[0] for times, _ in history)
    latest = max(times[-1] for times, _ in history)
    start = time.mktime(time.strptime(week_of(first), "%Y-%m-%d"))
    latest_stamp = latest / 1000
    out = []
    for week in range(int((latest_stamp - start) / DAY_SECONDS / 7) + 1):
        end = start + (week * 7 + 7) * DAY_SECONDS
        counts = {"learning": 0, "young": 0, "mature": 0}
        for times, marks in history:
            index = bisect.bisect_left(times, end * 1000) - 1
            if index < 0:
                continue
            interval = marks[index][1]
            counts["mature" if interval >= MATURE_DAYS
                   else "young" if interval >= 1 else "learning"] += 1
        total = sum(counts.values())
        out.append({"week": time.strftime("%Y-%m-%d", time.localtime(start + week * 7 * DAY_SECONDS)),
                    **counts, "started": total,
                    "mature_pct": round(100 * counts["mature"] / total, 1) if total else 0})
    return out


def forgetting_curve(reviews: list[dict]) -> list[dict]:
    """How often a card is still known, against how long it had been left alone.

    Only scheduled reviews count: a learning step is a card being taught, not tested.
    """
    buckets: dict[str, dict] = {}
    for row in reviews:
        if row["type"] != REVIEW or row["last"] <= 0:
            continue
        name = bucket(row["last"], INTERVAL_EDGES, INTERVAL_LABELS)
        b = buckets.setdefault(name, {"interval": name, "n": 0, "passed": 0, "again": 0})
        b["n"] += 1
        b["passed"] += 1 if row["ease"] >= PASS else 0
        b["again"] += 1 if row["ease"] == 1 else 0
    out = []
    for name in INTERVAL_LABELS:
        if name in buckets:
            b = buckets[name]
            b["pass_rate"] = round(100 * b["passed"] / b["n"], 1)
            out.append(b)
    return out


def weekly_series(reviews: list[dict]) -> list[dict]:
    """A week at a time: how much was answered, how fast, and how much of it stuck."""
    weeks: dict[str, dict] = {}
    for row in reviews:
        if row["type"] not in STUDY_TYPES:
            continue
        w = weeks.setdefault(week_of(row["t"]), {"week": week_of(row["t"]), "n": 0,
                                                 "passed": 0, "ms": []})
        w["n"] += 1
        w["passed"] += 1 if row["ease"] >= PASS else 0
        if row["ms"] > 0:
            w["ms"].append(row["ms"])
    out = []
    for w in sorted(weeks.values(), key=lambda w: w["week"]):
        w["pass_rate"] = round(100 * w["passed"] / w["n"], 1)
        w["median_seconds"] = round(median(w.pop("ms")) / 1000, 1)
        w["minutes"] = round(sum(r["ms"] for r in reviews
                                  if week_of(r["t"]) == w["week"] and r["type"] in STUDY_TYPES)
                             / 60_000, 1)
        out.append(w)
    return out


def distributions(cards: list[dict], reviews: list[dict]) -> dict:
    """The shapes behind the averages: lapses, ease, intervals, answers, answer time."""
    per_card = reviews_by_card(reviews)
    def tally(names: list[str], values) -> dict[str, int]:
        out = {name: 0 for name in names}
        for name in values:
            out[name] = out.get(name, 0) + 1
        return out

    lapses = tally(LAPSE_LABELS,
                   (bucket(c["lapses"], LAPSE_EDGES, LAPSE_LABELS) for c in cards))
    ease = tally(EASE_LABELS,
                 (bucket(c["factor"] / EASE_SCALE, EASE_EDGES, EASE_LABELS)
                  for c in cards if c["factor"] > 0))

    def interval_name(card: dict) -> str:
        if card["queue"] == -1:
            return "suspended"
        if not is_review_card(card):
            return "still learning"
        return bucket(card["interval"], [1, 3, 7, 14, 30, 60, 120, 240],
                      ["1d", "2-3d", "4-7d", "8-14d", "15-30d", "31-60d", "61-120d",
                       "121-240d", "240d+"])
    interval_labels = ["still learning", "1d", "2-3d", "4-7d", "8-14d", "15-30d",
                       "31-60d", "61-120d", "121-240d", "240d+", "suspended"]
    intervals = tally(interval_labels, (interval_name(c) for c in cards))

    answer_labels = ["0", "1", "2-3", "4-7", "8-15", "16-30", "31+"]
    answers = tally(answer_labels,
                    (bucket(len(per_card.get(c["cardId"], [])), [0, 1, 3, 7, 15, 30], answer_labels)
                     for c in cards))
    times = tally(TIME_LABELS,
                  (bucket(r["ms"] / 1000, TIME_EDGES, TIME_LABELS)
                   for r in reviews if r["type"] in STUDY_TYPES and r["ms"] > 0))
    return {"lapses": lapses, "ease": ease, "interval": intervals,
            "reviews_per_card": answers, "answer_time": times}


def hardest(cards: list[dict], reviews: list[dict], limit: int = 12) -> list[dict]:
    """The cards that keep coming back: most lapses first, then most answers."""
    per_card = reviews_by_card(reviews)
    rows = [{"label": c["label"], "deck": c["deckName"], "lapses": c["lapses"],
             "reps": c["reps"], "interval": c["interval"],
             "ease": round(c["factor"] / 10) if c["factor"] else 0,
             "answers": len(per_card.get(c["cardId"], []))}
            for c in cards if c["reps"] > 0]
    rows.sort(key=lambda r: (-r["lapses"], -r["answers"], r["label"]))
    return rows[:limit]


def easiest(cards: list[dict], limit: int = 10) -> list[dict]:
    """The words that stuck: longest interval, no lapses, fewest answers needed."""
    rows = [{"label": c["label"], "deck": c["deckName"], "interval": c["interval"],
             "ease": round(c["factor"] / 10) if c["factor"] else 0,
             "lapses": c["lapses"], "reps": c["reps"]}
            for c in cards if c["reps"] > 0 and c["lapses"] == 0 and c["interval"] > 0]
    rows.sort(key=lambda r: (-r["interval"], r["reps"], r["label"]))
    return rows[:limit]


def hour_weekday(reviews: list[dict]) -> dict:
    """When the studying happens: minutes answered, by weekday and hour of the day."""
    grid = [[0.0] * 24 for _ in range(7)]
    for row in reviews:
        if row["type"] not in STUDY_TYPES:
            continue
        stamp = time.localtime(row["t"] / 1000)
        grid[stamp.tm_wday][stamp.tm_hour] += row["ms"] / 60_000
    return {"weekdays": WEEKDAYS, "grid": [[round(v, 1) for v in row] for row in grid]}


def streaks(reviews: list[dict]) -> dict:
    """The current and longest run of consecutive days with at least one answer."""
    days = sorted({day_of(r["t"]) for r in reviews if r["type"] in STUDY_TYPES})
    if not days:
        return {"current": 0, "longest": 0, "active_days": 0}
    stamps = [time.mktime(time.strptime(d, "%Y-%m-%d")) for d in days]
    longest = run = 1
    for previous, current in zip(stamps, stamps[1:]):
        run = run + 1 if current - previous <= 1.5 * DAY_SECONDS else 1
        longest = max(longest, run)
    today = day_of(int(time.time() * 1000))
    current = 0
    if days[-1] == today:
        current = 1
        for index in range(len(days) - 1, 0, -1):
            if stamps[index] - stamps[index - 1] <= 1.5 * DAY_SECONDS:
                current += 1
            else:
                break
    return {"current": current, "longest": longest, "active_days": len(days)}


def schedule_baseline(cards: list[dict], reviews: list[dict]) -> int | None:
    """Anki's day number for today, worked out from the cards it has already scheduled.

    Anki stores a review card's `due` as a day number counted from the day the
    collection was created, and stores the interval it was given in the review log. So
    for a card answered on the most recent day of study and still waiting, `due minus
    interval` is that day's number, and the median of those is today - no guessing, and
    no reading of Anki's own database.
    """
    per_card = reviews_by_card(reviews)
    latest = max((rows[-1]["t"] for rows in per_card.values() if rows), default=0)
    last_day = day_of(latest)
    offsets = [card["due"] - rows[-1]["new"]
               for card in cards
               if (rows := per_card.get(card["cardId"])) and card["queue"] == 2
               and card["interval"] > 0 and rows[-1]["type"] in (REVIEW, RELEARNING)
               and rows[-1]["new"] > 0 and day_of(rows[-1]["t"]) == last_day]
    return int(median(offsets)) if offsets else None


def forecast(cards: list[dict], baseline: int | None, days: int = 30) -> list[dict]:
    """How much is waiting on each of the next days, from the cards' own due numbers."""
    if baseline is None:
        return []
    counts: dict[int, int] = {}
    for card in cards:
        if card["queue"] != 2 or not card["interval"]:
            continue
        offset = card["due"] - baseline
        counts[offset] = counts.get(offset, 0) + 1
    return [{"offset": offset, "cards": counts.get(offset, 0),
             "date": time.strftime("%Y-%m-%d", time.localtime(time.time() + offset * DAY_SECONDS))}
            for offset in range(0, days + 1)]


def chapters(cards: list[dict]) -> list[dict]:
    """Progress chapter by chapter, for the decks whose notes carry a chapter."""
    groups: dict[str, dict] = {}
    for card in cards:
        name = card.get("chapter")
        if not name:
            continue
        g = groups.setdefault(name, {"chapter": name, "cards": 0, "started": 0,
                                     "mature": 0, "learning": 0, "intervals": []})
        g["cards"] += 1
        if card["reps"] > 0 or card["interval"] > 0:
            g["started"] += 1
        if card["queue"] != -1 and is_review_card(card) and card["interval"] >= MATURE_DAYS:
            g["mature"] += 1
        if card["queue"] == -1 or not is_review_card(card):
            g["learning"] += 1
        if card["interval"] > 0:
            g["intervals"].append(card["interval"])

    def order(name: str) -> tuple:
        digits = re.search(r"(\d+)", name)
        return (int(digits.group(1)) if digits else 0, name)

    out = []
    for g in sorted(groups.values(), key=lambda g: order(g["chapter"])):
        g["median_interval"] = round(median(g.pop("intervals")), 1)
        g["mature_pct"] = round(100 * g["mature"] / g["cards"], 1)
        out.append(g)
    return out


def deck_block(cards: list[dict], reviews: list[dict], baseline: int | None) -> dict:
    """Everything the dashboard shows for one set of cards and one review log.

    The baseline is passed in rather than worked out here: a card's `due` is a day
    number counted from the collection, so "today" is the same number for every deck and
    only the collection as a whole can say what it is.
    """
    daily = daily_series(reviews)
    block = {
        "summary": summarise(cards, reviews),
        "daily": daily,
        "days": [{"d": d["d"], "reviews": d["reviews"], "minutes": d["minutes"],
                 "new": d["new"]} for d in daily],
        "hour_weekday": hour_weekday(reviews),
        "weekly": weekly_series(reviews),
        "buttons": buttons(reviews),
        "graduation": graduation(reviews),
        "interval_step": interval_step(reviews),
        "maturity_over_time": maturity_over_time(reviews),
        "forgetting_curve": forgetting_curve(reviews),
        "distributions": distributions(cards, reviews),
        "hardest": hardest(cards, reviews),
        "easiest": easiest(cards),
        "streaks": streaks(reviews),
        "schedule_baseline": baseline,
        "forecast": forecast(cards, baseline),
        "chapters": chapters(cards),
    }
    return block


BLOCKS = ["summary", "daily", "days", "hour_weekday", "weekly", "buttons", "graduation",
          "interval_step", "maturity_over_time", "forgetting_curve", "distributions",
          "hardest", "easiest", "streaks", "schedule_baseline", "forecast", "chapters"]


def build() -> dict:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    decks = raw["decks"]
    all_cards = [c for d in decks.values() for c in d["cards"]]
    all_reviews = [r for d in decks.values() for r in d["reviews"]]

    # One baseline for every deck: `due` is counted from the collection, so today's day
    # number is the same everywhere.
    baseline = schedule_baseline(all_cards, all_reviews)
    out: dict = {"generated": raw["generated"], "built": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "source": raw["source"], "decks": list(decks), "blocks": BLOCKS,
                 "today_day_number": baseline}
    for name, (cards, reviews) in {"all": (all_cards, all_reviews),
                                   **{d: (v["cards"], v["reviews"]) for d, v in decks.items()}}.items():
        out[name] = deck_block(cards, reviews, baseline)

    out["comparison"] = [{"deck": name, **{k: out[name]["summary"][k] for k in
                          ("cards", "reviews", "answers", "hours", "median_seconds",
                           "pass_rate", "active_days", "mature_pct")}}
                          for name in ["all"] + list(decks)]
    for row, name in zip(out["comparison"], ["all"] + list(decks)):
        row["mature_cards"] = out[name]["summary"]["standing"]["mature"]
        row["median_reps_to_graduate"] = out[name]["graduation"]["median"]
        row["suspended"] = out[name]["summary"]["standing"]["suspended"]
    out["hour_weekday"] = hour_weekday(all_reviews)
    out["days"] = [{"d": d["d"], "reviews": d["reviews"], "minutes": d["minutes"],
                    "new": d["new"]} for d in out["all"]["daily"]]
    return out


def report(data: dict) -> None:
    """Print the checks that make the build believable, not just its summary."""
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    print("cross-checks against raw.json")
    for deck in ["all"] + list(raw["decks"]):
        if deck == "all":
            cards = [c for d in raw["decks"].values() for c in d["cards"]]
            reviews = [r for d in raw["decks"].values() for r in d["reviews"]]
        else:
            cards, reviews = raw["decks"][deck]["cards"], raw["decks"][deck]["reviews"]
        s = data[deck]["summary"]
        study = [r for r in reviews if r["type"] in STUDY_TYPES]
        daily = sum(d["reviews"] for d in data[deck]["daily"])
        newest = sorted({day_of(r["t"]) for r in study})[-1]
        nonstudy = len(reviews) - len(study)
        print(f'  {deck:12s} cards {len(cards)}={s["cards"]}  study {len(study)}={s["answers"]}'
              f'  daily sum {daily}={s["answers"]}'
              f'  last day {newest}={s["last_day"]}'
              f'  manual/cram rows {nonstudy}'
              f'  pass {round(100*sum(1 for r in study if r["ease"]>=PASS)/len(study),1)}={s["pass_rate"]}')
    baseline = data["all"]["schedule_baseline"]
    print(f'\nschedule baseline (today as a day number): {baseline}')
    print(f'forecast starts: ' + ', '.join(
        f'{d} {[f["cards"] for f in data[d]["forecast"][:7]]}' for d in ["all"] + list(raw["decks"])))
    # Prove the forecast's arithmetic on every scheduled card. Anki fuzzes intervals
    # above a couple of days, so a few cards are expected to sit a day or two off the
    # number worked back from their last review; a large disagreement would mean the
    # baseline itself is wrong.
    today = day_of(int(time.time() * 1000))
    today_stamp = time.mktime(time.strptime(today, "%Y-%m-%d")) + ROLLOVER_HOUR * 3600
    per_card = reviews_by_card([r for d in raw["decks"].values() for r in d["reviews"]])
    agree = disagree = 0
    for card in [c for d in raw["decks"].values() for c in d["cards"]]:
        rows = per_card.get(card["cardId"])
        if not rows or card["queue"] != 2 or card["interval"] <= 0:
            continue
        last = rows[-1]
        if last["type"] not in (REVIEW, RELEARNING) or last["new"] <= 0:
            continue
        since = round((today_stamp - time.mktime(time.strptime(day_of(last["t"]), "%Y-%m-%d")))
                      / DAY_SECONDS)
        if card["due"] - last["new"] + since == baseline:
            agree += 1
        else:
            disagree += 1
    print(f'forecast arithmetic: {agree} scheduled cards confirm today = day {baseline}, '
          f'{disagree} sit off it (Anki fuzzes long intervals)')
    print(f'\ngraduation medians: ' + ', '.join(
        f'{d} {data[d]["graduation"]["median"]} ({data[d]["graduation"]["n"]} cards)'
        for d in ["all"] + list(raw["decks"])))
    print(f'chapters: ' + ', '.join(f'{d} {len(data[d]["chapters"])}' for d in raw["decks"]))
    print(f'heatmap days: {len(data["days"])}, hour grid rows {len(data["hour_weekday"]["grid"])}'
          f'x{len(data["hour_weekday"]["grid"][0])}')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pull", action="store_true", help="read Anki into pt-stats/raw.json")
    parser.add_argument("--build", action="store_true", help="derive pt-stats/data.json")
    args = parser.parse_args()
    if args.pull:
        STATS.mkdir(parents=True, exist_ok=True)
        data = pull()
        RAW.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
        total = sum(len(d["reviews"]) for d in data["decks"].values())
        cards = sum(len(d["cards"]) for d in data["decks"].values())
        print(f'\nwrote {RAW.relative_to(ROOT)}: {cards} cards, {total} review rows, '
              f'{RAW.stat().st_size / 1024:.0f} KB')
        return
    if args.build:
        data = build()
        report(data)
        DATA.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f'\nwrote {DATA.relative_to(ROOT)}: {DATA.stat().st_size / 1024:.0f} KB')
        return
    raise SystemExit("give --pull (or --build)")


if __name__ == "__main__":
    main()
