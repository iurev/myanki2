# Tesouro audio cutting and validation

## Honest guarantee

No ASR or forced-aligner can give a mathematical 100% guarantee on natural speech. A model can be confident and wrong. The safe guarantee is operational:

> The pipeline never uploads or unsuspends a clip unless independent systems agree and every hard check passes. Ambiguous clips fail closed.

This removes the need to listen to every accepted clip. It does not pretend that one model is infallible.

## Why the old method failed

The old cutter used one Whisper timestamp stream to choose boundaries. Sound effects and long pauses caused isolated words to attach to the wrong sentence. The first review pass then gave an audio model the expected sentence. That prompt biased the model toward confirming expected content.

Known examples:

- `ts0149` and `ts0150` included “E aí” from nearby audio.
- `ts0200` included the spoken chapter number “7”.
- `ts0152` ended with no measured tail margin.

The old validator still called these good. Do not use expected-text prompting as the main validation method.

## Whole-book pipeline

### 1. Generate boundaries with transcript-constrained forced alignment

Use Montreal Forced Aligner with a European Portuguese acoustic model and pronunciation data. Run `mfa validate` first with transcription testing. Reject OOV words, unaligned utterances, and large phone-duration deviations.

Do not generate final cuts from raw Whisper timestamps alone. Keep at least two boundary estimates, such as MFA and a word-timestamp ASR. If their first- or last-word boundaries differ by more than 100 ms, mark the clip ambiguous. Never constrain a boundary from one isolated token. The next sentence boundary needs a contiguous multi-word match or confirmation from a second ASR; this prevents a hallucinated token followed by a long gap from clipping the prior sentence.

### 2. Cut from the chapter source

Cut from the original chapter file, not from an already compressed clip. Leave about 200 ms before and after speech when the neighboring sentence permits it. Never cross the next or previous sentence’s speech boundary. A short real gap can force a smaller margin.

Save source chapter, start, end, duration, and boundary evidence in a manifest.

### 3. Validate without revealing the expected answer

Run at least two unrelated ASR providers on every cut with audio only:

1. OpenAI Whisper Large v3 with word timestamps.
2. Google Chirp 3 as an independent transcript.
3. Use Deepgram Nova 3 for timestamps when Whisper returns impossible timestamps beyond the decoded file duration.

Do not put the expected sentence in any ASR prompt.

### 4. Apply hard acceptance gates

A clip passes only when all checks below pass:

- `ffprobe` decodes the file and its duration matches the manifest within 30 ms.
- Chirp’s normalized transcript exactly matches the canonical sentence. Normalize punctuation, case, and number spelling only.
- Whisper similarity is at least 0.75.
- Whisper has no inserted words at the start or end. These insertions detect neighboring speech.
- There are no missing canonical words unless another independent ASR is exact and the mismatch is a documented ASR substitution.
- Speech starts at least 75 ms after the file starts.
- Speech ends at least 150 ms before the file ends. This larger tail protects nasal vowels and other low-energy endings that timestamp models often shorten.
- If a timestamp provider reports words beyond the file duration, reject those timestamps and require exact Deepgram content plus valid Deepgram edge margins.
- Any missing result, provider disagreement, invalid timestamp, or API error fails the clip.

Run the local gate with:

```bash
python tools/tesouro_validate_cuts.py PATH_TO_PACKAGE
```

Exit code 0 means every clip in that package passed. Any other exit code blocks upload.

### 5. Calibrate with deliberately bad cuts

Before a whole-book run, test the validator against known failures:

- prepend speech from the previous sentence;
- append speech from the next sentence;
- clip the first word;
- clip the last word;
- include the chapter title;
- end exactly on the last detected word.

The validator must reject every mutation. The current validator was tested against the rejected first package and caught `ts0149`, `ts0150`, `ts0200`, and the zero-tail `ts0152`.

### 6. Fail closed before Anki

