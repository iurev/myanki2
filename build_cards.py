#!/usr/bin/env python3
"""Generate words-deck cards from verbs.md + the book's PT/EN sentence pairs.

For each verb we look for a book sentence containing a conjugated form of the
verb. Sentences whose English translation also mentions the verb's meaning are
preferred (high confidence); otherwise the best remaining match is used and
flagged low-confidence for review. The verb token is blanked with its English
gloss to form the card front, and the source chapter is recorded.

    python3 build_cards.py            # report to stdout (review)
    python3 build_cards.py --yaml     # also write config.yaml
"""
import re
import sys
import unicodedata

import yaml

import extract_pairs

VERBS_MD = "verbs.md"
OUT_YAML = "config.yaml"

# Conjugated forms for verbs whose present stem differs from the infinitive stem
# (or whose stem is too short to match safely). Union'd with the stem search.
IRREGULAR = {
    "ser": "sou és é somos são era eram fui foste foi fomos foram sido",
    "estar": "estou estás está estamos estão estava estavam estive esteve estiveram",
    "ter": "tenho tens tem temos têm tinha tinham tive teve tiveram",
    "ir": "vou vais vai vamos vão ia iam",
    "vir": "venho vens vem vimos vêm vinha veio vieram",
    "ver": "vejo vês vê vemos veem via viam vi viu viram visto",
    "pôr": "ponho pões põe pomos põem punha pus pôs puseram posto",
    "fazer": "faço fazes faz fazemos fazem fazia fiz fez fizeram feito",
    "dizer": "digo dizes diz dizemos dizem dizia disse disseram dito",
    "dar": "dou dás dá damos dão dava dei deu deram",
    "saber": "sei sabes sabe sabemos sabem sabia soube souberam",
    "poder": "posso podes pode podemos podem podia pude pôde puderam",
    "querer": "quero queres quer queremos querem queria quis quiseram",
    "dever": "devo deves deve devemos devem devia",
    "dormir": "durmo dormes dorme dormimos dormem dormia dormiu",
    "ouvir": "ouço ouves ouve ouvimos ouvem ouvi ouviu",
    "pedir": "peço pedes pede pedimos pedem pedi pediu",
    "perder": "perco perdes perde perdemos perdem perdi perdeu",
    "sair": "saio sais sai saímos saem saí saiu",
    "trazer": "trago trazes traz trazemos trazem trouxe trouxeram",
    "subir": "subo sobes sobe subimos sobem subi subiu",
    "fugir": "fujo foges foge fugimos fogem fugi fugiu",
    "sentir": "sinto sentes sente sentimos sentem senti sentiu",
    "mentir": "minto mentes mente mentimos mentem menti mentiu",
    "servir": "sirvo serves serve servimos servem servi serviu",
    "vestir": "visto vestes veste vestimos vestem vesti vestiu",
    "despir": "dispo despes despe despimos despem despi despiu",
    "rir": "rio ris ri rimos riem ria riu",
    "ler": "leio lês lê lemos leem li leu",
    "perceber": "percebo percebes percebe percebemos percebem percebi",
}

# Pure function words: ignored when deriving English gloss keywords. We keep
# meaning-bearing helpers like have/do/be so "to have to do with" still has one.
STOP = set("to a an the of oneself itself up down out off away into from over "
           "in on at for with by lit also".split())

CLITIC = re.compile(r"^-(se|me|te|nos|vos|lhe|lhes|o|a|os|as)\b")
TABLE_LINE = re.compile(r"^(eu|tu|ele|ela|você|nós|vós|eles|elas|a gente)\s+\S+\.?$",
                        re.IGNORECASE)


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def gloss_blank(g):
    """Concise hint for the front: drop parentheticals, extra senses, objects."""
    g = re.sub(r"\(.*?\)", "", g)
    g = g.split(",")[0]
    g = re.split(r"\b(someone|something|somebody|a place|oneself)\b", g)[0]
    return re.sub(r"\s+", " ", g).strip()


def parse_verbs():
    verbs = []
    for line in open(VERBS_MD, encoding="utf-8"):
        line = line.rstrip("\n")
        if ":" not in line or line.strip().startswith("==="):
            continue
        inf, rest = line.split(":", 1)
        inf = inf.strip()
        if not inf:
            continue

        gloss = re.split(r"https?://", rest.strip())[0]
        cut = len(gloss)
        for i, ch in enumerate(gloss):
            if ord(ch) > 0x2BF:                      # first non-latin char
                cut = i
                break
        gloss = gloss[:cut].strip()

        base = inf.split()[0].split("-")[0]
        gloss = re.sub(rf"\s+{re.escape(base)}\s*$", "", gloss)   # trailing slug
        gloss = re.sub(r"\s+", " ", gloss).strip(" ,\t")
        if not gloss:
            gloss = rest.strip()

        b = base
        if b == "pôr":
            stem = "p"
        elif b.endswith(("ar", "er", "ir")):
            stem = b[:-2]
        else:
            stem = b

        kws = [strip_accents(w.lower()) for w in re.findall(r"[A-Za-z]+", gloss)]
        kws = [w for w in kws if w not in STOP and len(w) > 1]

        verbs.append(dict(infinitive=inf, gloss=gloss, blank=gloss_blank(gloss),
                          base=base, stem=stem, keywords=kws,
                          reflexive="-se" in inf))
    return verbs


