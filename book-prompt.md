# book-prompt

How a layer is actually chosen and built. The thinking, not the markup.
Formatting rules live in `artifact-rules.md`; this file is the part that decides
*what goes on the page at all*.

---

## What a layer is

A layer is **one historical event** that touched many words in the deck, and left
a trace you can still see today.

Not a topic. Not a word family. An event — a sound that changed, an ending that
merged, a verb that got replaced. The words on the page are there because the
same thing happened to all of them.

The test: can you write the event as one arrow?

```
pl- cl- fl-   →   ch-          (layer 01)
-n- -l-       →   nothing      (layer 02)
esse + fuī    →   one verb     (layer 03)
```

If the arrow needs an "and also", it is two layers.

---

## Finding a layer in the deck

Work from the deck outward, never from a grammar book inward. A beautiful sound
law that touched three cards is not a layer; it is a footnote.

**1. Look for a shape that repeats.**
Scan the word list for a letter pattern that shows up more than ~8 times:
a starting cluster (`ch-`), an ending (`-ão`, `-ção`, `-agem`), a vowel with a
mark (`ã`, `õ`), a gap where a letter should be (`lua`, `cor`, `dor`).

**2. Ask what it was before.**
Take three of them to Latin. If they arrive at the same Latin shape, that shape
is the layer. `chamar ← clamāre`, `chave ← clāvem`, `cheio ← plēnum` — all had a
consonant + `l`. That is the layer.

**3. Count the deck, not the language.**
Count how many cards actually qualify. Under ~10 cards, drop it or fold it into a
neighbouring layer. The page has to earn a page.

**4. Check the impostors.**
Every pattern collects words that only *look* like they belong. `chocolate`
never had a cluster; it came in from Nahuatl through Spanish. Those words do not
get thrown out — they get their own row and a reason. See *scope*, below.

---

## Deciding who is on the page

Three buckets, always named out loud:

- **made by the rule** — the core. The event produced these.
- **looks the same, different cause** — borrowings, later words, coincidences.
- **the control** — a word the rule should have hit and did not, or a word that
  shows the rule by *not* having happened. `sol` kept its `l` because the `l` was
  not between two vowels. One control word is worth a paragraph of explanation.

A word can also be present for a **support** reason: `estar` is on the `ser`
layer not because it is suppletive, but because you cannot use `ser` without
knowing where `estar` stops.

Every word on the page gets one line saying which bucket it is in. If you cannot
write that line, the word does not go on.

---

## The spine of a layer page

Same skeleton every time, because the reader learns the skeleton once:

1. **The arrow.** The event, in three symbols, before any prose.
2. **The term box.** Define the one or two terms the page needs — *sound law*,
   *nasal vowel*, *between two vowels*. First use, then never again.
3. **Three specimens.** The clearest three words, full-size, with their Latin.
   These are the ones the reader should remember by the end.
4. **Scope.** Who is on the page and why (the buckets above).
5. **The word tables.** All qualifying cards, split into small tables by
   sub-pattern, each row with gloss, source, sentence, level.
6. **The fork.** Almost every layer has one: the same input went to different
   outputs. `pl-` went to `ch-` in spoken words, stayed `pl-` in book words,
   became `pr-` in a few. Draw the fork; then a table per branch.
7. **The evidence.** The one surprising claim, printed as raw data instead of
   asserted. Latin singular / Latin plural stacked, so the reader sees the merge
   themselves.
8. **Minimal pairs.** Two words that differ only by the thing the page is about.
   `mão / mãos` vs `cão / cães`. This is where the layer becomes usable.
9. **Deck defects.** Anything the layer exposed as wrong in the deck itself,
   visible, with the suggested fix.
10. **Footer.** What the colours mean here, what is an estimate, what is disputed.

Steps 6 and 8 are what make a layer a layer instead of a list. If a layer has no
fork and no minimal pair, it is probably a vocabulary group, not a sound law.

---

## Rules of evidence

