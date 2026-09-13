#!/usr/bin/env python3
"""Third-opinion judge for clips flagged by tesouro_verify.py's text-similarity
check. Whisper's own re-transcription already independently confirms most
clips; this only runs on the handful that disagree, asking a cheap OpenRouter
model whether the mismatch is a harmless ASR quirk (isolated-clip context
loss, punctuation, capitalization) or a real cut/content problem.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

MODEL = "openai/gpt-4o-mini"


def judge(expected: str, heard: str) -> dict:
    api_key = os.environ["OPENROUTER_API_KEY"]
    prompt = (
        "You are auditing an automated audio-clip cutter for a European Portuguese "
        "listening deck. A sentence-level audio clip was cut from a longer narration "
        "and independently re-transcribed by Whisper.\n\n"
        f"Expected (ground-truth) sentence: {expected!r}\n"
        f"Whisper's re-transcription of the cut clip: {heard!r}\n\n"
        "Judge whether this mismatch is (a) a harmless ASR/transcription quirk "
        "(e.g. Whisper mishearing a word without sentence context, punctuation, "
        "capitalization) with the clip's actual audio content still correct, or "
        "(b) a real problem (the clip is truncated, cut wrong, missing/extra words, "
        "or contains a different sentence).\n\n"
        'Reply with strict JSON only: {"verdict": "ok"|"real_problem", "reason": "<one sentence>"}'
    )
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
    ).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    content = resp["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()
    return json.loads(content)


if __name__ == "__main__":
    expected, heard = sys.argv[1], sys.argv[2]
    print(judge(expected, heard))