The upload step must depend on a successful validator exit code. It must then query AnkiConnect again and upload only the exact manifest IDs. Only after media upload and field verification may those exact cards be unsuspended.

Never upload an entire directory by filename pattern. Never unsuspend the whole deck.

## Evidence to retain

For each run, keep:

- cut manifest;
- both unprompted ASR responses;
- fallback timestamp response, if used;
- validator output;
- SHA-256 hashes;
- Anki card IDs and pre-upload suspension state;
- total API cost.

These artifacts make the result reproducible and auditable without listening to every accepted clip.

## Research basis

- MFA validation checks OOVs, unreadable audio, unaligned files, transcription deviations, and alignment-quality metrics.
- MFA alignment analysis recommends speech likelihood, phone-duration deviation, short-phone runs, intensity deviation, and SNR rather than trusting one global likelihood.
- Boundary-ensemble research uses median consensus to reduce outlier alignments, while warning that confident systems can still be wrong.
- Speech dataset quality research combines forced alignment, independent ASR WER/CER, CTC/acoustic checks, VAD, and signal checks.
- Timestamp-curation research treats insertions as evidence of extra speech and deletions as evidence of missing speech.

## Final state (all 30 chapters)

| Step | Tool | Result |
| --- | --- | --- |
| Inventory from the EPUB | `tools/tesouro_build_full_inventory.py` | 773 records, ts0001-ts0773, chapters 1-30 |
| Cut chapters 11-30 | `tools/tesouro_align_api.py` | 461 clips, 0 unmatched sentences |
| Validate Portuguese | `tools/tesouro_validate_cuts.py` | 461/461 pass content and edge gates |
| Verify a failed clip | `tools/tesouro_probe_missing_words.py` | locates the sentence in a window of the source recording |
| Transcribe English | `tools/tesouro_en_tts_api.py` | 773 clips, voice Algieba |
| Verify English | `tools/tesouro_en_verify_api.py` | 773/773 pass with Whisper and Chirp |
| Assemble the deck | `tools/tesouro_package_full_book.py` | 773 PT + 773 EN clips, 1546/1546 hashes |
| Update Anki | `tools/tesouro_anki_upload.py` | 312 cards updated, 461 added |
| Read Anki back | `tools/tesouro_anki_verify.py` | 773 notes, every served file matches its clip byte for byte |

Chapters 1-10 are not regenerated. Their Portuguese audio is read back out of
Anki and compared against the file that ships, so the package cannot silently
replace a live take. `tesouro/full-book-local/ch01-10-anki-live-sha256.json`
holds those hashes as they were served.

### Where a clip had to be settled by hand

Some clips fail an automated content check without being wrong. The
transcribers garble a name or drop a quiet word, and that looks exactly like a
clip cut through the word. Every such clip was settled against the recording
itself and recorded rather than waved through:

- `tesouro/full-book-local/boundary-overrides.json` — cut points measured from
  the recording's energy envelope when the chapter-level word times put the cut
  inside the sentence (`ts0437`, `ts0705`, `ts0528`, `ts0532`).
- `tesouro/full-book-local/content-exceptions.json` — Portuguese clips whose
  sentence was located inside the clip in a window transcription.
- `tesouro/full-book-local/english-exceptions.json` — English clips where both
  providers mishear one word (`João` as `Joel`; a lone leading `But`; `tea` as
  the letter `t`).

An exception is not a pass on trust: the check still has to hear most of the
sentence in the clip, so a blank, truncated or foreign clip cannot ride on one.

### Card shape

- Front: `[sound:tesouro_audio_ch{NN}_{id}.mp3]` — Portuguese audio only.
- Back: `[sound:tesouro_en_{id}.mp3]`, then the Portuguese text, then the
  English text exactly as the book prints it, parentheses and quotation marks
  included (`Maybe some (a) tea?”`).

Portuguese and English stay in separate files. The earlier combined
Portuguese+English clips are no longer referenced by any card; the files
themselves were left in the media collection untouched.
