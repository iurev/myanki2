#!/usr/bin/env python3
"""Generate location/movement cards (location.yaml) from location.md.

These are place prepositions/adverbs. They're clozed into a fixed frame,
"O gato está ___ (casa)", with the de+a / a+a contractions resolved so the
sentence is correct. The base dictionary form is shown on the back.

    python3 build_location.py [--yaml]
"""
import sys
import yaml

SRC, OUT, START_ID = "location.md", "location.yaml", 571


def parse():
    rows = []
    for line in open(SRC, encoding="utf-8"):
        s = line.strip()
        if not s or s.startswith("#") or ":" not in s:
            continue
        phrase, gloss = s.split(":", 1)
        rows.append((phrase.strip(), gloss.split(",")[0].strip()))
    return rows


def card(phrase, gloss):
    if phrase == "em":
        pt, en = "O gato está em casa.", "The cat is at home."
        blanked = "em"
    elif phrase.endswith(" de"):                 # de + a (casa) -> da
        blanked = phrase[:-3] + " da"
        pt = f"O gato está {blanked} casa."
        en = f"The cat is {gloss} the house."
    elif phrase.endswith(" a"):                   # a + a (casa) -> à
        blanked = phrase[:-2] + " à"
        pt = f"O gato está {blanked} casa."
        en = f"The cat is {gloss} the house."
    else:                                         # standalone (à direita, em frente…)
        blanked = phrase
        pt = f"O gato está {phrase}."
        en = f"The cat is {gloss}."
    pre = pt.split(blanked)[0]
    suf = pt.split(blanked, 1)[1]
    front = f"{pre}{{{{{gloss}}}}}{suf}"
    back = f"{pt}\n{en}\n({phrase})"
    return front, back


def main():
    rows = parse()
    out = {"deck": "words", "model": "words", "cards": []}
    for i, (phrase, gloss) in enumerate(rows):
        front, back = card(phrase, gloss)
        out["cards"].append(dict(id=f"{START_ID + i:04d}", word=phrase,
                                 front=front, back=back, chapter="—"))
        if "--yaml" not in sys.argv:
            print(f"{front:34} | {back.replace(chr(10),' / ')}")
    print(f"\n{len(rows)} location phrases (ids {START_ID:04d}-{START_ID+len(rows)-1:04d})")
    if "--yaml" in sys.argv:
        yaml.safe_dump(out, open(OUT, "w", encoding="utf-8"),
                       allow_unicode=True, sort_keys=False, width=1000)
        print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
