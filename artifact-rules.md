# artifact-rules

Rules for the origin-layer pages (the HTML/PDF book built from this deck).
Derived from what went wrong on layer 03 and had to be fixed. Apply to every new
page, and to any page being revised.

How a layer is *chosen* — which sound law, which words qualify, what evidence to
print — is in `book-prompt.md`. This file is the presentation half.

---

## 1. Medium mismatch — no interaction-gated content

The pages are printed to PDF. Hover does not exist in a PDF, so anything only
reachable by hovering is lost.

- No tooltips, no popovers, no `title=` attributes carrying real content.
- No accordions, tabs, or "click to reveal".
- If a fact is worth writing, it is on the page as text.
- Print CSS: `print-color-adjust: exact`, `break-inside: avoid` on every card,
  tightened padding, ~10.5pt body.

**Check:** disable JavaScript and print to PDF. Nothing may be missing.

---

## 2. Abstraction with no instance — every form gets a sentence

A word, form or rule shown without a real sentence is not learnable.

- Every Portuguese word or verb form gets at least one example sentence.
- Prefer sentences from the deck itself. Show the card number (`card 0159`) so
  the book and Anki cross-reference.
- Sentences not in the deck are marked `new` (dashed tag). They are candidates
  for new cards.
- Bold the target word in the sentence, in that item's colour.

### Words the deck does not have

The deck is the starting point, not the ceiling. A page that covers a pattern
must cover it properly.

- **Include an off-deck word when it is A1–B1 and it belongs to the page's
  pattern.** A missing A1 word is a hole in the page, not a boundary to respect.
  `espelho` belongs on any page about `es-`, and the deck not having it is the
  deck's problem.
- Mark every one with a `no card` tag (dotted), distinct from the dashed `new`
  tag. `new` means the word is in the deck but the sentence was written here.
  `no card` means the word itself is missing from the deck.
- Above B1, include an off-deck word only when the page needs it as evidence —
  and say why in the row.
- Count them separately. Every total must say how many cards and how many
  off-deck words, and never fold the two into one number.
- Off-deck words are the best candidates for new cards, so the deck-check section
  should name the strongest of them.
- **Sentences may use a few off-deck words too.** A sentence that is stilted
  because the natural word is missing from the deck teaches worse Portuguese
  than one that borrows `mais` or `muito`. Prefer deck vocabulary, reach outside
  it when the natural sentence needs it, and keep the borrowed words A1–A2.
  Naturalness beats vocabulary purity — the reader is learning the language, not
  auditing the deck.

---

## 3. Register — A2 English maximum

The reader is learning Portuguese, not English. Difficult English steals effort
from the actual subject.

- Short sentences, one idea each. Aim 10–15 words.
- Plain words. Not *melted down*, *casualties*, *whatever was lying around*.
- No metaphor unless the metaphor **is** the content (sit vs stand is the real
  meaning of *sedēre* / *stāre*, so it stays).
- No rhetorical tics. The "It is not X. It is Y." pattern is allowed **once per
  page**, never more.
- Do not tell the reader why they were confused.
- Terms that are the content stay: Latin forms, PIE roots, macrons, tense names.
  Define a term the first time it is used, in a term box.

**Exception:** Latin, grammar labels, and linguistic terms are not simplified.
They are the material.

---

## 4. One table, one job

A table that carries origin *and* forms *and* examples *and* sources is
unreadable at any size.

- Split by job. On layer 03: an *origin map* (which tense came from which Latin
  verb, no examples) and separate *conjugation tables* (pronouns, forms,
  sentences).
- Many small tables beat one large table. Tile them in a responsive grid.
- A dense reference row may drop its examples; put the examples in their own
  table underneath.

---

## 5. Show the join key

Data listed without the thing it attaches to is correct and useless.

- Verb forms are listed with their pronouns (`eu / tu / ele / nós / eles`), never
  as a bare run of five words.
