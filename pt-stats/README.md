# Portuguese study statistics

A dashboard of every answer ever given in the Portuguese Anki decks: **words**,
**words2**, **listening**, **listening2**, **mnemonics**. `qtarot` is a Russian tarot
deck and is deliberately not here.

    python3 -m http.server 8899 --directory pt-stats
    # then open http://127.0.0.1:8899/

It is a static page: `index.html`, `app.js`, `style.css`, `data.json`, and two vendored
libraries in `vendor/` (ECharts for the charts, Bootstrap 5 for the dark chrome - both
local so the page works with no network). It needs a server rather than `file://` only
because it reads `data.json` with `fetch`.

## Where the numbers come from

Nothing on the page is typed in. `tools/pt_stats.py` reads Anki through AnkiConnect:

    python3 tools/pt_stats.py --pull     # Anki -> pt-stats/raw.json   (cards + review log)
    python3 tools/pt_stats.py --build    # raw  -> pt-stats/data.json  (the numbers)

`--pull` keeps, for each deck, every card's current scheduling state (maturity, interval,
ease, reps, lapses, due date, label, chapter) and the whole review log - one row per
answer ever given, with the button pressed, the interval before and after, the time it
took and whether it was a learning step or a scheduled review. About 2.5 MB for 2,954
cards and 14,896 answers; the built `data.json` is 97 KB.

`--build` prints cross-checks as it goes, and they are worth reading before trusting the
page: card counts, answer counts and the daily sums are all recomputed from `raw.json`
and compared, and the pass rate is derived twice. It also proves the due-date arithmetic
against every scheduled card (`1661 scheduled cards confirm today = day 158, 0 sit off`).

The two files are separate on purpose: `--build` is where the thinking is, so it can be
re-run and re-read in a second without touching Anki.

## Reading it honestly

A few decisions that the charts depend on, all of them measured rather than assumed:

- **A study day starts at 04:00**, as Anki has it. This is not cosmetic: with a midnight
  boundary, every card last answered between 00:00 and 02:59 sat exactly one day off the
  schedule Anki had written - 237 of 1,661 cards, and not one card outside those hours.
  About a fifth of the answers in this collection happen after midnight, so the choice
  moves real numbers.
- **A card's `type` is not a log row's `type`.** A card in its review phase is 2, while
  the log row that put it there was 1. Mixing them up makes every card look like it is
  still learning, which is what the first build of this page said.
- **Anki stops its own timer at one minute**, so no answer appears longer than that and
  the top bucket of the answer-time chart is a floor, not a measurement.
- **Only real answers count.** Cramming and manual rescheduling rows (`type` 3 and 4) are
  excluded from every number. There are none in these decks, and the check says so.
- **Suspended cards** are counted where the cards are counted (the standing donut, the
  deck table) and left out of the interval chart.
- **"All decks" is the sum**, not an average of each deck's percentage - which is why the
  deck buttons carry their card counts.
- **Chapters are shown one book at a time.** Each book numbers its own chapters, so adding
  them across decks would merge two unrelated chapter 1s.

## What is on the page

Sixteen charts and three tables, all of which follow the chosen deck:

| card | what it answers |
|---|---|
| Words that are sticking | the log replayed weekly: how many cards were still 21+ days out on that date |
| Where the cards stand now | new / learning / young / mature / suspended, as Anki has it |
| Which button gets pressed | Again, Hard, Good, Easy |
| What a study day looks like | first-time cards, learning steps, scheduled reviews, and the minutes |
| Week by week: how much stuck | pass rate against minutes spent |
| How far the scheduler pushes you | the interval given next, against the one just survived (the taper) |
| Does a word survive a month? | pass rate against how long the card had been left alone |
| Answers needed to graduate | answers before a card became a scheduled review |
| How far out the cards sit | the distribution of current intervals |
| How long an answer takes | answer time, capped at Anki's one minute |
| How often a card slips | lapses per card |
| What is waiting in the next 30 days | the real queue, from the due dates Anki already wrote |
| The habit, day by day | a calendar of study days |
| When the studying happens | minutes by weekday and hour |
| Cards seen and answers given | cumulative cards and answers |
| Chapter by chapter | per chapter, for one book deck only |

Plus three tables: the five decks side by side, the words with the most lapses, and the
words with the longest intervals that have never lapsed.

## Checking it still works

`tools/pt_stats_cdp.mjs` looks at the page in a real browser over the DevTools protocol
(no browser driver needed - it uses the WebSocket Node already has, so it cannot reach a
browser in another network namespace):

    google-chrome-stable --headless=new --remote-debugging-port=9222 \
        --user-data-dir=/tmp/pt-stats-chrome about:blank      # keep this running
    node tools/pt_stats_cdp.mjs --url http://127.0.0.1:8899/ --out /tmp/page.png \
        --width 1500 --height 950 --full                      # screenshot + console
    node tools/pt_stats_cdp.mjs --url http://127.0.0.1:8899/ \
        --click '[data-deck="words"]' --read 'document.title'  # click, then read the DOM

It prints every console message, the result of `--read`, and exits non-zero if the page
threw an error - a screenshot that looks fine while the console is full of failures is
not a pass.
