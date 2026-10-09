# The `words2` deck

One card per word the twelve chapters of *A Cidadela Misteriosa* teach: 396 notes, 395
from the chapter specs plus `andar` from the pilot spec, in the note type `words2`.

Each card shows a word, its English sentence, and plays one recording of both:

```
Front:  English                                     <- the glossary word, e.g. "noise"
        the example sentence, in italics            <- e.g. "The NOISE woke the whole house."
        [sound:w2_ruido_merged.mp3]                 <- the word, then the sentence, spoken

Back:   the front, then Portuguese, the Portuguese word,
        the letter-by-letter clips, the animal clips,
        the book's own sentence and its chapter
```

## One clip on the front, not two

The note type has ten fields and one card. Five of the fields name a clip:

| Field | Clip |
| --- | --- |
| `SentenceAudio` | `w2_<word>_merged.mp3` — the word, then the sentence. **This is what the front plays.** |
| `EnglishAudio` | empty. It used to hold `w2_<word>_en.mp3`. |
| `PortugueseAudio` | `w2_<word>_pt.mp3` |
| `LettersAudio` | `w2_<word>_letters.mp3` |
| `AnimalsAudio` | `w2_<word>_animals.mp3` |
| `EnglishSentence` | text, not a clip: the example sentence the merged recording speaks. **Shown on the front, under the word.** |

The front used to play two separate recordings and left a gap where a card should have
one thing to listen to. Now the word and its example sentence are joined into a single
clip at the start of the word, and the front names only that clip — so the pair cannot
be heard twice, and nothing shows `EnglishAudio` on either side of the card.

The two halves were not thrown away. `w2_<word>_en.mp3` and `w2_<word>_sent.mp3` are
still in `cidadela/audio2/`, still hashed in `cidadela/work/words2-merge-state.json`,
and no field names them: **a field that names a clip is a field that plays it.**

The merge was made without re-encoding a second time where it mattered: both halves are
decoded to PCM, joined, and encoded **once** (`-c:a libmp3lame -b:a 256k -ac 1 -ar
48000`). A plain `-c copy` was tried first and refused — the second file's timestamps
collide with the first's, and ffmpeg warns `non monotonically increasing dts`. 256k
mono was chosen by sweep: it stays −62 dB under the sources where 224k loses −34 dB.

`tools/words2_merge_audio.py` builds them and checks them. It fails closed unless the
merged clip's aligned error against its two sources is better than −45 dB and its
length is within 5 ms of their sum, and it carries a `--self-test` that joins a wrong
pair to prove the check can reject one. Across the deck the error runs −50.9 to −67.2 dB
and the join inherits a natural 0.10–0.80 s pause (median 0.50 s) — the word's clip ends
in a little room tone and the sentence's begins with a little more.

Twelve merged clips were read back to a blind ear (Whisper, two providers): all twelve
read the word and then the sentence, including the tightest join at 0.10 s. The log is
`cidadela/work/words2-merge-check.log`.

## The word "noise" was 79 seconds of music

Building the merge found a defect that had been in the deck all along. `ruído`'s
English clip, `w2_ruido_en.mp3`, was **79.48 seconds long and contained no speech at
all** — Whisper heard "Oh.", "OOF" and the Japanese for "music" in it. The voice had
been asked for the bare word `noise`, treated it as a sound effect, and sent back
music; nothing in the pipeline compared a clip's length with what it was supposed to be,
so it stayed.

It is very good at making that mistake. Seven takes came back as: a 79-second music
file, laughter ("Oh, ho, ho, ho"), `*cough*`, "Thank you.", "Sigh. Sigh.", "Ahem.
Ahem.", "Hmm.", "Whew." and "Mm-hmm." Capitalised with a full stop — `Noise.` — was read
as "Mm-hmm" too. Respelled **`Noyze.`**, the same voice reads the word, and the ear
hears back `noise`. So `tools/words2_audio.py` now has `EN_SAID_AS = {"noise": "Noyze."}`
beside the Portuguese `SENT_AS`, and a clip records both the `speech` the card shows and
the `say` the voice was given.

Word clips run 0.52–1.92 s and sentence clips 2.08–4.96 s across the deck, so
`source_problems()` now refuses a source clip outside 0.30–6 s (word) or 1–12 s
(sentence). A length is cheap and cannot be talked round by a plausible transcript.

## Rebuilding

```sh
python3 tools/words2_merge_audio.py                     # build; skips what has not changed
python3 tools/words2_merge_audio.py --verify            # check, build nothing
for n in $(seq 1 12); do                                # upload and update the notes
  python3 tools/words2_anki.py --spec cidadela/work/words2-spec-ch$n.json
done
```

Run the chapter specs **in order 1 to 12** and **do not run `words2-spec-pilot.json`**:
a word can appear in several chapters and the last spec to run owns the note's sentence
and chapter, so the pilot — which predates them — would blank the book sentence and
chapter of `maçã`, `poção`, `bruxa` and `ogre`.

`andar`, the one word no chapter spec names, was updated on its own so that its text
fields kept whatever the pilot gave them.

## The English sentence became a field of its own

The front used to play the sentence without showing it: no field held the English sentence,
because `SentenceText` carries the book's own *Portuguese* sentence on the back. Reading a
sentence and hearing it are not the same help, so the deck grew a tenth field,
`EnglishSentence`, holding the exact sentence the merged recording was made from — the same
wording, not a second version of it — and the front now shows it in italics under the word:

```
{{English}}<br>{{#EnglishSentence}}<i>{{EnglishSentence}}</i><br>{{/EnglishSentence}}{{SentenceAudio}}
```

Adding it was a schema change, so it was done once and in the open. `EnglishSentence` is
**last** in the field list only because Anki appends a field and `words2_anki.py` refuses to
reshape a note type whose existing fields are not a prefix of the spec's. All fourteen spec
files were rewritten by `tools/words2_add_english_sentence.py`, which copies each original to
`cidadela/work/backup-english-sentence/` first and hashes every other top-level key before
and after: each spec differs by exactly the five lines of those two keys, and `cards` came
through untouched — the specs are the source of truth for 396 notes, and a rebuild of them
once silently dropped four translations.

The pilot-only word `andar` is owned by specs that predate the book sentence, so re-uploading
one of those wholesale would blank its text side. `--fill-missing` sets the new field on that
note and nothing else.

## What was verified, and by what

`cidadela/work/words2-deck-verification.log` — one command, `tools/words2_verify.py --all`,
which builds the deck's expected state itself (twelve chapters in order, later chapters
winning, pilot words filling gaps) and reads the whole deck back out of Anki:

- 396 notes, one card template, front as above, note type fields exactly the spec's ten;
- every field of every note holds what the spec says, `EnglishSentence` included;
- every clip a field names is served by Anki, byte for byte the same as on disk (1584 clips);
- `PASS: 0 problem(s)`.

The field table above is now ten fields, and `tools/words2_verify.py --self-test` passes all
eleven ways this deck can be wrong — including a wrong example sentence and an empty one.

Two things that check reports rather than hides. It prints that the superseded aggregate
`words2-spec.json` names twelve words the deck does not hold — `certo`, `dar`, `dentro`,
`eles`, `exemplo`, `iluminado`, `longe`, `me`, `medo`, `preso`, `responsavel`, `senhora` —
which are in no other Portuguese deck either. Whether they belong here is a decision, not a
check, so it is left visible. And writing `--all` caught a defect in the check itself:
reading the pilot glob after the chapters re-applied every chapter in alphabetical order, so
chapter 7 beat chapter 11 and 184 differences were invented. Chapters are now read 1 to 12,
then the pilot file, and nothing else.
