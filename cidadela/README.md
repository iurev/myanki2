# A Cidadela Misteriosa → the `listening2` deck

501 listening cards for all twelve chapters of *A Cidadela Misteriosa*, each
with the Portuguese sentence cut from the book's own recording and the matching
English sentence spoken by TTS. The deck is live in Anki as `listening2`.

Chapters 1–5 were the first pass (214 cards). Chapters 6–12 added 287 more
through the same pipeline, with the corrections and tool changes recorded below.

## What was in the book

The epub was unzipped into `extracted/`. It is an interlinear reader: `part-001`
holds the Portuguese, `part-002` prints the publisher's English translation
beside it. The audio is one MP3 for the whole book,
`book2/Storyglot-A cidadela misteriosa.mp3` (71:01, 320 kbps stereo). Chapter
files are cut from it with `ffmpeg -c copy`, so each one is a bit-exact copy of
the same stream — proved by decoding a cut and the source to the same MD5.

Boundaries come from the narrator's spoken chapter announcements, recorded per
chapter in `work/chapter-spans.json`. Chapter 12 is listed as "01:09" in the
epub's own table of contents, which is a typo for 69:09 and would cut into
chapter 11's speech, so its start (4184.7 s) was measured from the audio instead:
chapter 11's last word ends at 4183.2 s and chapter 12's title begins at 4188.0 s,
and the printed markers sit about 3.28 s before their chapter's title in the same
kind of pause.

## Pipeline

| stage | tool | result |
| --- | --- | --- |
| unzip and read the book | — | 214 Portuguese sentences in chapters 1–5; English already printed for 208 of them |
| split the audiobook | `cidadela/work/chapter-spans.json` | chapters cut at the narrator's spoken chapter announcements (00:09, 05:04, 11:56, …) into `source/ch01..ch05.mp3` |
| transcribe for alignment | `tools/cidadela_align.py` (its own `transcribe` step) | Deepgram per chapter, cached in `work/asr-deepgram/ch0N.json`; this is the only pass over a whole chapter. The endpoint refuses large inputs, so a bigger chapter would have to be transcribed in pieces; the largest here, chapter 11 at 610 s and 2.9 MB, was accepted whole |
| align and cut | `tools/cidadela_align.py` | `audio/chNN/*.mp3`, one file per sentence |
| fill the missing translations | `tools/cidadela_translate.py` | 4 sentences, `deepseek/deepseek-v4.1-flash` at high reasoning, each checked by `typesafe/jev-router` |
| English speech | `tools/cidadela_en_tts.py` | Gemini flash TTS, voice Algieba, one file per sentence |
| level the English | `tools/cidadela_en_gain.py` | every clip to −24.4 LUFS, the Portuguese narration's own median (English arrived +8.1 dB louder) |
| verify | `tools/cidadela_validate.py`, `tools/cidadela_en_verify.py` | see below |
| upload | `tools/cidadela_anki_upload.py` | deck `listening2` |
| verify the deck | `tools/cidadela_anki_verify.py` | see below |

## Chapters

| chapter | title | cards |
| --- | --- | --- |
| 1 | An envelope and a sword | 42 |
| 2 | No return | 47 |
| 3 | The poisoned apple | 40 |
| 4 | The spider's web | 44 |
| 5 | The potion shop | 41 |
| 6 | The goblin’s garden | 44 |
| 7 | The healer's cave | 59 |
| 8 | The lady in white | 36 |
| 9 | The mirror tent | 38 |
| 10 | The tower without stairs | 27 |
| 11 | The monster with tentacles | 73 |
| 12 | The diamond potion | 10 |

## How the cuts are verified

`cidadela_validate.py` runs free checks over all 501 clips — each clip starts and
ends in silence, no clip contains a word belonging to its neighbour, no word of
the sentence is left out of the clip, and no two clips overlap — then transcribes
a sample with two unprompted providers. `--self-test` feeds the checker a clip of
the wrong sentence and a cut moved 1.5 s late, and fails if either one passes.

* 501 clips pass the free gates.
* 40 sampled clips: both providers agree with the sentence (a few needed the
  second provider because Whisper garbles proper nouns).
* 8 gaps between clips hold audio that is not a word (laughter, a closing
  consonant, an onset, music, and a loud thud in a sentence about falling over).
  Each was transcribed from the recording itself and recorded in
  `work/gap-exceptions.json` with the seconds it is allowed to cover, so the
  exception cannot quietly grow. A gap holding a transcribed word is never
  excepted: that word is cut into the clip that owns it.
