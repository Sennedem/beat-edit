# Lessons (append every correction, newest at the bottom)

Each line cost a render to learn. Read before the first run of a session.

## Story and shots
- The intro must set up what the edit pays off: the same fight, the line right before the payoff. A heavy line
  followed by an unrelated montage tells no story (rejected v3, 2026-10-08).
- No overused hype quotes ("I alone am the honored one", "Nah, I'd win"), no single short quotes: a ~12 s scene.
- Dialogue wording comes from the official subtitles, never from memory: Claude once "remembered" a chant that is
  not in the scene.
- One caption per speaker turn. v3 put one character's caption over the other character's reply; `intro.py` now
  fails the build when a caption spans a pause over 0.8 s (calibrated on only two cases: raise it if a slow
  speaker trips it, never delete it).
- Scene packs mix in flashbacks from earlier rounds; tag `fight` and set it in the plan. Keep the hero on
  ≥70 % of the shots (`main_share`).
- Ranking on motion alone picks debris and rocks. Quality scores defects only (blur, black, flicker), never art
  style: golden bloom and bright light are the look, not a flaw.

## Framing
- Centre crop cuts faces; a fixed 1.14 punch-in was "too zoomed in". Blurred bars around a 16:9 frame looked
  cheap. Now: full-screen 9:16 that follows the character, found by CLIP (12/12 on hand-marked test shots; edge
  saliency got 9/12 and chased hair, hands and chains).
- Keep every take ≥0.25 s away from shot boundaries: twixtor packs morph one shot into the next there, and the
  motion spike fooled the impact-frame finder into a garbled first frame.

## Audio
- The beat detector skips beats on trap (half-time 808s); `edit.py` fits a regular grid through the downbeats
  instead of trusting single beats.
- A mono song upmixed to stereo by ffmpeg drops 3 dB; `edit.py` pans mono to both sides at full level.
- ffmpeg's `alimiter` auto-levels the whole track unless `level=0`; `amerge` ends at its shortest input unless
  the shorter one is padded (`apad`).
- YouTube auto-subtitles return HTTP 429 when fetched in bulk: use the subtitles burned into the clip.

## Speed
- Run CLIP before the video encoder starts: side by side they turned a 3-minute render into 134 minutes.
- YouTube serves AV1, and OpenCV seeking in AV1 hung for 1h47m: `shots.py` asks for H.264 and scans a 640 px proxy.
