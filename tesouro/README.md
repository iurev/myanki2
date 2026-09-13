# Tesouro Submerso listening deck

Sentence-level listening cards for chapters **1–10** of *O Tesouro Submerso*.

The deck currently contains **312 cards** (`ts0001`–`ts0312`), synced into a
dedicated Anki deck called **`listening`**. Each card has:

- **front:** Portuguese audio only
- **back:** Portuguese transcript + English translation from the bilingual EPUB
- tags for `tesouro`, `listening`, and the source chapter

The generated audio clips are intentionally **not stored in this public
repository** (`tesouro/audio/`, `tesouro/source/`, and `tesouro/whisper-cache/`
are all gitignored). Keep the source chapter MP3s privately, then generate the
clips locally before syncing to Anki.

## Files

- `../tesouro-listening.yaml` — the generated Anki deck configuration (`deck: listening`)
- `alignment-ch01-10.csv` — canonical chapter/text manifest for all 312 clips (the `text` column is the ground truth used for alignment; the old `start`/`end` columns are historical and **not trusted** — see below)
- `translation-report.csv` — mapping validation for chapters 1–10
- `../tools/build_tesouro_listening.py` — regenerates English backs from the bilingual EPUB chapter files
- `../tools/tesouro_align.py` — **current** cutter: transcribes each chapter with Whisper and aligns it against the ground-truth text (see "How the clips are cut" below)
- `../tools/tesouro_verify.py` — independent re-transcription cross-check for every cut clip
- `../tools/tesouro_llm_check.py` — OpenRouter LLM third opinion for clips `tesouro_verify.py` flags
- `../tools/cut_tesouro_audio.py` — **superseded**, kept for history only. This was the original VAD/section-anchor cutter; it produced bad splits (wrong boundaries, clipped words) and should not be used for new work. Use `tesouro_align.py` instead.

## How the clips are cut (and why)

The original cutter (`cut_tesouro_audio.py`) used VAD (voice-activity
detection) plus section anchors to guess sentence boundaries without ever
checking what was actually said. That produced audibly bad splits.

The current pipeline instead:

1. **Transcribes the full chapter MP3 with `faster-whisper` (`large-v3`, GPU),
   word-level timestamps.** Real ASR, not a heuristic — this is what makes
   the timestamps trustworthy in the first place.
2. **Aligns the transcription against the known-correct sentence text**
   (the `text` column in `alignment-ch01-10.csv`) using `difflib.SequenceMatcher`
   over token streams. Only exact (`equal`-opcode) token matches are trusted as
   anchors; a sentence's start/end come from the first/last matched word,
   found by searching outward from the sentence's own token range to the
   nearest trusted anchor.
3. **Pads** each boundary a little into the surrounding silence so words
   aren't clipped, without crossing into a neighboring sentence.
4. **Cuts** the clip with `ffmpeg`.

### Running it

One chapter at a time (deliberately — see "Problems found" below for why
processing a whole book blind is a bad idea):

```bash
# from the repo root, with the audio venv (see below) active
python3 tools/tesouro_align.py 4      # align + cut chapter 4
python3 tools/tesouro_verify.py 4     # independently re-check chapter 4's clips
```

`tesouro_verify.py` re-transcribes each cut clip on its own (giving Whisper
the *previous* sentence's text as `initial_prompt` for narrative context, not
the current one — that would be circular) and flags anything below a 0.97
text-similarity ratio against the ground truth.

For a flagged mismatch, get a second opinion instead of guessing:

```bash
python3 tools/tesouro_llm_check.py "Expected sentence." "What whisper heard."
```

This asks a cheap OpenRouter model (`openai/gpt-4o-mini`) whether the
mismatch is a harmless ASR quirk or a real cut problem. Treat its answer as
one more input, not the final word — see the `ts0080`/`ts0064` cases below
where the LLM's text-only judgment was wrong and had to be overridden with
audio-timestamp evidence.

### Environment

```bash
uv venv .venv-audio --python 3.12
uv pip install --python .venv-audio/bin/python faster-whisper
```

`faster-whisper`'s GPU path needs `libcublas`/`libcudnn` on `LD_LIBRARY_PATH`
if they aren't installed system-wide:

```bash
uv pip install --python .venv-audio/bin/python nvidia-cublas-cu12 nvidia-cudnn-cu12
export LD_LIBRARY_PATH=.venv-audio/lib/python3.12/site-packages/nvidia/cublas/lib:.venv-audio/lib/python3.12/site-packages/nvidia/cudnn/lib
```

`ANKI_CONNECT_URL` overrides AnkiConnect's default `http://localhost:8765`
(useful when something else is squatting that port — see `sync.py`).

