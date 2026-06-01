#!/usr/bin/env python3
"""Generate number cards (numbers.yaml).

Simplified set per request: 1–20 individually, then just enough of 21–100 to
teach the formation rule (30, 31, 37) plus the round tens 40–100. The rule is
written on the back so the pattern is memorised, not every number.

    python3 build_numbers.py [--yaml]
"""
import sys
import yaml

OUT, START_ID = "numbers.yaml", 590

# (digit, portuguese, rule-note)
DATA = [
    ("1", "um / uma", ""), ("2", "dois / duas", ""), ("3", "três", ""),
    ("4", "quatro", ""), ("5", "cinco", ""), ("6", "seis", ""),
    ("7", "sete", ""), ("8", "oito", ""), ("9", "nove", ""), ("10", "dez", ""),
    ("11", "onze", ""), ("12", "doze", ""), ("13", "treze", ""),
    ("14", "catorze", ""), ("15", "quinze", ""),
    ("16", "dezasseis", "16–19 = dez + a + unit"),
    ("17", "dezassete", "16–19 = dez + a + unit"),
    ("18", "dezoito", "dez + oito → dezoito"),
    ("19", "dezanove", "dez + a + nove → dezanove"),
    ("20", "vinte", ""),
    ("30", "trinta", ""),
    ("31", "trinta e um", "21–99: tens + e + unit"),
    ("37", "trinta e sete", "21–99: tens + e + unit  (30 + 7)"),
    ("40", "quarenta", "combine: quarenta e um = 41"),
    ("50", "cinquenta", "combine: cinquenta e dois = 52"),
    ("60", "sessenta", ""), ("70", "setenta", ""), ("80", "oitenta", ""),
    ("90", "noventa", ""),
    ("100", "cem", "cem alone; cento e um = 101"),
]


def main():
    out = {"deck": "words", "model": "words", "cards": []}
    for i, (digit, pt, note) in enumerate(DATA):
        back = pt + (f"\n\nrule: {note}" if note else "")
        out["cards"].append(dict(id=f"{START_ID + i:04d}", word=pt,
                                 front=digit, back=back, chapter="—"))
        if "--yaml" not in sys.argv:
            print(f"{digit:>4}  ->  {back.replace(chr(10),' ')}")
    print(f"\n{len(DATA)} numbers (ids {START_ID:04d}-{START_ID+len(DATA)-1:04d})")
    if "--yaml" in sys.argv:
        yaml.safe_dump(out, open(OUT, "w", encoding="utf-8"),
                       allow_unicode=True, sort_keys=False, width=1000)
        print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
