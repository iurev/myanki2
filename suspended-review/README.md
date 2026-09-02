# Suspended Portuguese card review

This folder contains a review overlay for the **134 cards that were suspended**
in the Anki collection export from 2026-09-02.

Nothing here unsuspends cards automatically.

For every card, the overlay records:
- `suspended`: the most likely reason it was suspended;
- `recommendation`: whether to rewrite/review, keep suspended, merge/delete, or unsuspend;
- `review_note`: the concrete reasoning/action;
- `proposed_front` / `proposed_back` when the repair is clear enough.

There are **79** rewrite/review candidates,
**46** keep-suspended candidates,
**7** merge/delete candidates, and
**2** cards that look safe to unsuspend without a substantive rewrite.
Concrete front/back proposals are included for **79** cards.

## Workflow

1. Review/edit the overlay in this PR.
2. Dry-run: `python3 tools/apply_suspended_review.py`
3. Apply accepted `suspended` metadata and proposed front/back changes:
   `python3 tools/apply_suspended_review.py --apply`
4. Inspect the resulting YAML diff, then sync to Anki.
5. Dry-run unsuspension:
   `python3 tools/unsuspend_ids.py migrations/unsuspend-after-suspended-review.txt`
6. Add `--apply` only when you are ready.

The migration list intentionally excludes cards marked `keep_suspended` or
`merge_or_delete`.
