#!/usr/bin/env python3
"""Generate noun cards (nouns.yaml) from nouns.md.

Nouns rarely appear in a natural conjugated context we can grep, so instead each
card gets a short, grammatically-correct A1 sentence built from a section-aware
frame, with the article agreeing with the noun's gender/number. The noun is
blanked with its English gloss for the front, mirroring the verb cards.

    python3 build_nouns.py            # report
    python3 build_nouns.py --yaml     # write nouns.yaml
"""
import re
import sys

import yaml

NOUNS_MD = "nouns.md"
OUT_YAML = "nouns.yaml"
DECK = "words"
START_ID = 186          # ids are one global sequence; verbs take 0001-0185

SECTIONS = {
    "Abstract nouns", "Animals & nature", "Body", "City & services", "Clothing",
    "Family", "Food", "Home", "Objects", "Occupations & relationships",
    "Transportation",
}


def defart(gender, plural, cap=False):
    if plural:
        a = "os" if gender == "m" else "as"
    else:
        a = "o" if gender == "m" else "a"
    return a.capitalize() if cap else a


def frame(section, lemma, gloss, gender, plural):
    """Return (prefix, suffix, english) so that
       pt    = prefix + lemma + suffix
       front = prefix + '{{gloss}}' + suffix
    """
    g = gloss
    if section == "Abstract nouns":
        return (f"{defart(gender, plural, cap=True)} ", " é importante.",
                f"{g.capitalize()} is important.")
    if section in ("Animals & nature", "City & services"):
        return (f"Eu vejo {defart(gender, plural)} ", ".", f"I see the {g}.")
    if section == "Body":
        return (f"Eu vejo {defart(gender, plural)} ", ".", f"I see the {g}.")
    if section == "Home":
        return (f"Eu limpo {defart(gender, plural)} ", ".", f"I clean the {g}.")
    if section == "Clothing":
        return (f"Eu uso {defart(gender, plural)} ", ".", f"I wear the {g}.")
    if section == "Objects":
        return (f"Eu uso {defart(gender, plural)} ", ".", f"I use the {g}.")
    if section == "Food":
        return ("Eu gosto de ", ".", f"I like {g}.")
    if section == "Family":
        if plural:
            poss = "Os meus" if gender == "m" else "As minhas"
            verb = " estão em casa."
            en = f"My {g} are at home."
        else:
            poss = "O meu" if gender == "m" else "A minha"
            verb = " está em casa."
            en = f"My {g} is at home."
        return (f"{poss} ", verb, en)
    if section == "Occupations & relationships":
        return ("Ele é ", ".", f"He is a {g}.")
    if section == "Transportation":
        if lemma == "a pé":
            return ("Eu vou ", ".", "I go on foot.")
        return ("Eu vou de ", ".", f"I go by {g}.")
    # fallback
    return (f"Eu vejo {defart(gender, plural)} ", ".", f"I see the {g}.")


def parse():
    rows, section = [], None
    for line in open(NOUNS_MD, encoding="utf-8"):
        s = line.strip()
        if not s:
            continue
        if s in SECTIONS:
            section = s
            continue
        if ":" not in s:
            continue                     # e.g. "de…by… (for the nouns above)"
        left, gloss = s.split(":", 1)
        left, gloss = left.strip(), gloss.strip()
        lemma = re.split(r"\(", left)[0].strip()      # drop "(m, -s)" etc.
        if not lemma:
            continue
        paren = left[len(re.split(r"\(", left)[0]):]
        gender = "m"
        if re.search(r"\bf\b", paren) and not re.search(r"\bm/f\b", paren):
            gender = "f"
        plural = "plural" in paren
        rows.append(dict(section=section, lemma=lemma, gloss_full=gloss,
                         gloss=gloss.split(",")[0].strip(),
                         gender=gender, plural=plural))
    return rows


def main():
    rows = parse()
    out = {"deck": DECK, "model": "words", "cards": []}
    for i, r in enumerate(rows, 1):
        pre, suf, en = frame(r["section"], r["lemma"], r["gloss"],
                             r["gender"], r["plural"])
        pt = pre + r["lemma"] + suf
        front = pre + "{{" + r["gloss"] + "}}" + suf
        num = "pl" if r["plural"] else r["gender"]
        tag = f"({r['lemma']}, {num})"
        back = f"{pt}\n{en}  {tag}"
        out["cards"].append(dict(id=f"{START_ID + i - 1:04d}", word=r["lemma"], front=front,
                                 back=back, chapter="—"))
        if "--yaml" not in sys.argv:
            print(f"{r['section'][:12]:12} | {front}")
            print(f"{'':12} | {pt}  /  {en}  {tag}")

    print(f"\n{len(rows)} nouns")
    if "--yaml" in sys.argv:
        with open(OUT_YAML, "w", encoding="utf-8") as f:
            yaml.safe_dump(out, f, allow_unicode=True, sort_keys=False, width=1000)
        print(f"wrote {OUT_YAML}")


if __name__ == "__main__":
    main()
