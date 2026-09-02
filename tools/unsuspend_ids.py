#!/usr/bin/env python3
"""Unsuspend Anki cards by note `id` using AnkiConnect. Dry-run by default."""
import argparse, json, urllib.request
from pathlib import Path
ANKI_URL="http://localhost:8765"

def anki(action, **params):
    body=json.dumps({"action":action,"version":6,"params":params}).encode()
    req=urllib.request.Request(ANKI_URL,data=body,headers={"Content-Type":"application/json"})
    out=json.loads(urllib.request.urlopen(req,timeout=15).read())
    if out.get("error"): raise RuntimeError(f"{action}: {out['error']}")
    return out["result"]

def read_ids(path):
    return [x.strip() for x in Path(path).read_text(encoding="utf-8").splitlines()
            if x.strip() and not x.lstrip().startswith("#")]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("ids_file")
    ap.add_argument("--deck",default="words")
    ap.add_argument("--apply",action="store_true")
    args=ap.parse_args()
    cards=[]; missing=[]
    for note_id in read_ids(args.ids_file):
        nids=anki("findNotes",query=f'deck:"{args.deck}" "id:{note_id}"')
        if not nids: missing.append(note_id); continue
        for nid in nids: cards += anki("findCards",query=f"nid:{nid}")
    cards=sorted(set(cards))
    print(f"matched {len(cards)} cards; missing {len(missing)} ids")
    if missing: print("missing:",", ".join(missing))
    if args.apply:
        if cards: anki("unsuspend",cards=cards)
        print(f"unsuspended {len(cards)} cards")
    else:
        print("DRY RUN: add --apply to change Anki.")

if __name__=="__main__": main()
