# DEVELOPMENT — how to extend Faceless

This is the guide for adding or changing features. It exists so that when you say
*"add feature X"* or *"improve Y"*, the coding agent (and you) already share a map of
where things live, what the rules are, and how a change gets planned → implemented →
verified. Read `CLAUDE.md` first (the project brief + the "Done" log); this file is the
*how-to-change-it* companion.

---

## 0. The workflow for a new feature

When you ask for a feature, the agent will:

1. **Plan in writing first.** Add an entry to `BACKLOG.md` (or a new phase in
   `BEST_VERSION_ROADMAP.md` for something large) describing: goal, why, the files it
   touches, the config/spec/playbook changes, the fallback, and the acceptance check.
   For anything non-trivial the agent should surface this plan for your OK before coding.
2. **Implement one feature at a time**, following the invariants in §2 and the
   layer map in §1.
3. **Verify** with the checklist in §4 — always ending with a **real render**.
4. **Record it** in `CLAUDE.md` under "Done (do not redo)" with a concrete verification
   line, and tick/close the `BACKLOG.md` entry.

You can always just say: *"plan feature X in the md files"* (stops after step 1 so you
can review) or *"plan and implement feature X"* (runs the whole loop).

---

## 1. Architecture map — where everything lives

The pipeline is one linear flow wired in `faceless/pipeline.py::run()`. Each stage
degrades on its own. Follow the data: **trends → selection → playbook → hook → script →
QC → assets → spec → render → packaging → (later) learn**.

```
faceless/
  trends/        discovery + scoring        finder.py  youtube.py  reddit.py  score.py  models.py
  plan/          decide + write + gate       selector.py  mastery.py  script.py  hook_lab.py  qc.py  schemas.py
  assets/        make the media              tts.py  subtitles.py  images.py  motion.py  stock.py  sfx.py  music.py
  render/        Python↔Remotion bridge      spec.py (build video_spec.json)  grade.py  remotion.py (invoke node)
  publish/       package for upload          metadata.py  thumbnail.py  package.py
  learn/         analytics → playbook edits  store.py  ingest.py  reflect.py  youtube_analytics.py
  core/          shared infra               config.py  http.py  log.py  util.py  fallback.py
  __main__.py    CLI (run|trends|plan|learn)
playbooks/       per-niche recipes          _base.yaml + <niche>.yaml  (generated/  learned/  overlays)
remotion/src/    the composition            Video.tsx  Scene.tsx  Layers.tsx  Transitions.tsx  Captions.tsx  Grade.tsx  types.ts
config.yaml      all tunables (NO topics)
scripts/         smoke_test.py  backfill_analytics.py
```

### The three contracts (touch these carefully — many stages depend on them)

- **`video_spec.json`** — the single Python↔Remotion contract, built in
  `render/spec.py`, consumed by `remotion/src/`. If you add a per-scene or per-render
  field you must update **both** `spec.py` (emit it) and `remotion/src/types.ts` (type it)
  and whichever `.tsx` consumes it. Keep asset fields as **basenames**; the bridge stages
  real files into `remotion/public/render/`.
- **The playbook schema** — `playbooks/_base.yaml` is the shape every niche inherits and
  every LLM-synthesized playbook is validated against (`plan/mastery.py::_validate` +
  `yaml_to_shape`). Add a knob here first so it generalizes to *all* niches.
- **The LLM JSON schemas** — `plan/schemas.py` (`SCRIPT_SCHEMA`, `METADATA_SCHEMA`, …).
  If you want a new field from the model, add it to the schema AND the sanitizer/fallback
  that guarantees it exists offline.

---

## 2. Invariants — never violate (from CLAUDE.md, enforced here)