- **Follow one word all the way.** Latin → what changed → modern form. Do not
  jump from Latin to Portuguese with a tag like *swallowed*.
- **Where the plural remembers, use the plural.** Portuguese singular endings
  merged; the plurals did not. `-ães / -ãos / -ões` is a fossil of three
  different Latin endings. Same trick works anywhere the language kept a second
  form: verb stems, feminines, diminutives.
- **Prefer a cross-check the reader already owns.** English "I have *been* to
  Lisbon" ≈ "I *went* to Lisbon" makes suppletion obvious with no Latin at all.
- **Disputed stays disputed.** If two sources disagree on an origin, say both and
  mark it. Never flatten it into a clean arrow.
- **Never invent a card.** Every claim about the deck is checked against the yaml
  before it is written. Phrase cards are not word cards; a word that appears only
  inside a phrase is not a lemma on the page. This has already caused two wrong
  claims — check first.
- **Card numbers are no longer used.** As of 2026-08 the author dropped them:
  do not add a new `card NNNN` to any page, and do not verify or re-check the
  ones already printed. Numbers already on a page stay exactly as they are —
  removing them is not the job either. What still matters is the claim *around*
  the number: whether the word is in the deck at all, and whether a quoted
  sentence is really that card's own text.

  The rule this replaces was "never write a card number from memory", and it
  earned its place: on layer 07 six of eight numbers written from memory pointed
  at the wrong card, and one named a word the deck does not contain. That failure
  mode is now avoided by not writing numbers at all. For a new row, tag it
  `no card` if the deck lacks the word, and otherwise just name the word.

---

## Levels

Every word, form and section gets a CEFR flag, and every section gets a one-line
verdict on whether to read it today.

The deck stores no level, so the flag is an estimate from two things: how often
the word turns up in everyday European Portuguese, and where it lands in an
A1–B1 course. For tenses, the order a course teaches them.

Purpose of the flag is **skipping**, not gatekeeping. A page whose words are all
B2 is a correct page and a bad afternoon. Say in the footer that the flags are
estimates, and that a word which feels easy should be learned regardless of what
it says.

---

## Register

The reader is spending their effort on Portuguese. English must cost nothing.

- A2 English maximum. Ten to fifteen words a sentence, one idea each.
- Latin, tense names, macrons and root notation are the *material* — they are
  never simplified.
- No metaphor unless the metaphor is the fact (*sit* vs *stand* really is what
  `sedēre` and `stāre` mean).
- Do not explain to the reader why they were confused.
- Headings are labels: "Where every tense comes from", not "Two verbs, five
  ancestors".

---

## Before a layer is finished

- Every word has a sentence, and deck sentences are preferred and cited by card
  number. Invented sentences are marked, and use only deck vocabulary.
- Every count on the page is recounted against the tables. Counts drift during
  editing; they have been wrong three times.
- Every list of forms shows what varies across it — pronouns for verbs, gender
  and plural for nouns.
- The scope block and the tables agree.
- One surprising claim per page carries printed evidence.
- The layer names at least one thing the deck should change.

---

## Five review passes, run one after another

A finished draft is not a finished layer. Every layer goes through **five review
passes, strictly sequentially** — each reads the file as it stands after the
previous one, and edits it in place. Never run two at once: they edit the same
file, and a reviewer that cannot see the previous fix will undo it.

**Every pass gets the identical prompt.** Do not split the job — not
"pass 1 checks the numbers, pass 2 checks the rules". Splitting guarantees
misses, because defects live exactly on the seam between two reviewers: a
counter who is not allowed to question an etymology will happily recount a wrong
bucket and report it as correct, and a prose reviewer told to leave facts alone
will smooth the wording of a false claim. Every pass checks **everything** and
fixes **everything** it finds.

Five identical passes are not waste. Each one starts from a cleaner file and
finds what the previous one was too busy to see. The list below is what every
pass runs through, top to bottom.

