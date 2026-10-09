# File formats

## clips/<name>/vision.json (written by Claude in step 5)

One entry per shot id (as a string). Keys starting with `_` are notes and are ignored.

```json
{
  "_how": "Claude's read of each impact frame, <fight>, <date>.",
  "51": {"iconic": 9, "impact": 10, "role": "drop", "subject": "toji", "fight": "r2",
         "note": "Purple hits Toji in the chains (the payoff)"},
  "15": {"iconic": 8, "impact": 7, "role": "build", "subject": "gojo", "fight": "r2", "note": "manic laugh close"},
  "9":  {"iconic": 8, "impact": 8, "role": "impact", "subject": "gojo", "fight": "r1",
         "note": "stabbed through the head (round-1 flashback)"},
  "47": {"iconic": 0, "impact": 0, "role": "filler", "subject": "gojo", "fight": "r2", "flags": ["in-intro"]}
}
```

| key | values | meaning |
|---|---|---|
| iconic | 0-10 | would a fan of the show recognise this moment instantly |
| impact | 0-10 | how hard it hits on a beat |
| role | drop / build / impact / close / filler | where it belongs: the payoff, a slow character beat, a hit, the ending, never |
| subject | the character's name / both / other | who fills the frame; `main` in the plan counts the hero's share |
| fight | any label (r1, r2, flashback…) | the plan's `fight` keeps only matching shots |
| flags | in-intro, text, blank, soft, other-character | in-intro and text/blank are never picked; soft is penalised |
| note | free text | printed next to the pick, so write what is on screen |

## plans/<name>.json (edit) and plans/<name>-intro.json

See `plans/example-edit.json` and `plans/example-intro.json`; each has a `_how` line. All times are seconds:
song time in the edit plan, source-video time in the intro plan.
