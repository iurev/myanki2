# book

Origin layers of the deck, as standalone HTML pages. Each page is self-contained
(no external CSS, JS, fonts or images) and is meant to be printed to PDF.

Written to the rules in `../artifact-rules.md`. How a layer is *chosen* — which
sound law, which words qualify, what evidence to print, and the review passes
every layer goes through — is in `../book-prompt.md`. Layers 01–07 each had five
identical passes; from 2026-08 the standard is three.

## Pages

| file                    | layer | subject                                       | cards | artifact URL |
|-------------------------|-------|-----------------------------------------------|-------|--------------|
| `ch-layer.html`         | 01    | Latin `pl- cl- fl-` → `ch-`                    | 13    | https://claude.ai/code/artifact/c97cfaa0-5a38-483c-a8cf-a3de93cf8a0f |
| `nasal-layer.html`      | 02    | lost `n` and `l`, the `-ão` plural classes     | 17    | https://claude.ai/code/artifact/4f889f4b-7ce0-4bb3-b815-0475254f4b79 |
| `suppletion-layer.html` | 03    | `ser` · `ir` · `estar`, five Latin verbs       | —     | https://claude.ai/code/artifact/14a59085-a5a1-42fe-9e63-07dbe3737dec |
| `palatal-layer.html`    | 04    | `lh` · `nh`, two sounds Latin never had        | 44    | https://claude.ai/code/artifact/9f94dd88-3e27-4c93-ad8f-d3ba2754a101 |
| `es-layer.html`         | 05    | `s`+consonant → `es·`, three roads to it       | 28    | https://claude.ai/code/artifact/f2cbfeba-6ee9-4026-8484-53d854572c06 |
| `it-layer.html`         | 06    | `ct` `pt` `lt` → `·it·`, a consonant melts     | 18    | https://claude.ai/code/artifact/9cd6075e-958f-42ca-92c7-524ff4b22d70 |
| `eiro-layer.html`       | 07    | `-ārium` → `-eiro`, an ending still in use    | 19    | https://claude.ai/code/artifact/cb3dc079-e2ee-408c-994f-ed4d0a9b6214 |

Card counts are deck cards only. Each page also carries A1–B1 words the deck is
missing, tagged `no card` and counted separately — layer 04 has 15, layer 05 has
10, layer 06 has 10, layer 07 has 11. Those tables are the best source of new
cards to add.

## Levels: what the deck actually stores

The footers used to say the deck stores no level. It does, partly: **145 verb
cards carry an `(A1)` mark** in the `back` field, and nothing else in the deck
carries any level at all. That mark is the level of the course book the verbs
came from, not a judgement about each word — it covers `mergulhar` "to dive" as
readily as `falar`. Seventeen rows across six pages carry a flag above that mark;
that is deliberate, and the pages say so.

Do not confuse it with the `(ch.N)` chapter markers, which are on 47 cards and
mean something else entirely.

## Reading them locally

```
node book/serve.js [port]        # default 8787, binds 127.0.0.1
```

The page files are **fragments** — no `<!doctype>`, `<html>` or `<head>`, exactly
as the artifact host expects. `serve.js` adds the skeleton, a CSS reset and a
theme toggle so the dark palette can be exercised, then lists every page at
`http://127.0.0.1:8787/`. Opening a file over `file://` will not render properly.

## Editing

Edit the file here, then republish it to the **same** URL (pass the URL when
publishing from a session that did not create it, otherwise a new URL is
minted). The file in this directory is the source of truth.

Runtime check before publishing — catches a JS error that would silently blank a
whole section:

```
npm install jsdom          # in any scratch dir
node run.js <page>.html    # load with runScripts:"dangerously", count elements
```

## Colours

Colour roles are **per layer** and deliberately not shared:

- layer 01 — when the word entered Portuguese (spoken / borrowed / from books)
- layer 02 — which Latin ending the word came from (`-ānem` / `-ānum` / `-ōnem`)
- layer 03 — which Latin verb a form came from (`esse` / `fuī` / `sedēre` / …)
- layer 04 — which builder made the sound (yod / dropped vowel / returning nasal
  / borrowed), with grey for anything none of the four built

Each page states its own key in the footer. The palette values are shared.

**Palette was corrected in 2026-08.** The original green, orange and purple
failed 4.5:1 against `--paper-2` in light, and blue/purple collapsed under
protanopia. Current values, all ≥4.5:1 on both surfaces in both themes and
≥15 ΔE apart under deuteranopia, protanopia and tritanopia:

| role   | light     | dark      |
|--------|-----------|-----------|
| blue   | `#1F5FBF` | `#4E8BE0` |
| green  | `#0A744E` | `#0FA06B` |
| orange | `#A6501C` | `#D0783C` |
| purple | `#9E3A90` | `#C95CAB` |

**`--ink-3` was raised in 2026-08 too.** It carries every English gloss under
every Portuguese sentence, at 12px, and it sat at 3.28:1 — below AA for small
text. Now `#5F6A75` light (4.95 / 4.59), `#7C8690` dark (4.94 / 4.56) and
`#616B75` in print (5.43 / 4.66). All five pages share it.

Layer 03 carries a fifth role (`--fu`, crimson `#B03A5B` / `#D14E72`) that has
**not** been validated against the other four. Check it before relying on it.

Colour is never the only channel: every role is also named in text.

## Print

Every page forces the light palette inside `@media print`. Without that, printing
from a dark-themed browser produced near-white text on white paper — the bug was
in all four pages until it was found on layer 04.

Known and unfixed: at the ~703px print width the word rows fall below the
`max-width: 760px` breakpoint and stack into one column, which roughly doubles
the page count. All four pages share the breakpoint, so changing it is a
book-wide decision.

## Level flags

`A1 A2 B1 B2 C1` badges are monochrome on purpose — hue is already carrying the
etymology. The flags are an estimate based on everyday frequency in European
Portuguese and on where a word falls in an A1–B1 course. See *Levels: what the
deck actually stores* above for the one thing the deck does record. Adding a
real `level` field to the yaml would replace the estimate; that is not done yet.

## Deck facts worth knowing

- 724 notes, 720 distinct `word` values. The figure "677 words" appeared in every
  footer until 2026-08 and is not reproducible from the yaml by any metric.
- 232 notes carry a `skipped` field (`reason_similar` 132, `reason_phrase` 63,
  `reason_numbers` 30, `reason_reflexive` 7). Nothing in the repo reads it and
  `sync.py` pushes those notes regardless, so they *are* in Anki. Treat it as an
  author's annotation, not as absence.
- Phrase cards are not lemmas. A word that appears only inside a phrase has no
  gender, no plural and no standalone card — layer 04's deck check found three
  such gaps (`vinho`, `manhã`, `olhar`).