1. **100% free, cloud-light.** No paid APIs, no card, no local GPU / heavy models.
2. **Every provider needs a free fallback.** A dead API, empty key, queued Space, or
   missing dep must degrade to a working path — never raise out of the pipeline. The
   pattern: `available()` gate → try in a `try/except` → `log.warning` → return
   `None`/template. See `core/fallback.py::try_providers` and how `assets/tts.py` and
   `assets/motion.py` use it.
3. **Niche mastery must generalize.** No hardcoded topic/niche behavior — new levers go
   in the playbook and are read generically so the selector can pick ANY niche.
4. **Analytics is manual-upload-only.** Never auto-post. The learn loop only ever
   *reads* and writes local overlay files.
5. **Optional/flaky layers are opt-in + time-boxed** (e.g. HF Spaces for TTS and
   AI-video). Off by default; a slow Space must fall back within its timeout.
6. **Windows-safe subprocess.** The repo path has a space ("yt thing"). Use
   `shutil.which`, `shell=False`, and list-args — see `render/remotion.py`.

---

## 3. Common change recipes

**Add a new provider to an existing layer** (e.g. another image or TTS source):
add an impl fn + register it in that module's provider ladder with an `available()`
gate, add its key to `.env.example` and its order to `config.yaml providers.<layer>.order`,
and add a `check_*` probe in `scripts/smoke_test.py`.

**Add a new per-scene visual/audio field:** emit it in `render/spec.py`, type it in
`remotion/src/types.ts` (+ `defaultSpec`), consume it in the relevant `.tsx`, and stage
the file by appending its `Path` to `staged` in `pipeline.py`.

**Add a new playbook lever** (pacing/voice/look/captions/motion): add it to
`playbooks/_base.yaml` (and the `_FALLBACK_BASE` in `mastery.py`), read it wherever it
applies, and — if the LLM should set it per-niche — include it in `yaml_to_shape` +
`_validate` clamps. Optionally let the learn loop tune it in `learn/reflect.py`.

**Add a new niche:** drop `playbooks/<niche>.yaml` overriding only what differs from
`_base.yaml`, and add it to `policy.allow_niches` in `config.yaml`. (Unknown niches are
auto-synthesized by `mastery.py`, so this is just for hand-tuned quality.)

**Add a CLI command/flag:** wire it in `faceless/__main__.py` (the `choices=[...]` list
and arg parsing), and document it in `README.md`.

**New standalone stage** (e.g. a "music mastering" or "translation" pass): add a module
under the right package, call it from `pipeline.py` at the correct point in the flow,
gate it behind config, and make it a no-op when disabled/unavailable.

---

## 4. Verification checklist (run before calling a feature done)

```bash
cd "C:\Users\syed_\Desktop\yt thing\faceless"
python -m compileall -q faceless scripts           # 1. Python compiles
cd remotion && npx tsc --noEmit -p tsconfig.json   # 2. Remotion typechecks
cd .. && python scripts/smoke_test.py              # 3. providers probe (SKIP = no key, OK)
python -m faceless                                 # 4. a REAL render — then WATCH the mp4
```

- Confirm the rendered `output/<run>/<slug>.mp4` exists, has audio+video
  (`ffprobe`), and its duration matches `video_spec.json` (post-render QC does this too).
- If you changed a spec/playbook/schema field, add a targeted offline check (like the
  ones used for chapter derivation and long-form pacing).
- **Known quirk:** Remotion can tab-OOM at `concurrency=2` on long (~1400-frame) jobs
  (exit 143); the bridge auto-retries at `concurrency=1` and renders clean. Not a
  regression.

---

## 5. Planning docs

- **`BEST_VERSION_ROADMAP.md`** — the north-star design + the original 7-phase plan and
  provider matrix. Add *large* new initiatives here as a new "Phase 8+".
- **`BACKLOG.md`** — the running list of smaller ideas/feature requests with enough
  detail to pick up later. This is the default place to capture a "someday" ask.
- **`CLAUDE.md`** — the brief + the authoritative "Done" log. Every shipped change gets a
  concrete, verified entry here so nothing is redone by accident.