**The Portuguese itself — check this first, every time.** The reader is learning
this language from these pages. A wrong sentence here teaches a mistake, and no
amount of correct etymology makes up for it. Every Portuguese sentence on the
page must be:

- **grammatical** — agreement of gender and number, correct verb form for the
  person and tense, correct preposition, correct use and contraction of articles
  (`a` + `a` = `à`, `de` + `o` = `do`, `em` + `a` = `na`);
- **European Portuguese, not Brazilian** — `tu` and the EP verb forms, `estou a
  fazer` and not `estou fazendo`, clitic pronouns after the verb in a plain
  statement (`chamo-me`, not `me chamo`), EP vocabulary (`autocarro`, `comboio`,
  `pequeno-almoço`, `casa de banho`, `telemóvel`);
- **natural** — a sentence no native speaker would say is wrong even when every
  word parses. Read it aloud. If it sounds like a translation, rewrite it.

Deck sentences are copied exactly and are not the reviewer's to change; if one
looks wrong, report it as a deck defect. Sentences written for the page carry the
dashed `new` tag and are entirely the book's responsibility — check those hardest,
and check that they use only vocabulary the deck already has.

**Facts and the deck.** Is every etymology defensible? Does every quoted sentence
match the card's own text? Are the `new` sentences genuinely absent from the deck,
and built only from deck vocabulary? Is every row tagged `no card` really missing
from the deck, and every untagged row really present? Card numbers themselves are
not checked any more — see the rule above. Contested etymologies carry a visible *sources
disagree* mark rather than being stated flatly. Every word sits in the bucket its
history actually puts it in — a wrong bucket has turned up on every layer so far.

**Numbers.** Recount everything from the rendered page: totals, bucket counts,
level splits, per-section topic counts, stats row, hero line, footer summary, the
number of rows actually marked disputed. They must agree with each other, with
the tables, and with the deck. Counts drift during editing; this is the most
common defect by a wide margin.

**The rules.** `artifact-rules.md`, one rule at a time. Nothing gated behind
hover or a click. Every word and form has a sentence. One job per table. Join
keys shown. Scope block naming why each item qualifies — including a bucket for
anything printed only for contrast. Evidence printed, not asserted. Level flags
on words, sections and the hero. Headings that are labels, not essay titles.

**Language and teaching.** A2 English: short sentences, one idea each, plain
words, every non-obvious term defined in a term box the first time it appears.
Then the harder half. Does the order build, or does a section arrive before the
thing it depends on? Is there a sentence a learner would read twice? Is the
surprising fact given room, or buried between two reference tables? Would the
page reward a second visit?

**Design, print and colour.** Print to real A4 and read every page. Both themes,
and the un-stamped system default as well as the two explicit stamps. Contrast
against both surfaces. Deuteranopia, protanopia, tritanopia — and colour is never
the only channel. Narrow screens, no sideways scroll. Then the check that keeps
catching things: does any colour *lie* — is a role colour painted on something
that role did not produce?

Each pass reports what it fixed, what it verified, and what it left alone. Only
a genuine judgement call — one where two defensible answers change the page —
goes back to the author instead of being fixed.

---

## Layers already done

| # | event | why it earned a page |
|---|-------|----------------------|
| 01 | `pl- cl- fl-` → `ch-` | 13 cards, a clean fork into spoken / borrowed / book words |
| 02 | `-n- -l-` deleted, `-ão` merge | 17 nouns, and the plural still remembers three Latin endings |
| 03 | `ser` · `ir` suppletion | two of the highest-frequency verbs, five Latin ancestors |
| 04 | `lh` · `nh` built from nothing | 44 cards, the largest set; four builders, and it closes layers 01 and 02 |

## Planned: layers 08–12

Scoped against the deck, not guessed. Each passes the test at the top of this
file — one arrow, enough cards, a real fork, a minimal pair.

