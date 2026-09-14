#!/usr/bin/env python3
"""Create the 'listening' Anki note type used by tesouro-listening.yaml.

Mirrors the 'words' note type's fields/styling, but the Back template does
NOT include {{front}} -- unlike 'words' (shared by verbs/nouns/adjectives/
etc, where the Back template re-renders {{front}} as a question recap),
that would replay the front's Portuguese-only [sound:...] tag every time
the answer is shown, on top of the back's own merged Portuguese+English
audio. Listening cards have no visible front text (audio-only), so
dropping {{front}} from the Back template loses nothing visually.

Run once (idempotent: Anki errors harmlessly if the model already exists).
"""
from __future__ import annotations

import json
import os
import urllib.request

ANKI_URL = os.environ.get("ANKI_CONNECT_URL", "http://localhost:8765")


def anki(action, **params):
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    req = urllib.request.Request(ANKI_URL, data=body, headers={"Content-Type": "application/json"})
    out = json.loads(urllib.request.urlopen(req, timeout=30).read())
    if out.get("error"):
        raise RuntimeError(f"{action}: {out['error']}")
    return out["result"]


BLANK_SCRIPT = """<script>
(function(){
  document.querySelectorAll('.q,.a').forEach(function(el){
    el.innerHTML = el.innerHTML.replace(/\\{\\{([^}]+)\\}\\}/g, function(_, g){
      return '<span class="blank">' + '{'+'{' + g + '}'+'}' + '</span>';
    });
  });
})();
</script>"""


def main() -> None:
    css = anki("modelStyling", modelName="words")["css"]

    front_tmpl = f'<div class="q">{{{{front}}}}</div>\n{BLANK_SCRIPT}'
    back_tmpl = (
        '<hr id="answer">\n'
        '<div class="a">{{back}}</div>\n'
        '<div class="meta">{{word}} · #{{id}}</div>\n'
        f"{BLANK_SCRIPT}"
    )

    result = anki(
        "createModel",
        modelName="listening",
        inOrderFields=["id", "word", "front", "back", "chapter"],
        css=css,
        cardTemplates=[{"Name": "Card 1", "Front": front_tmpl, "Back": back_tmpl}],
    )
    print("created model:", result["name"])


if __name__ == "__main__":
    main()