## Sync to Anki

Once the clips for a chapter (or all chapters) exist locally, **test one card
first**:

```bash
ANKI_CONNECT_URL=http://localhost:PORT python3 sync.py tesouro-listening.yaml --id ts0001
```

Then check it actually landed right (`notesInfo` via AnkiConnect, or just
look at the card in Anki) before syncing the rest:

```bash
ANKI_CONNECT_URL=http://localhost:PORT python3 sync.py tesouro-listening.yaml
```

`sync.py` uploads the clips into Anki's media collection and upserts notes by
`id`, so re-running it is safe. If you're replacing an entire deck's worth of
bad cards, delete the old notes first (`deleteNotes` via AnkiConnect) rather
than relying on upsert, since content may have shifted.

## Validation

| Chapter | Cards |
| ---: | ---: |
| 1 | 15 |
| 2 | 22 |
| 3 | 28 |
| 4 | 50 |
| 5 | 62 |
| 6 | 22 |
| 7 | 53 |
| 8 | 20 |
| 9 | 27 |
| 10 | 13 |
| **Total** | **312** |

All 312 clips were cut with `tesouro_align.py` and independently verified
with `tesouro_verify.py`. Every flagged mismatch was manually cross-checked
against the full-chapter transcription's word-level confidence (and, where
still ambiguous, an LLM second opinion) before being accepted or fixed.
Spoken title/chapter/section labels are excluded from the listening cards.

## Problems found while building this pipeline

Keeping this here because every one of these is a *class* of bug, not a
one-off, and the next chapter/book will hit them again.

### 1. Hallucinated low-confidence words during silence, matched as if real

Whisper sometimes "hears" a short word (often a common one like "O") during a
genuine pause, with low confidence. Because that word's text is real
Portuguese, naive text-alignment can match it as if it were the sentence's
actual first word, anchoring the cut boundary to the wrong point in time —
by several seconds.

**Symptom:** a card whose duration is wildly long for its word count.

**Fix:** drop words below a confidence threshold before alignment:

```python
CONF_THRESHOLD = 0.45
words = [w for w in transcribe_chapter(chapter) if w.prob >= CONF_THRESHOLD]
```

### 2. Unsafe "replace"-block fallback in the sequence alignment

`difflib.SequenceMatcher`'s `replace` opcode pairs up a span of target tokens
with a span of whisper tokens *positionally*, with no guarantee the text
actually corresponds. This let a target token like `"O"` get silently mapped
to an unrelated whisper token like `"2"` just because they were roughly in
the same place in a messy region — producing a nonsense boundary.

**Fix:** only trust `equal` opcodes as anchors; resolve everything else via
nearest-neighbor search to the closest trusted anchor (never via `replace`
proportional mapping):

```python
target_to_whisper: dict[int, int] = {}
for tag, i1, i2, j1, j2 in opcodes:
    if tag == "equal":
        for offset in range(i2 - i1):
            target_to_whisper[i1 + offset] = j1 + offset
# no 'replace' branch -- anything not exactly matched falls through to
# nearest_whisper_idx(), which only ever returns a trusted equal-anchor.
```

### 3. Hyphenated compounds never match Whisper's un-hyphenated output

`"caravela-portuguesa"` is one token in the ground-truth text, but Whisper
naturally transcribes it as two separate words with a space. The single
hyphenated token then never gets an exact match, and the boundary falls back
to the word *before* it — truncating the compound clean off the clip.

**Fix:** split on hyphens too when tokenizing for matching (only affects
matching, not the actual sentence text used on cards):

```python
toks = [normalize(p) for w in text.split() for p in w.split("-")]
```

### 4. An unstripped ellipsis character silently blocking a match

`"Olhe…"` (with a real ellipsis character, not three periods) never matched
Whisper's `"Olhe!"` because the punctuation-stripping set didn't include `…`.
Losing the match on the sentence's *first* word meant the whole leading word
got excluded from the cut.

**Fix:** add `…` to the stripped punctuation set. Small, easy to miss, real
impact — check your punctuation-stripping set covers every character
actually used in the source text, not just the "obvious" ones.

### 5. Word-initial silent 'h' causing a total match failure

Whisper transcribed `"Hei!"` as `"Ei!"` — a legitimate alternate spelling,
since word-initial `h` is always silent in Portuguese. With no fallback
anchor nearby (it was a single-word sentence), this produced a **complete
unmatched sentence with zero cut clip** — the card would have had no audio
at all.

**Fix:** strip a leading `h` when normalizing, applied identically to both
sides of the comparison so it can only recover false negatives, never cause
a false match:

```python
if len(tok) > 1 and tok[0] == "h":
    tok = tok[1:]
```