* `work/boundary-overrides.json` holds 12 hand cuts. Most extend a clip over its
  own word, which Deepgram's pass left sitting in the gap — "A metamorfose."
  (cm0263), the "Então" that opens cm0315, the drawn-out whispered "David…"
  (cm0324, cm0328), "curiosa." (cm0344), "que veio." (cm0381), the "Uh." that
  opens cm0400, plus the first pass's "Ah!" (cm0100) and "Hei!" (cm0233). Two are
  different kinds: cm0372 carries the thud the sentence is performed with, and
  cm0351 is placed by hand entirely — the one-word scream "— Ahhhhh!" that
  Deepgram never transcribed, so no transcript word could anchor it, and the
  aligner used to drop such a sentence without a clip. Both providers hear it at
  292.84 s, and an override may now supply a row's whole span and both edges
  (`span_start`, `span_end`, `cut_start`, `cut_end`) for a sentence the
  transcript never anchored. Such a row is marked `hand_cut` and kept out of the
  chapter's coverage statistic, which describes the ASR alignment it has none of.
* `cm0502` is the book's printed last line, `FIM`. The narration never says it —
  both providers, given the last 20 s of chapter 12, transcribe the closing
  sentence and nothing after it — so there is no audio to cut and no card. It is
  recorded in `work/not-narrated.json`, which the uploader skips by name.

## How the English is verified

* 469 sentences use the book's own English, byte for byte. 2 more are the same
  edition's English moved back onto the sentence it translates
  (`work/english-reassignments.json`). 31 were translated and are the only text in
  this deck not from the book (`work/english-fills.json`); one of those, `FIM`,
  has no card.
* TTS text is passed through unchanged, parenthetical glosses included.
* 501 clips, transcribed in English by two providers: 499 verbatim or fuzzy-word
  matches, 1 matching once provider word-splitting is normalised ("GUESTHOUSE"
  heard as "guest house"), 1 matching with a parenthetical dropped.
* cm0209 and cm0409 were re-recorded: the expressive TTS model *acted out* lines
  instead of reading them. For "David laughs." it laughed (heard as "Ha ha ha
  ha."), and for "David sighs." it breathed out "David Size." / "David's eyes"
  on six takes in a row. The retake loop keeps a take only when both providers
  hear the sentence — cm0409 was accepted on take 7 — and every rejected take is
  recorded in `english-retakes.json`.
* cm0351's English line is "— Ah!" rather than the screamed "— Ahhhhh!": no
  speech recogniser writes a drawn-out scream that way, so the verifier could
  never confirm the clip. The clip itself still screams; only the printed
  English is short. The Portuguese is untouched, and the change is recorded in
  `work/english-fills.json`.
* The shared English verifier caches one transcript per note id, so a retaken
  clip would be judged on the audio it used to be. `cidadela_en_verify.py` now
  drops the cached transcripts of clips whose pristine copy is newer than the
  cache (the gain stage rewrites every shipped clip, so only the pristine copies
  can tell a retake apart), and prints what it dropped.

## The deck

* Deck `listening2`, note model `listening` (the existing one, unchanged), so the
  cards look and behave like the first listening deck's.
* Front: the chapter, then the Portuguese audio. Back: the English audio, the
  Portuguese sentence, its English, then the chapter again.
* Every entry carries its chapter both in the `chapter` field and on the card,
  and `chapterNN` tags group them.
* Media names are prefixed `cidadela_`, so this deck and `listening` can share one
  Anki media folder without either file shadowing the other's.
* Verified by reading the deck back out of Anki: 501 notes, 501 cards, every
  field equal to the book's text, and all 1002 media files hashed as Anki serves
  them and compared against the files that were cut and verified here — 1002
  matches, every one decoding as audio.
* Anki's own renderer was asked for the first card and returned
  `<i>Chapter 1 — An envelope and a sword</i><br><br>[anki:play:q:0]` on the
  front and `[anki:play:a:0]<br><b>O David vive na capital do reino.</b><br>David
  lives in the capital of the kingdom.<br><br><i>Chapter 1 — An envelope and a
  sword</i>` on the back, with the card still new and unscheduled afterwards.

## Changes made for chapters 6–12

Four tools needed a change, each for a defect the new chapters exposed:

* `cidadela_align.py` — an override may now place a sentence the ASR never
  anchored (see cm0351 above), which the aligner previously skipped outright.
* `cidadela_translate.py` — it rebuilt `work/english-fills.json` from the
  sentences that still needed a translation, so re-running it silently dropped
  earlier fills (it dropped four, recovered from
  `work/text-inventory.before-fills-backup.json`). It now carries existing fills
  over.
* `cidadela_anki_upload.py` — honours `work/not-narrated.json` and skips those
  lines instead of failing the whole build on a record that can never have audio.
* `cidadela_en_verify.py` — drops cached transcripts of retaken clips, which it
  otherwise judged on their old audio.

## Files

* `source/` — the chapter MP3s cut from the single book file
* `audio/chNN/` — the Portuguese clips, the files the deck plays
* `audio-en/`, `audio-en-original/` — the levelled English clips and the raw TTS
* `work/` — the inventory and every decision the run recorded, including
  `not-narrated.json`, `boundary-overrides.json`, `gap-exceptions.json` and
  `english-fills.json`
* `work/english-verify-288.log` — the two-provider result for the 288 new English
  clips, kept as the run's evidence
* `anki-listening2-state.json` — note ids, planned fields and media hashes
* `english-verification.json`, `english-gain.json`, `english-retakes.json` — the
  English stage's records
