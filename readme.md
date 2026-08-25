---
permalink: /readme.html
---

# myanki2

Portuguese vocabulary → Anki, driven from plain-text word lists and synced over
[AnkiConnect](https://foosoft.net/projects/anki-connect/) (port 8765).

## Deck

One deck, `words` (724 notes), fed from the book glossary by category. `id` is a
single global sequence (the `word` field stays unique, so Anki never sees a
duplicate first field):

| source            | ids         | notes | content                              |
|-------------------|-------------|-------|--------------------------------------|
| `verbs.yaml`      | 0001-0185   | 185   | verbs (`verbs.md`)                   |
| `nouns.yaml`      | 0186-0468   | 283   | nouns (`nouns.md`)                   |
| `adjectives.yaml` | 0469-0570   | 102   | adjectives + colors (`adjectives.md`)|
| `location.yaml`   | 0571-0589   | 19    | place prepositions (`location.md`)   |
| `numbers.yaml`    | 0590-0619   | 30    | numbers 1-20, tens, +rule            |
| `phrases.yaml`    | 0620-0724   | 105   | time words + useful phrases          |

All cards use the `words` note type: fields `id, word, front, back, chapter`.
Verbs/nouns/adjectives/location are cloze sentences (front blanks the word with
its English gloss); numbers are digit→word; phrases are English→Portuguese.
Each `build_*.py` writes its yaml from the matching `.md`; `sync.py <file>.yaml`
pushes it. Keep the id ranges above non-overlapping when adding a category.

## Card design

- **front** – a Portuguese example sentence with the target word blanked out by
  its English gloss in `{{...}}` (plain field text, not an Anki template).
- **back** – the real sentence + English translation. Example sentences taken
  from the book are tagged `(ch.N)`; simple A0/A1 sentences written for words the
  book doesn't cover are tagged `(A1)`. A card may carry several examples.

```
front:  Eu {{to like}} de desenhar.
back:   Eu gosto de desenhar.
        I like to draw.  (ch.7)

        Eu gosto de café.
        I like coffee.  (A1)
```

## Files

- `verbs.md`, `nouns.md` – the source word lists (`lemma: gloss`).
- `verbs.yaml`, `nouns.yaml` – the curated card data (source of truth).
- `sync.py` – one-way sync yaml → Anki. Upserts by the `id` field, so it never
  duplicates and edits in the yaml win. `python3 sync.py verbs.yaml`.
- `extract_pairs.py` – pulls clean PT/EN sentence pairs out of `extracted/` (the
  unzipped book) so example sentences can be sourced from real text.
- `build_cards.py` – seeds verb cards by matching each verb to a book sentence
  (stem + English-gloss cross-check + irregular-form table). Output was then
  reviewed by hand; bad/missing matches were rewritten as A1 sentences.
- `build_nouns.py` – generates noun cards with section-aware, gender-correct A1
  frames (Animals→"Eu vejo o X", Food→"Eu gosto de X", Family→"A minha X está em
  casa", Occupations→"Ele é X", Transport→"Eu vou de X", …).

## Usage

```sh
# Anki must be running with AnkiConnect on :8765
python3 sync.py verbs.yaml
python3 sync.py nouns.yaml
```

Editing a card: change `verbs.yaml`/`nouns.yaml` and re-run `sync.py`. New cards
can be added with a blank `id:` — sync.py assigns the next number and rewrites
the file.

## Syncing to AnkiWeb

Changing the note type / fields bumps the collection schema, so the next AnkiWeb
sync is a **full sync**. AnkiConnect can't pick a direction, so do it from the
desktop client: Sync → *Upload to AnkiWeb*. (Never open the same profile in two
Anki instances at once.)
