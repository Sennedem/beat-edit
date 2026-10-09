---
name: beat-edit
description: Make a TikTok/Reels/Shorts "beat edit" from a song and anime (or any) footage - a ~12 s dialogue intro that sets up the moment, then a 9:16 edit cut frame-exact to the beat with speed ramps, hit effects and a drop. Use when the user says "/beat-edit", "make an edit", "make a beat edit to my song", "edit this fight to my track", "AMV", "velocity edit", or drops a song and a clip link and wants a video. Runs locally, costs nothing.
---

# beat-edit

You make the whole video. The user picks the song, approves the story, and watches the result; they never edit.
Every script lives in the repo root and is run from there. Read `references/lessons.md` before the first run in a
session: it holds every mistake already made, and each one cost a full render to find.

## Definition of done

`out/<name>.mp4` exists, 1080x1920, 20-30 s: a dialogue intro with readable English captions, ~0.5 s of silence,
the beat drops on the payoff shot, then an 8-bar edit. You have looked at the contact sheets of the intro and every
slot (step 9) and told the user what you checked and what only they can judge (the feel). Never call the feel
"verified".

## Steps

**1. Song.** Ask for the master file (WAV/MP3) and put it in `song/`. No master? Apple's free 30 s preview works for a
draft: `https://itunes.apple.com/lookup?id=<artist id>&entity=song&limit=50` lists `previewUrl` per track.
Run `python beatmap.py song/<file>`. It writes `song/<file>.beatmap.json` (bpm, downbeats, drop candidates) and a
mono WAV next to the source. Pick the section: 8 bars (≈ 15 s at 130 BPM) starting on a downbeat where the beat
hits hardest; the first drop candidate is usually right. That start is the `drop`.

**2. Story (ask, then confirm).** One fight, told before -> after: the intro is the line right before the payoff,
the edit is what happens next. Ask the user for the anime/fight, or propose 2-3 with the scene and the line.
Bar for the line: it carries weight and runs ~10-14 s; never an overused hype quote, never a single short quote.
Get the wording from the official subtitles (burned into the clip, or Crunchyroll) and never from memory: Claude
has misremembered scene dialogue before. Confirm the story with the user before downloading anything big.

**3. Footage.** Find a scene pack of that fight (search YouTube for "<fight> scene pack" / "twixtor"; 60 fps
twixtor packs give the smoothest slow motion). `python shots.py <url-or-file> <name>` downloads it, finds every
shot and writes `clips/<name>/{source.mp4, proxy.mp4, shots.json, sheet.jpg, meta.json}`.

**4. Signals.** `python signals.py <name> [<url of a viral edit of this fight> ...]`. Two to nine edit URLs with
real views make the popularity score far better; without them it falls back to replays and your own read.

**5. Your read of every shot (vision.json).** `python allsheet.py <name>`, then look at every `clips/<name>/all-*.jpg`
and write `clips/<name>/vision.json` in the format in `references/formats.md`: iconic, impact, role, subject,
fight, flags, note per shot. Tag `in-intro` on shots that already appear in the intro clip, `text` on title cards,
`soft` on blurry ones. Fight tags matter: scene packs mix in flashbacks from earlier rounds.

**6. Plan + pick.** Copy `plans/example-edit.json` to `plans/<name>.json`, fill in audio, beatmap, source, shots,
start, end, drop, and set `fight` + `main` (the hero) + `main_share` (0.7). Run `python rank.py <name> plans/<name>.json`.
It prints one line per slot. Read it as a story: drop = the payoff hit, the build slots after it = the hero's
moment, then the fight's hits in order, the last slot = the end. If a pick makes no sense, fix the shot's
vision.json entry and rerun (do not hand-edit picks unless the user asks for a specific shot).

**7. Render the edit.** `python edit.py plans/<name>.json` -> `out/<name>.mp4` (the edit alone, with the song).
First run ~3-5 min (CLIP finds the character in every shot; cached in `out/<name>/track.json`, so later
effect-only renders take ~1 min).

**8. Intro.** `python stems.py <scene url-or-file> <scene name> <start> <end>` downloads the dialogue scene with
sound and splits voice from music; it prints the lines to paste and a suggested blast time. Copy
`plans/example-intro.json` to `plans/<name>-intro.json`: start/end of the dialogue in source seconds (end ~0.5 s
after the last word, which becomes the silence before the drop), one caption per speaker turn with the official
wording, `crop_bottom` if the clip has subtitles burned in, `edit` = `out/<name>.mp4`.
Run `python intro.py plans/<name>-intro.json` -> `out/<intro name>.mp4`, the finished video. It refuses to build
when speech has no caption or a caption spans a speaker change; fix the subs, never the guard.

**9. Look before you hand it over.** `python check.py out/<final>.mp4 out/<edit name>/cuts.json out/check.jpg <intro seconds>`
makes one row per slot (first frame, +3, middle, last). Look at it and at a few intro frames
(`ffmpeg -i out/<final>.mp4 -vf "fps=1,scale=270:-2,tile=6x2" -frames:v 1 out/intro.jpg`). Every slot must show the
character's face or the action, never only hair, hands or background. Then open the video for the user.

**10. Hand-off.** Tell the user what you checked, what you could not (feel, timing, effect strength), and how to
post: in the TikTok app upload the MP4, add their official sound, set Added sound 0 % / Original sound 100 %, so
the post is tagged with their song while the baked-in audio plays. Anime footage belongs on a separate edits
account, not the main artist account: it can be muted or taken down.

## When the user gives feedback

"Too zoomed", "boring", "doesn't make sense", "wrong shot": fix it in the smallest durable place (the plan, a
vision.json entry, a constant at the top of edit.py) and rerender. Add every correction to
`references/lessons.md` with the date, so the next edit starts from it.

Tuning knobs at the top of `edit.py`: `RAMPS` (speed ramp per slot type), `PUNCH`, `PUSH`, `FREEZE`, `GRADE`
(colour). Hit strength sits in `render_segment` (shake 22 px, RGB split 14 px in the fast half).
