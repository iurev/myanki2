# Tesouro Submerso listening deck

Sentence-level listening cards for chapters **1–10** of *O Tesouro Submerso*.

The deck currently contains **312 cards** (`ts0001`–`ts0312`). Each card has:

- **front:** Portuguese audio only
- **back:** Portuguese transcript + English translation from the bilingual EPUB
- tags for `tesouro`, `listening`, and the source chapter

The generated audio clips are intentionally **not stored in this public repository**. Keep the source/derived audio privately (for example in Google Drive), then place or generate the clips locally before syncing them to Anki.

## Files

- `../tesouro-listening.yaml` — the generated Anki deck configuration
- `alignment-ch01-10.csv` — canonical chapter-relative timestamps and Portuguese text for all 312 clips
- `translation-report.csv` — mapping validation for chapters 1–10
- `../tools/build_tesouro_listening.py` — regenerates English backs from the bilingual EPUB chapter files
- `../tools/cut_tesouro_audio.py` — cuts a chapter MP3 using the aggregate alignment CSV

## Regenerate the deck YAML

```bash
python3 tools/build_tesouro_listening.py
```

The generator validates that every aligned Portuguese card maps to an English translation from the book before writing `tesouro-listening.yaml`.

## Regenerate audio clips

For each source chapter MP3, run the cutter with the corresponding chapter number. For example:

```bash
python3 tools/cut_tesouro_audio.py \
  Storyglot-O_Tesouro_Submerso_chpt4.mp3 \
  --chapter 4
```

That writes chapter 4 clips to:

```text
tesouro/audio/ch04/ts0066.mp3
...
tesouro/audio/ch04/ts0115.mp3
```

Repeat for chapters 1–10. The output paths match the `audio:` fields in `tesouro-listening.yaml`.

If you already have the prepared private `tesouro-listening-ch01-10.zip`, extract it at the repository root so that `tesouro/audio/ch01/...` through `tesouro/audio/ch10/...` exist.

## Sync to Anki

Once the audio clips are present locally:

```bash
python3 sync.py tesouro-listening.yaml
```

`sync.py` uploads the clips to Anki media through AnkiConnect. Anki/AnkiWeb then handles media synchronization to the other devices.

## Validation

The current chapters 1–10 build has:

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

Spoken title/chapter/section labels are excluded from the listening cards.
