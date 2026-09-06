# Tesouro Submerso listening deck

Proof of concept for sentence-level listening cards from chapter 1.

Each card has **audio only on the front** and the Portuguese transcript + English translation on the back. The source chapter is already split separately, so the alignment manifest stores sentence timestamps relative to that chapter MP3.

`ch01-alignment.yaml` is the reproducible source of the cuts. To regenerate the clips locally:

```bash
python3 tools/cut_tesouro_audio.py \
  Storyglot-O_Tesouro_Submerso_chpt1.mp3 \
  tesouro/ch01-alignment.yaml \
  --output tesouro/audio/ch01
```

The first pass excludes the spoken title/chapter/section labels and keeps 15 story sentences/utterances.
