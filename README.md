# Faceless — fully-automated free faceless video generator

Finds a genuinely trending topic from real engagement data, lets an LLM decide the
best format/length/style, writes a scene-by-scene script, generates AI stills +
expressive voiceover + word-by-word karaoke captions, and renders a polished
vertical Short (9:16) with a thumbnail, title, description and tags ready to review
and upload.

Everything runs on free tiers with no card required. **Nothing is auto-uploaded** —
each run drops a review-ready folder under `output/`.

- **No hardcoded topic** — the system discovers and chooses it from live trends.
- **No local LLMs** — cloud free tiers (Gemini → Groq) only.
- **Graceful degradation** — every layer has a fallback, so a single dead API or a
  missing key never breaks a run. With *zero keys* you still get edge-tts narration
  over Pollinations AI stills with karaoke captions.

---

## Requirements

- **Python 3.10+** (3.11 recommended)
- **Node.js LTS** (18+) — used by Remotion to render. `node` and `npx` must be on PATH.
- **ffmpeg / ffprobe** on PATH (Remotion bundles ffmpeg for rendering; ffprobe is
  used to measure narration durations).

## Setup

```bash
cd faceless

# 1. Python environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt

# 2. Keys (all optional, all free — copy and fill in what you have)
cp .env.example .env        # Windows: copy .env.example .env

# 3. Remotion deps (also auto-installed on first render)
cd remotion && npm install && cd ..
```

### API keys (all free, no card)

None are required to produce a video, but each unlocks more:

| Key | Unlocks | Where |
|---|---|---|
| `GEMINI_API_KEY` | Smart topic selection, scripts, metadata | https://aistudio.google.com/apikey |
| `GROQ_API_KEY` | LLM fallback + Whisper caption alignment | https://console.groq.com/keys |
| `YOUTUBE_API_KEY` | Real YouTube trend discovery | Google Cloud → "YouTube Data API v3" |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Reddit trend breadth + corroboration | https://www.reddit.com/prefs/apps (type: script) |
| `PEXELS_API_KEY` / `PIXABAY_API_KEY` | Real stock B-roll motion between stills | pexels.com/api, pixabay.com/api/docs |
| `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN` | Flux image backup (Pollinations is primary, needs no key) | dash.cloudflare.com → Workers AI |

With **no keys at all**: synthetic trend pool → template script → edge-tts voice →
Pollinations images → rendered Short. Add keys to make each stage smarter/real.

## Verify your providers

```bash
python scripts/smoke_test.py
```

Hits every adapter once and prints `PASS` / `FAIL` / `SKIP` (SKIP = no key for that
optional layer). Core keyless layers are `images`, `tts`, and `node`.

## Run

```bash
# Full pipeline: trends -> select -> script -> voice -> images -> captions -> render
python -m faceless

# Just discover & print ranked topics (no generation)
python -m faceless trends

# Trends -> selection -> script, printed as JSON (no assets/render)
python -m faceless plan

# Useful flags
python -m faceless run --skip-render   # build spec + all assets, don't invoke Remotion
python -m faceless run --skip-stock    # AI stills only, ignore any stock keys
python -m faceless run --no-synthetic  # fail instead of using the offline test pool
python -m faceless --log DEBUG         # verbose logging
```

Each run writes `output/<timestamp>_<slug>/`:

```
output/20260710-141552_the-mirroring-psychology-trick/
  audio/            per-scene narration (mp3)
  img/              per-scene AI stills (jpg)
  video/            optional stock B-roll clips (mp4)
  selection.json    what the selector chose + why
  script.json       the scene-by-scene script
  video_spec.json   the Python↔Remotion contract (scenes, timings, captions)
  metadata.json     title / description / tags
  thumbnail.jpg     1280x720 thumbnail
  <slug>.mp4        the final rendered video
  summary.json      run summary (paths, duration, etc.)
```

## How it works

```
trends/   discover (YouTube mostPopular + Reddit) -> score -> cluster -> rank
plan/     selector (LLM picks topic+niche+format+length+style) -> script writer
assets/   tts (edge-tts / Chatterbox) -> subtitles -> images -> stock -> music
render/   spec.py assembles video_spec.json -> remotion.py invokes `remotion render`
publish/  metadata (LLM) -> thumbnail (AI bg + bold text) -> packaged output folder
remotion/ one composition drives both 9:16 Shorts and 16:9 long-form via inputProps
```

Scene durations come from the **actual** TTS audio length (not LLM estimates), so
audio, visuals and captions stay perfectly in sync.

## Tuning

All behaviour lives in `config.yaml` (regions, subreddits, score weights, allowed
niches, format bounds, provider order, Ken Burns / caption / music knobs). There is
deliberately **no topic** in config — that is always chosen from live trends.

## Notes & honest limitations

- **Copyright-safe by design.** Visuals are AI-generated imagery + generic stock +
  Ken Burns motion — never ripped copyrighted clips (which Content ID auto-strikes).
- **edge-tts** uses a ToS-gray Microsoft backend and **Chatterbox** on free cloud GPU
  can be flaky; the fallback chain keeps runs working, but expressive-voice
  availability varies. Leave `providers.tts.chatterbox_space` blank to go straight to
  the reliable edge-tts voice.
- **No auto-upload** — you review each folder and upload yourself (safest for channel
  health).
- Background music is off unless you drop royalty-free `.mp3`/`.m4a` files into
  `assets_lib/music/`; otherwise videos render with narration only.

## Troubleshooting

- **`node`/`npx` not found** → install Node.js LTS and reopen your shell so PATH updates.
- **First render is slow** → Remotion bundles + installs its deps once; later runs are faster.
- **A provider fails mid-run** → it falls back automatically; check the logs for which
  provider was used. Run `python scripts/smoke_test.py` to isolate a bad key.