- Nouns are listed with gender and plural.
- Any list of forms must say what varies across the list.

---

## 6. State the scope, and why each item qualifies

If the reader cannot tell why something is on the page, the page is wrong — not
the reader.

- Near the top, a scope block: which items this page covers, and one line per
  item saying **why it qualifies**.
- Items can be present for different reasons. Say so. On layer 03: `ser` and `ir`
  are here because they are mixed; `estar` is here because you cannot use `ser`
  without it.
- Section headings are labels, not essay titles. "Where every tense comes from",
  not "Two verbs, five ancestors".

---

## 7. Show the evidence, do not assert it

The worst failure mode, because the page still looks finished.

A short tag like `shared with ser`, `swallowed`, or `analogy` asks the reader to
trust a claim they cannot check on the page.

- When a fact is surprising, print the evidence next to the claim.
- Bad: "its past tense is the same as *ser*".
- Good: both rows of forms, printed one above the other, marked *the same five
  words*.
- Where possible, add a cross-check the reader already knows — English "I have
  **been** to Lisbon" = "I **went** to Lisbon" makes the shared `fui` obvious.
- Where sources disagree, say so and mark it (dashed outline). Never launder a
  disputed etymology into a flat statement.

---

## 8. Flag the level, so the reader can skip

A correct page is still a bad use of today if the words on it are B2.

- Every word, verb form and tense carries a CEFR flag: `A1 A2 B1 B2 C1`.
- Every section carries a **topic level** line: the level, plus the count split,
  plus one sentence saying whether to read it now.
- The hero carries the level split for the whole page.
- The flag is a **monochrome** badge — fill weight, not hue. Colour is already
  spent on the etymology role (rule: layout conventions). Two colour scales on
  one page cannot both be read.
  - `A1` solid ink, `A2` solid ink-2, `B1` outline, `B2` dashed, `C1` dotted.
- Levels are an estimate. Say so in the footer, and say what the estimate is
  based on: everyday frequency in EP, and where the word falls in an A1–B1
  course. For tenses: the order a course teaches them.
- **The deck is not level-free, and the footer must not say it is.** 145 verb
  cards carry an `(A1)` mark in the `back` field. It is the level of the course
  book they came from, not a judgement about each word — it covers `mergulhar`
  "to dive" as readily as `falar`. Describe it accurately, and where a page's
  flag sits above that mark, that is a deliberate choice, not an oversight.
- Never let the flag override the reader: "if a word feels easy and it says B1,
  learn it."
- **Historical forms carry no flag.** `luita`, `oitubro`, `vĩo`, `oc'lum` are
  evidence, not vocabulary — the reader is never meant to learn them. Leave the
  badge off and label the row *not a modern word*, so the gap is a statement
  rather than an omission.

---

## Layout conventions (shared across layers)

- Palette must pass `dataviz/scripts/validate_palette.js` in **both** light and
  dark, against the page's own surface colour.
- Colours are per-layer roles. The footer must say what the colours mean on this
  page, because they mean something different on the next one.
- Type: serif for Portuguese and Latin specimens, sans for explanation, mono for
  roots, dates, card numbers and codes.
- Light and dark both defined at token level; `data-theme` overrides must beat
  the media query in both directions.

---

## Where the pages live

Source HTML is in `book/`. Editing a file there and republishing it with the
same artifact URL updates the page in place. See `book/readme.md` for the URLs.

---

## Still open (not yet decided)

- **Pronunciation.** `ety.md` asks for Cyrillic stress marks + IPA. No page has
  any. You cannot say these words out loud from the book.
- **Language of address.** `ety.md` is written in Russian and wants Russian
  cognates. The pages currently put English kin first.
- **Colour consistency.** Blue means *inherited* on layer 01, *-ānem* on layer
  02, *esse* on layer 03. No intuition can build across pages.
- **Takeaway block.** No page ends with "remember these three things".
- **Essay vs reference.** The pages read once well. They may not reward the
  second visit.
