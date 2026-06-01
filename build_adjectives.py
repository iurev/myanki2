#!/usr/bin/env python3
"""Generate adjective cards (adjectives.yaml) from adjectives.md.

Each card is a cloze sentence (consistent with the verb/noun cards). Because
Portuguese adjectives agree with their noun and split ser/estar, every adjective
is routed to a frame:

  A  ser   + neutral object : "Isto é {m}."        (default: object qualities)
  B  ser   + person         : "Ele é {m}."         (personality traits)
  C  estar + person         : "Ele está {m}."      (feelings / conditions)
  D  estar + fitting object : "A porta está {f}."  (states of things)

The back lists all four agreement forms.

    python3 build_adjectives.py            # report
    python3 build_adjectives.py --yaml     # write adjectives.yaml
"""
import re
import sys

import yaml

SRC = "adjectives.md"
OUT = "adjectives.yaml"
START_ID = 469          # continues the global id sequence after the nouns

SET_B = {"cuidadoso", "curioso", "inteligente", "maluco", "rabugento",
         "simpático", "indeciso"}
SET_C = {"assustado", "atrasado", "cansado", "chateado", "confuso", "contente",
         "deitado", "desiludido", "despenteado", "distraído", "doente",
         "espantado", "feliz", "nervoso", "ocupado", "preocupado", "pronto",
         "relaxado", "sozinho", "surpreso", "triste"}
D_SUBJ = {
    "aberto": ("A porta", "The door"), "fechado": ("A porta", "The door"),
    "cheio": ("A garrafa", "The bottle"), "escondido": ("A chave", "The key"),
    "fresco": ("A água", "The water"), "frio": ("A água", "The water"),
    "gelado": ("A água", "The water"), "partido": ("A chávena", "The cup"),
    "quente": ("A sopa", "The soup"), "sujo": ("A roupa", "The clothing"),
    "submerso": ("A cidade", "The city"), "desarrumado": ("A casa", "The house"),
}

IRREG = {  # m, f, m-plural, f-plural
    "bom": ("bom", "boa", "bons", "boas"),
    "mau": ("mau", "má", "maus", "más"),
}
PL_OVERRIDE = {
    "agradável": "agradáveis", "desconfortável": "desconfortáveis",
    "fácil": "fáceis", "final": "finais", "incrível": "incríveis",
    "inútil": "inúteis", "feliz": "felizes", "azul": "azuis",
    "simples": "simples", "cor-de-rosa": "cor-de-rosa",
    "cor-de-laranja": "cor-de-laranja",
}


def forms(lemma):
    if lemma in IRREG:
        return IRREG[lemma]
    if lemma.endswith("o"):
        m, f = lemma, lemma[:-1] + "a"
        return m, f, m + "s", f + "s"
    # gender-invariable (ends in -e or a consonant)
    if lemma in PL_OVERRIDE:
        pl = PL_OVERRIDE[lemma]
    elif lemma.endswith(("e", "a")):
        pl = lemma + "s"
    else:
        pl = lemma + "es"
    return lemma, lemma, pl, pl


def parse():
    rows, colors = [], False
    for line in open(SRC, encoding="utf-8"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            colors = "Colors" in s
            continue
        if ":" not in s:
            continue
        left, gloss = s.split(":", 1)
        lemma = re.split(r"\(", left)[0].strip()
        gloss = gloss.strip()
        rows.append(dict(lemma=lemma, gloss=gloss.split(",")[0].strip(),
                         color=colors))
    return rows


def card(r):
    lemma, gloss = r["lemma"], r["gloss"]
    m, f, mpl, fpl = forms(lemma)
    if r["color"] or (lemma not in SET_B and lemma not in SET_C
                      and lemma not in D_SUBJ):
        pre, form, en = "Isto é ", m, f"This is {gloss}."
    elif lemma in SET_B:
        pre, form, en = "Ele é ", m, f"He is {gloss}."
    elif lemma in SET_C:
        pre, form, en = "Ele está ", m, f"He is {gloss}."
    else:
        subj, subj_en = D_SUBJ[lemma]
        pre, form, en = f"{subj} está ", f, f"{subj_en} is {gloss}."
    pt = f"{pre}{form}."
    front = f"{pre}{{{{{gloss}}}}}."
    if m == f:
        fline = f"(m/f: {m} · pl: {mpl})"
    else:
        fline = f"(m: {m} · f: {f} · pl: {mpl}/{fpl})"
    back = f"{pt}\n{en}\n{fline}"
    return front, back


def main():
    rows = parse()
    out = {"deck": "words", "model": "words", "cards": []}
    for i, r in enumerate(rows):
        front, back = card(r)
        out["cards"].append(dict(id=f"{START_ID + i:04d}", word=r["lemma"],
                                 front=front, back=back, chapter="—"))
        if "--yaml" not in sys.argv:
            print(f"{front:32} | {back.replace(chr(10),' / ')}")
    print(f"\n{len(rows)} adjectives (ids {START_ID:04d}-{START_ID+len(rows)-1:04d})")
    if "--yaml" in sys.argv:
        with open(OUT, "w", encoding="utf-8") as fh:
            yaml.safe_dump(out, fh, allow_unicode=True, sort_keys=False, width=1000)
        print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
