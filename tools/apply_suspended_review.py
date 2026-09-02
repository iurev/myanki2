#!/usr/bin/env python3
"""Apply the suspended-card review overlay to the original card YAML files.

Default is DRY RUN. Add --apply to write.

The patch is textual so comments and unrelated YAML formatting are preserved.
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "suspended-review"

def source_for_id(card_id: str) -> Path:
    n = int(card_id)
    if n <= 185: name = "verbs.yaml"
    elif n <= 468: name = "nouns.yaml"
    elif n <= 570: name = "adjectives.yaml"
    elif n <= 589: name = "location.yaml"
    elif n <= 619: name = "numbers.yaml"
    else: name = "phrases.yaml"
    return ROOT / name

def ystr(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)

def locate(lines, card_id):
    pat = re.compile(r'^(?P<i>\s*)-\s+id:\s*["\']?' + re.escape(card_id) + r'["\']?\s*$')
    for i, line in enumerate(lines):
        m = pat.match(line.rstrip("\n"))
        if not m: continue
        nxt = re.compile(r'^' + re.escape(m.group("i")) + r'-\s+id:\s*')
        j=i+1
        while j < len(lines) and not nxt.match(lines[j]): j += 1
        return i,j
    raise KeyError(f"{card_id} not found")

def set_field(block, key, value):
    pat=re.compile(r'^(\s+)'+re.escape(key)+r':')
    for i,line in enumerate(block):
        m=pat.match(line)
        if m:
            block[i]=f"{m.group(1)}{key}: {ystr(value)}\n"
            return block
    indent="    "
    for line in block[1:]:
        m=re.match(r'^(\s+)(?:word|front|back|chapter|tags|skipped):',line)
        if m: indent=m.group(1); break
    pos=1 if key=="suspended" else next((i for i,l in enumerate(block) if re.match(r'^\s+(?:back|chapter):',l)),len(block))
    block.insert(pos,f"{indent}{key}: {ystr(value)}\n")
    return block

def load_cards():
    for path in sorted(REVIEW_DIR.glob("*.yaml")):
        data=yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for card in data.get("cards",[]): yield card

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--apply",action="store_true")
    args=ap.parse_args()
    by_source={}
    for c in load_cards(): by_source.setdefault(source_for_id(str(c["id"])),[]).append(c)

    total=0
    for source,cards in by_source.items():
        lines=source.read_text(encoding="utf-8").splitlines(keepends=True)
        located=[]
        for c in cards:
            a,b=locate(lines,str(c["id"]))
            located.append((a,b,c))
        located.sort(reverse=True,key=lambda x:x[0])
        for a,b,c in located:
            block=lines[a:b]
            block=set_field(block,"suspended",c["suspended"])
            if c.get("proposed_front"): block=set_field(block,"front",c["proposed_front"])
            if c.get("proposed_back"): block=set_field(block,"back",c["proposed_back"])
            lines[a:b]=block
            total += 1
        patched="".join(lines)
        changed=patched != source.read_text(encoding="utf-8")
        print(f"{source.name}: {len(cards)} cards; changed={changed}")
        if args.apply and changed: source.write_text(patched,encoding="utf-8")

    print(("APPLIED" if args.apply else "DRY RUN")+f": {total} reviewed cards")
    if not args.apply: print("Run again with --apply to write changes.")

if __name__=="__main__":
    main()
