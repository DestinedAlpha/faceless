# Faceless — project brief for the coding agent

100% free, fully-automated faceless-video generator. Python discovers trends
(YouTube+Reddit) → LLM (Gemini→Groq) picks topic/format → per-niche "playbook" →
scene script → voice + AI images + karaoke captions + SFX/music → `video_spec.json`
→ Remotion renders a 9:16 MP4 → thumbnail + metadata. Run: `python -m faceless [run|trends|plan]`.
Degrades gracefully with zero keys. No auto-upload.

## Hard constraints (never violate)
- 100% free (no paid APIs/cards). Cloud-only, light (no local GPU / heavy models).
- Niche mastery must generalize to ANY niche the selector finds.
- Analytics learning is manual-upload-only (never auto-post).
- Every provider needs a free fallback; a dead API must never break a run.

## Done (do not redo)
- Render bridge fix `faceless/render/remotion.py` (Windows shell/space-path; npx via
  shutil.which, shell=False, `_relocate_output`). `scripts/smoke_test.py`, `README.md`.
- Phase 3 Mastery Engine: `playbooks/` (_base + 7 niches), `faceless/plan/mastery.py`
  (`get_playbook`: authored→LLM-synth+cache→nearest→base). Wired into pipeline/script/tts/subtitles/spec.
- Phase 1 Voice+Sound: voice ladder `faceless/assets/tts.py` (Chatterbox→Kokoro HF Spaces
  →Gemini TTS→edge-tts) + per-scene prosody; `faceless/assets/sfx.py` (procedural SFX →
  `assets_lib/sfx/`); `faceless/assets/music.py` (mood track or procedural bed); ffmpeg
  loudnorm; spec+Remotion (`Scene.tsx`/`Video.tsx`/`types.ts`) play per-scene SFX; caption
  per-word `emphasis` carried in spec.

## Remaining (one phase fully at a time; end each with a REAL render)
- Phase 2 Motion+Coherence: 2.5D parallax (rembg fg/bg layers + camera dolly) in new
  Remotion `Layers.tsx`; transitions via `@remotion/transitions`; animated emphasis captions
  in `Captions.tsx` (spec already has per-word `emphasis`); per-niche color grade; image
  consistency (style/seed lock + character sheet + negative prompts).
- Phase 4 hook_lab + QC gate. Phase 5 thumbnail variants + title A/B. Phase 6 YouTube
  Analytics OAuth learn-loop (manual upload). Phase 7 optional AI-video clips + long-form.
- Full plan: see `BEST_VERSION_ROADMAP.md`.

## Run / verify
```
cd "C:\Users\syed_\Desktop\yt thing\faceless"
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # add free keys; Gemini matters most
python scripts/smoke_test.py
python -m faceless          # then open output/<latest>/ and WATCH the mp4
```
After changes: `python -m py_compile` changed modules; `npx tsc --noEmit -p remotion/tsconfig.json`;
then a real `python -m faceless` render. Path has a space ("yt thing") — keep subprocess calls shell-safe.
Remotion project is in `remotion/`, consumes `video_spec.json` as inputProps; renders via esbuild.