**08 — the three conjugations.** Latin had four (`-āre`, `-ēre`, `-ĕre`, `-īre`);
Portuguese has three. 168 verbs in the deck: 91 `-ar`, 50 `-er`, 25 `-ir`, and
`pôr`. The arrow is `4 → 3`: the two `-ere` classes merged. The fork is which one
a verb came from, which is what explains its stress and its irregularities.
The minimal pair is `beber` ← `bibĕre` against `dever` ← `dēbēre` — both `-er`
now, different classes then. And `pôr` is the leftover: the only Portuguese verb
in none of the three, because `pōnĕre` contracted. That ties straight back to
layer 03.

**09 — Greek, through Latin, into Portuguese.** `farmácia`, `arqueologia`,
`matemática`, `hipótese`, `história`, `teoria`, `símbolo`, `poesia`, `mistério`,
`cinema`, `escola`, `biólogo`, `fotografia`, `problema`. The fingerprints are
spelling: `ph → f`, `th → t`, `y → i`. The fork is bookish borrowings against
the few that came through spoken Latin — `escola` took the prosthetic `e` of
layer 05, `farmácia` did not. The payoff is grammatical: Greek neuter `-ma`
nouns are **masculine** in Portuguese despite the `-a`, so `o problema`,
`o cinema`, `o sistema`.

**10 — the endings English shares.** `-ção`/`-tion`, `-dade`/`-ty`,
`-oso`/`-ous`, `-vel`/`-ble`, `-ura`/`-ure`, `-ista`/`-ist`. About 30 cards
between them. Not a sound law but a reading tool: it turns a large part of the
English abstract vocabulary into guessable Portuguese. Each ending needs its own
small table and its own Latin source.

**11 — doublets: one Latin word, two arrivals.** The capstone. `olho`/`óculos`,
`direito`/`direto`, `estreito`/`restrito`, `feito`/`facto`, `teto`/`teito`,
`praia`/`prato`. One came through speech and wore down; one was lifted from a
book and did not. This is the page that makes layers 01–10 add up, and it is the
answer to *essay vs reference* in the open list below.

**12 — the numbers.** A1-dense and 30 cards. `quīnque` → `cinco` is a real sound
law worth its own row, `octō` → `oito` is already on layer 06, and the whole set
anchors to English and Russian through the oldest words in the language.

**Rejected after checking the deck:** Arabic loans. Portuguese has around a
thousand, but this deck has four — `azul`, `almoço`, `laranja`, `alugar`. A page
needs about ten. `alto`, `arte`, `aluno` and `arco` look Arabic and are not.

## Other candidates not yet built

Judge each by the same test — one arrow, ~10+ cards, a fork, a minimal pair.
Counts are from the deck as it stands.

- **`s-` → `es-`**, the extra e — 24 cards, very A1-heavy. Fork is real:
  `escola`, `escrever`, `estrela`, `estar` got a new `e`, while `escolher`,
  `esconder`, `esquecer`, `estender`, `escuro` only look the same because they
  swallowed an `ex-` or `abs-` prefix. Minimal pair `estar` / `estender`.
  Control: `sol`, `sopa` start with s + vowel and never got an e. Gives the
  reader a rule that works on words the deck does not have: drop the `e-` and the
  English word often appears.
- **`-ct-` / `-lt-` → `-it-`** — 12 cards (`oito`, `oitenta`, `dezoito`,
  `noite`, `direita`, `deitado`, `aceitar`, `receita`, `fato`, `muito`). Fork:
  spoken `oito` against bookish `outubro`, both from `octō-`.
- **`-eiro` / `-eira`** ← `-ārium` — agent nouns against place and container
  nouns. Note `dinheiro`'s `nh` is **not** from this ending's yod — that account
  was wrong and was corrected on layer 04; it is the returning nasal of
  `dēnārium → dĩeiro → dinheiro`, the same road as `vinho`.
- **doublets** — one Latin word arriving twice, once spoken and once from books.
  `olho` / `óculos` is already used on layer 04; find the rest first.
- **initial `f-` kept where Spanish lost it** — 27 cards, but it fails the test:
  no fork, and the evidence needs a Spanish reader.
