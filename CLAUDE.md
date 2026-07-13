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
- Phase 6 Analytics learn-loop (manual-upload-only, all free): new `faceless/learn/`
  package. `store.py` owns `memory/performance.jsonl` (upsert/dedup by run_id) + run-folder
  feature extraction (niche, hook shape via `classify_hook`, pacing, title variants) + a cheap
  offline hook-shape classifier. `ingest.py` two sources → one store: manual `memory/metrics_inbox.jsonl`
  (paste from YT Studio; archived after ingest) and optional OAuth `from_youtube()`; joins metrics
  back to the run by run_id; `write_inbox_template()` stubs un-reported runs. `youtube_analytics.py`
  OAuth (google libs + client_secret lazy-imported; `available()` gates everything; read-only scopes;
  Data API uploads list + Analytics AVD/AVP/CTR/impressions/retention pull) — degrades to no-op when
  libs/secret absent. `reflect.py` aggregates per-niche, and once a niche has ≥`learn.min_samples`
  usable rows, blends `retention_targets.avd_pct`, steps `pacing.seconds_per_scene`, and (LLM, whitelisted+
  clamped; offline stat fallback) floats the best hook shape + refreshes title patterns — writing a
  SEPARATE overlay `playbooks/learned/<niche>.yaml` (authored packs never mutated; `rm` to reset) plus
  human-readable `memory/learnings.md`. `mastery.py` now merges that overlay LAST for EVERY resolution
  path (`_apply_learned`; `_source` gains `+learned`) and exposes `base_playbook()` (pre-overlay, so
  reflect blends from stable levers — idempotent). CLI `python -m faceless learn [--pull|--backfill N|
  --template|--no-reflect|--min-samples N]`; `scripts/backfill_analytics.py` one-off OAuth seed;
  `config.yaml` `learn:` block; smoke_test `check_learn`; checklist §8 now emits a copy-paste run_id-keyed
  JSON inbox line. Verified fully offline: fabricated metrics for 4 real explainer runs → ingest (idempotent
  upsert) → reflect patched the explainer overlay (retention/pacing offline + hook_formulas/title via LLM)
  → learnings.md with concrete non-generic rules → a REAL render (8-scene explainer short, 57.3s, 33.4MB,
  audio+video) whose `playbook.json` shows `_source: authored+learned`, avd_pct 0.58, and the learned hook
  formula floated to index 0 — i.e. a live run inheriting the lessons. OAuth/`--pull` no-op'd gracefully
  (libs absent). Fabricated test data was then REMOVED (memory/*, learned/explainer.yaml) so no fake overlay
  biases production; explainer confirmed back to authored avd_pct 0.55.
- Render bridge fix `faceless/render/remotion.py` (Windows shell/space-path; npx via
  shutil.which, shell=False, `_relocate_output`; NOW also retries once at concurrency=1
  if a multi-tab render fails, so a Chromium tab OOM degrades to a slow success).
  `scripts/smoke_test.py`, `README.md`.
- Bugfix `faceless/llm/client.py` `_to_gemini_schema`: it dropped ANY dict key named
  "title" to strip JSON-schema annotations, which also deleted the metadata *property*
  named `title` → Gemini 400 every metadata call (silently fell back to Groq). Now it
  never filters keys inside a `properties` map. Gemini is primary for metadata again.
- Phase 5 Packaging + Thumbnail/Title A/B: `publish/metadata.py` now takes the playbook,
  emits `title_variants` (2-3 A/B, seeded by playbook `title.patterns`) + `thumbnail_variants`
  + long-form `chapters` (schema extended in `plan/schemas.py`, sanitizer dedupes/caps/forces
  primary in). `publish/thumbnail.py` `generate_variants()` renders up to 3 distinct 1280x720
  variants (bg seed + text option + look preset {fill,pos}); variant 0 composites a rembg
  subject cutout via new `assets/motion.py::cutout()` (no coverage gate; graceful when rembg
  absent). `publish/package.py` `write_checklist()` writes `UPLOAD_CHECKLIST.md` (A/B titles,
  thumbnails, hook+alt, paste-ready description/tags, chapters, post-time hint, QC verdict,
  and run_id-keyed metrics fields for the Phase 6 learn loop). Wired in `pipeline.py`; summary
  gains run_id/title_variants/thumbnails/checklist. Verified: real render (8-scene explainer
  short, 67.3s, 43MB, audio+video) at concurrency=2 (no crash this run), pre-QC 0.82 PASS,
  post-QC PASS, 3 thumbnails + 3 A/B titles + checklist all produced. NOTE: rembg/onnx NOT
  installed on this machine, so parallax (Phase 2) and thumbnail cutout both degrade to flat
  stills / plain-bg — expected graceful path; install rembg to exercise them.
- Phase 4 Hook intelligence + QC gate: `faceless/plan/hook_lab.py` (`develop_hooks`: LLM
  drafts N candidate hooks per playbook `hook_formulas`, self-scores curiosity/specificity/
  stakes/scroll_stop, weighted pick → winner + A/B `alt`; logs all to `hooks.json`; offline
  fallback keeps the draft hook). Winner is pinned onto scene 1 via `write_script(..., hook=)`
  (`_prompt`/`_sanitize`/`_template` thread + force it). `faceless/plan/qc.py`: pre-render
  `gate()` scores hook(0.45)/pacing(0.30)/coherence(0.25), policy = hard fail on
  `blocked_terms`; below `qc.min_score` it asks the LLM for ONE targeted revision and keeps
  the higher-scoring version (`qc_report.json`); post-render `post_render_check()` verifies
  file exists+nontrivial, ffprobe duration within `qc.duration_tolerance` of spec, every scene
  has audio (`qc_post.json`). Config `qc:` block. Wired in `pipeline.py`; summary carries
  hook/hook_alt/qc_score/qc_passed/qc_post_passed. Verified: real 8-scene explainer short
  rendered (58.1s, 38.6MB, audio+video) — hook forged (winner 9.00 + alt), pre-QC 1.0 PASS,
  post-QC PASS. NOTE: Remotion tab OOM-crashed ("Page crashed!") at concurrency=2 on this
  1741-frame job; concurrency=1 rendered clean end-to-end (consider lowering the default or
  adding a retry in Phase I robustness work).
- Phase 2 Motion+Coherence: 2.5D parallax `faceless/assets/motion.py` (rembg fg cutout +
  blurred bg plate; matte cleaned with erode+feather `_clean_matte` to kill the rembg halo,
  applied ONLY after the coverage gate so flat scenes never pay it; parallax applied ONLY to
  scenes with real fg/bg separation — coverage band `MIN/MAX_COVERAGE` 0.06–0.72, else fall
  back to flat still + Ken Burns; graceful skip if rembg/onnx absent) rendered by Remotion
  `Layers.tsx` (differential fg/bg dolly); entrance transitions `Transitions.tsx`
  (fade/slide/whip/zoom/flash, per-playbook, no overlap so audio/captions stay frame-synced);
  animated emphasis captions `Captions.tsx` (clean/bold/brainrot presets, pop-on spring,
  lower/center); per-niche color grade `faceless/render/grade.py` + `Grade.tsx` (CSS filter +
  vignette + film grain, keyword-preset so it generalizes); image consistency in `images.py`
  (`run_seed` seed family + `compose_prompt` style anchor/negative, wired via
  `pipeline._visual_consistency`). Spec carries `scene.layers`, `render.{transitions,grade}`.
  Verified: real render (8-scene explainer short) + matte/selectivity checks (flat gradient
  skipped at coverage 0.00; composited fg-over-bg edge is clean, no halo).
- Phase 3 Mastery Engine: `playbooks/` (_base + 7 niches), `faceless/plan/mastery.py`
  (`get_playbook`: authored→LLM-synth+cache→nearest→base). Wired into pipeline/script/tts/subtitles/spec.
- Phase 1 Voice+Sound: voice ladder `faceless/assets/tts.py` (Chatterbox→Kokoro HF Spaces
  →Gemini TTS→edge-tts) + per-scene prosody; `faceless/assets/sfx.py` (procedural SFX →
  `assets_lib/sfx/`); `faceless/assets/music.py` (mood track or procedural bed); ffmpeg
  loudnorm; spec+Remotion (`Scene.tsx`/`Video.tsx`/`types.ts`) play per-scene SFX; caption
  per-word `emphasis` carried in spec.

## Remaining (one phase fully at a time; end each with a REAL render)
- Phase 7 optional AI-video clips + long-form (HF Space LTX/SVD, time-boxed, opt-in;
  long-form pacing/chapters polish). This is the last planned phase.
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
