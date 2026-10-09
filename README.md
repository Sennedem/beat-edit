# beat-edit

Give it your song and an anime fight, and it hands back a finished TikTok edit: a character speaks for about
12 seconds, the screen goes quiet for half a second, then your beat drops on the biggest hit of the fight and
eight bars of footage are cut exactly to your drums. You don't edit anything. Claude does the cutting, you
approve the story and watch the result.

Everything runs on your own computer and costs nothing per video. The only paid part is the Claude subscription
that runs Claude Code: Pro or Max.

## What one edit looks like

- **0-12 s:** the scene before the payoff, voice only with the show's music removed, big English captions.
- **12 s:** half a second of silence, then the drop. The scene's own blast sound sits under your beat.
- **12-27 s:** eight bars of the same fight, full screen 9:16. Cuts land on the beat: one per bar, then every two
  beats, then every beat in the last bar. Shots slow down on the hit and speed up out of it, and every snare
  shakes the frame.

The first edit takes about an hour, mostly downloads and model setup. After that, a new edit takes 15-30 minutes,
and most of that is the computer working while you do something else.

## Install (once, about 30 minutes)

You type the commands below into a terminal: **PowerShell** on Windows (Start menu, type "PowerShell"),
**Terminal** on a Mac. Paste one line, press Enter, wait until it finishes, then the next.

**1. Python and ffmpeg**

Windows:
```
winget install Python.Python.3.12
winget install Gyan.FFmpeg
```
Mac (install [Homebrew](https://brew.sh) first if you don't have it):
```
brew install python@3.12 ffmpeg
```
Close the terminal and open a new one, so it finds the new programs.

**2. This repo**

Click the green **Code** button on this page, then **Download ZIP**, unzip it into your Documents folder and
rename the folder from `beat-edit-main` to `beat-edit`. Or, if you have git:
`git clone https://github.com/Sennedem/beat-edit` inside Documents.

**3. The Python packages** (about 3 GB, 10 minutes)

Go into the folder and make a private Python environment for it:
```
cd Documents/beat-edit
python -m venv .venv
```
Turn it on. Windows: `.venv\Scripts\activate`. Mac: `source .venv/bin/activate`. Your prompt now starts
with `(.venv)`. Then:
```
pip install -r requirements.txt
```

**4. Claude Code**

Windows (PowerShell):
```
irm https://claude.ai/install.ps1 | iex
```
Mac:
```
curl -fsSL https://claude.ai/install.sh | bash
```
Open a new terminal and check it with `claude --version`. The first time you run `claude`, it opens your browser
to log in with your Claude account.

## Make an edit

1. Put your song in a folder called `song` inside `beat-edit`. Use the master WAV or MP3, not a phone recording.
2. Open a terminal in `beat-edit`, turn the environment on (step 3 above), and start Claude:
   ```
   claude
   ```
3. Type what you want, for example:
   ```
   /beat-edit my song is song/on-ya-mind.wav, make an edit to Gojo vs Toji round 2
   ```
4. Claude finds the beat, suggests the dialogue for the intro and asks you to confirm the story. Then it downloads
   the footage, picks the shots and renders. It asks before it does anything big.
5. The video opens when it's done: `out/<name>.mp4`. Tell Claude what you think in plain words: "too zoomed in",
   "the drop is weak", "use the shot where he smiles". It fixes it and renders again, and it writes your feedback
   down so the next edit starts better.

No fight in mind? Ask "which fight would fit this song?" and pick one of its suggestions.

## Post it

1. Upload the MP4 in the TikTok app.
2. Tap **Add sound** and pick **your own song** from your artist profile.
3. Open **Volume** and set **Added sound to 0 %** and **Original sound to 100 %**.

The video plays the audio that's baked into the file, but the post is tagged with your official sound, so every
view counts toward your song's page. Check on the first post that it says your song's name and not "original
sound".

Post anime edits on a **separate edits account**, not on your main artist account. The footage belongs to the
studio, and an account full of it can get videos muted or taken down. The edits account points people to your
music. Your main account stays clean.

## When something goes wrong

| You see | Do this |
|---|---|
| `python` or `ffmpeg` is not recognized | Close the terminal, open a new one. Still broken: reinstall step 1. |
| `running scripts is disabled on this system` (Windows, when turning the environment on) | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, answer `Y`, then turn it on again. |
| `No module named ...` | You forgot to turn the environment on (`.venv\Scripts\activate` / `source .venv/bin/activate`). |
| The first edit sits still for minutes | It is downloading the AI models (about 1 GB, once). |
| `uncaptioned speech` or `caption ... spans a pause` | A caption doesn't match who is talking. Tell Claude; it fixes the captions. |
| No captions, font error on Linux | Set `BEATEDIT_FONT` to the path of any bold `.ttf` font. |

## Without Claude

Every step is a script you can run yourself. The order and every option are in
[.claude/skills/beat-edit/SKILL.md](.claude/skills/beat-edit/SKILL.md), and the mistakes already made are in [lessons.md](.claude/skills/beat-edit/references/lessons.md).

| Script | Does |
|---|---|
| `beatmap.py` | finds the tempo, beats and the drop in your song |
| `shots.py` | downloads the footage and splits it into shots |
| `signals.py` | scores each shot: popular, original, sharp, hard-hitting |
| `allsheet.py` | contact sheets of every shot, for Claude to tag who is on screen |
| `rank.py` | picks a shot for every cut and puts them in story order |
| `edit.py` | renders the beat edit: framing, speed ramps, hits, flashes |
| `stems.py` | downloads the intro scene and splits the voices from the music |
| `intro.py` | renders the intro, joins it to the edit, adds the drop sound and the colour grade |
| `check.py` | a contact sheet of every cut, to look at before posting |

## Built on

[Beat This!](https://github.com/CPJKU/beat_this) (beat tracking), [CLIP / OpenCLIP](https://github.com/mlfoundations/open_clip)
(finding the character in each frame), [Demucs](https://github.com/facebookresearch/demucs) (voice/music split),
[PySceneDetect](https://www.scenedetect.com), [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org).

MIT licence for the code. The footage and the music you put through it stay the property of their owners.