### 6. Whisper splitting one word into two tokens

`"Porque é que..."` was transcribed as `"Por"` + `"que"` (two tokens, no
hyphen involved at all) instead of one `"Porque"` token. Same failure shape
as the hyphen issue, but with no punctuation marker to key a general fix off
of — this one needed a manual, audited override:

```python
MANUAL_OVERRIDES: dict[tuple[int, str], tuple[float, float]] = {
    (9, "ts0297"): (117.59, 123.05),  # verified against raw word timestamps
}
```

Keep this list small and always comment *why* — it's a deliberate escape
hatch for genuine one-offs, not a place to paper over an actual pipeline bug.

### 7. VAD silently dropped ~40 seconds of real speech (chapter 10)

`vad_filter=True` gated out an entire ~40-second stretch of real narration in
chapter 10 — six whole sentences vanished from the transcription with zero
error, just silently absent. Re-transcribing the same audio with
`vad_filter=False` recovered every missing sentence correctly.

The twist: **disabling VAD globally then broke chapter 1** a different way —
without VAD, Whisper's long-form decoder drifted/skipped a ~25-second stretch
after an early pause. Neither setting is safe for every chapter.

**Fix:** an explicit per-chapter override, decided by evidence (re-transcribe
both ways, compare), not a blanket setting:

```python
NO_VAD_CHAPTERS = {10}
...
use_vad = chapter not in NO_VAD_CHAPTERS
segments, _info = model.transcribe(str(mp3), language="pt",
                                    word_timestamps=True, vad_filter=use_vad)
```

**Lesson:** always sanity-check *coverage*, not just boundary quality — a
sequence match ratio of `0.000` with several fully "UNMATCHED" sentences in a
row is a red flag for missing transcription, not just misalignment.

### 8. Isolated short clips are genuinely worse at ASR than full-chapter context

This isn't a bug to fix so much as a fact to design around. Re-transcribing
a 1-3 word clip in total isolation (no narrative context) measurably degrades
Whisper's accuracy versus the same words heard in the original full-chapter
pass — e.g. `"Vou, vou."` → `"— Vô, vô."`, `"Ali?"` → `"Oh, e..."`. The
*audio* is correct; only the out-of-context re-transcription is noisy.

**Mitigations, in order of how much they helped:**

1. Give the verification pass the *previous* sentence's ground-truth text as
   `initial_prompt` (real context, not circular — see `tesouro_verify.py`).
   This alone fixed most cases (e.g. `"Está a partir..."` → `"Está partindo."`
   → close enough to trust once combined with full-context confidence).
2. When still flagged, cross-reference the **full-chapter-context
   transcription's word-level confidence** for the exact matched span — this
   is a much stronger signal than a second isolated re-transcription, since it
   has real sentence context. A sentence where all target tokens matched with
   >0.9 average confidence in the original pass is almost certainly fine
   even if the isolated re-check disagrees.
3. Only escalate to the OpenRouter LLM judge for genuinely ambiguous
   remaining cases, and don't treat its verdict as final — it only sees text,
   never audio, so it can't tell "ASR mangled an isolated clip" from "the
   clip is actually wrong". Two examples where the LLM said `"real_problem"`
   but the correct call (confirmed via full-context confidence and, for
   `ts0080`, dialogue logic) was to accept the clip as correct:
   - `ts0026`: `"Antónia!"` heard as `"Antônia"` (European vs Brazilian
     spelling of the same sound — a name transcribed in isolation lost the
     accent convention it correctly used elsewhere in the same chapter).
   - `ts0064`: `"Está partido."` heard as `"Está a partir..."` / `"Está
     partindo."` / `"Está perto."` across three different re-transcription
     attempts — three different wrong guesses is itself evidence of ASR
     noise on a hard 2-word out-of-context utterance, not a consistent
     signal of a real defect.

### 9. A genuine narration/text divergence, not a pipeline bug at all

`ts0080`'s ground-truth text says `"Tem a certeza?"` (interrogative, "Are you
sure?"), but the audiobook narrator's actual delivery blends into something
Whisper consistently heard as `"Tenha certeza."` (imperative). The dialogue
logic (the reply `"Tenho, tenho."` only makes sense as an answer to a
question) supports the ground-truth text being correct and this being a fast/
blended pronunciation, not a script change — but *regardless of which text is
"right"*, the actual acoustic span for the utterance still needed to be
captured in full. This got the same manual-override treatment as case 6.

**Lesson:** when ASR and the reference text disagree, don't assume either one
is automatically right. Check what a *human* would conclude from full
dialogue context, and separately make sure the *audio boundary* is still
correct regardless of which text label you settle on.