def good_pairs():
    """Book pairs minus conjugation tables and bare drill lines."""
    out = []
    for pt, en, chap in extract_pairs.pairs():
        if en.strip().startswith("("):          # "(they know)" gloss of a table
            continue
        if TABLE_LINE.match(pt):                 # "eles conhecem"
            continue
        if len(pt) < 10:
            continue
        out.append((pt, en, chap))
    return out


def build_regex(v):
    alts = []
    if v["base"] in IRREGULAR:
        alts += [re.escape(f) for f in IRREGULAR[v["base"]].split()]
    if len(v["stem"]) >= 3:
        alts.append(re.escape(v["stem"]) + r"[a-zà-úãõçê]{1,5}")
    alts.append(re.escape(v["base"]))            # bare infinitive (after auxiliary)
    return re.compile(r"\b(" + "|".join(alts) + r")\b", re.IGNORECASE)


def score(pt, en, v, token):
    en_l = strip_accents(en.lower())
    s = 0.0
    primary = v["keywords"][0] if v["keywords"] else None
    if primary and primary in en_l:
        s += 4
    if any(k in en_l for k in v["keywords"]):
        s += 2
    if re.search(r"[.!?]\s*$", pt) and re.match(r"^[—A-ZÀ-Ú]", pt):
        s += 2
    if token.lower() != v["base"]:               # finite form beats infinitive
        s += 1
    s -= len(pt) / 60.0                           # shorter is better
    if re.search(r"\d", pt):
        s -= 1
    if len(pt) > 140:
        s -= 3
    return s


def extend_span(pt, span):
    """Grow the verb span to swallow an enclitic pronoun (chama-se -> chama-se)."""
    s, e = span
    m = CLITIC.match(pt[e:])
    if m:
        e += m.end()
    return s, e


def best_match(v, pairs):
    rx = build_regex(v)
    with_kw, without = [], []
    for pt, en, chap in pairs:
        m = rx.search(pt)
        if not m:
            continue
        token = m.group(1)
        rec = (score(pt, en, v, token), pt, en, chap, extend_span(pt, m.span(1)), token)
        en_l = strip_accents(en.lower())
        if v["keywords"] and any(k in en_l for k in v["keywords"]):
            with_kw.append(rec)
        else:
            without.append(rec)
    pool, conf = (with_kw, "ok") if with_kw else (without, "low")
    if not pool:
        return None
    return max(pool, key=lambda r: r[0]), conf


def make_front(pt, span, blank):
    s, e = span
    return pt[:s] + "{{" + blank + "}}" + pt[e:]


def main():
    emit_yaml = "--yaml" in sys.argv
    verbs = parse_verbs()
    pairs = good_pairs()

    matched, misses = [], []
    for v in verbs:
        res = best_match(v, pairs)
        if res is None:
            misses.append(v)
            continue
        (sc, pt, en, chap, span, token), conf = res
        matched.append(dict(v=v, pt=pt, en=en, chap=chap, span=span,
                            score=sc, conf=conf))

    ok = [m for m in matched if m["conf"] == "ok"]
    low = [m for m in matched if m["conf"] == "low"]
    print(f"verbs {len(verbs)} | matched {len(matched)} "
          f"(ok {len(ok)}, low {len(low)}) | missed {len(misses)}\n")
    for m in matched:
        v = m["v"]
        front = make_front(m["pt"], m["span"], v["blank"])
        flag = "  <<LOW" if m["conf"] == "low" else ""
        print(f"[{m['score']:+.1f}{flag}] ch.{m['chap']}  {v['infinitive']} ({v['gloss']})")
        print(f"   F: {front}")
        print(f"   B: {m['pt']} | {m['en']}")
    print("\n--- MISSED ---")
    print(", ".join(v["infinitive"] for v in misses))

    if emit_yaml:
        out = {"deck": "words", "model": "words", "cards": []}
        for i, m in enumerate(matched, 1):
            v = m["v"]
            out["cards"].append({
                "id": f"{i:04d}", "word": v["infinitive"],
                "front": make_front(m["pt"], m["span"], v["blank"]),
                "back": f"{m['pt']}\n\n{m['en']}", "chapter": str(m["chap"]),
            })
        with open(OUT_YAML, "w", encoding="utf-8") as f:
            yaml.safe_dump(out, f, allow_unicode=True, sort_keys=False, width=1000)
        print(f"\nwrote {OUT_YAML}: {len(out['cards'])} cards "
              f"({len(low)} low-confidence)")


if __name__ == "__main__":
    main()
