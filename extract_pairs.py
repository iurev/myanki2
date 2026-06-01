#!/usr/bin/env python3
"""Extract clean Portuguese/English sentence pairs from the extracted book.

Narrative chapters store each line as:
    <p class="first">PT sentence</p>
    <p class="subsq"><i>EN translation</i></p>

We pair consecutive first/subsq paragraphs and expose a search helper so we can
find good example sentences for a given verb.
"""
import re
import glob
import os
import html

OEBPS = os.path.join(os.path.dirname(__file__), "extracted", "OEBPS")

_TAG = re.compile(r"<[^>]+>")
_PARA = re.compile(r'<p[^>]*class="(first|subsq)"[^>]*>(.*?)</p>', re.DOTALL)
_LI = re.compile(r"<li[^>]*>(.*?)</li>", re.DOTALL)
_ITALIC = re.compile(r"<i>(.*?)</i>", re.DOTALL)
_CHAPNUM = re.compile(r"chapter-(\d+)\.xhtml$")


def _clean(s: str) -> str:
    s = _TAG.sub("", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _chapter(path: str) -> int:
    m = _CHAPNUM.search(path)
    return int(m.group(1)) if m else 0


def pairs():
    """Yield (pt, en, chapter) for clean Portuguese/English pairs.

    Two markup shapes carry parallel translations in this book:
      1. <p class="first">PT</p> followed by <p class="subsq">EN</p>
      2. <li>PT text <i>EN translation</i></li>  (example sentences)
    """
    out = []
    for path in sorted(glob.glob(os.path.join(OEBPS, "upart-002-chapter-*.xhtml"))):
        raw = open(path, encoding="utf-8").read()
        chap = _chapter(path)

        # shape 1: first -> subsq paragraph pairs
        paras = _PARA.findall(raw)
        i = 0
        while i < len(paras) - 1:
            (c1, t1), (c2, t2) = paras[i], paras[i + 1]
            if c1 == "first" and c2 == "subsq":
                pt, en = _clean(t1), _clean(t2)
                if pt and en and "____" not in pt:
                    out.append((pt, en, chap))
                i += 2
            else:
                i += 1

        # shape 2: <li>PT <i>EN</i></li>
        for li in _LI.findall(raw):
            m = _ITALIC.search(li)
            if not m:
                continue
            en = _clean(m.group(1))
            pt = _clean(li[: m.start()])
            if pt and en and "____" not in pt:
                out.append((pt, en, chap))
    return out


def find(regex, limit=8):
    rx = re.compile(regex, re.IGNORECASE)
    hits = [(pt, en, c) for pt, en, c in pairs() if rx.search(pt)]
    return hits[:limit]


if __name__ == "__main__":
    import sys
    pat = sys.argv[1] if len(sys.argv) > 1 else r"\bgost"
    for pt, en, c in find(pat):
        print(f"[ch.{c}]\n  PT: {pt}\n  EN: {en}\n")
