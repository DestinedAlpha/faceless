# Faceless v2 — Roadmap to the Absolute Best Free Version

> **Goal:** generate faceless videos people *genuinely enjoy and finish* — on par with
> the best faceless YouTube/Shorts channels — while staying **100% free**, **cloud-only
> and light** (no local GPU, no heavy local renders), with **built-in mastery that
> generalizes to whatever niche the trend selector finds**, and a **learning loop that
> improves from the real analytics of videos you upload manually** (never auto-posts).
>
> This document is the spec for getting there. It is intentionally exhaustive. Nothing
> here compromises the "free + actually works" constraint: every provider named is free
> and has a reliable fallback, and any flaky free enhancement (e.g. AI video) is an
> *optional* layer that degrades to a rock-solid default.

---

## 0. Locked constraints & principles

**Constraints (from you):**
- 100% free, no paywalls, no card. Best quality *within* free.
- Cloud-only, light compute. No local GPU, no multi-hour local renders. CPU-only steps
  (rembg, Pillow, ffmpeg via Remotion) are fine because they're light.
- Niche mastery must cover **any and all** niches the selector picks — not one hardcoded vertical.
- Learn from **real performance analytics** of manually-uploaded videos. Manual upload only.

**Design principles that follow from those:**
1. **Retention is the only north star.** Every feature is justified by average-view-duration
   (AVD) / watch-through, swipe-away rate, and re-watch — not by looking cool in isolation.
2. **Reliable core, optional wow.** The default path must always produce a great video with
   zero flaky dependencies. Fancy free tools (AI video, cloud TTS spaces) are *enhancements*
   that fall back cleanly. A run must never fail because a free Space was queued/down.
3. **Mastery = an explicit, data-backed "playbook" per niche**, plus a generator that can
   *synthesize a playbook for a niche it has never seen*. This is how mastery generalizes.
4. **Everything flows through `video_spec.json`.** New capabilities extend the spec; the
   Python side stays the brain, Remotion stays the renderer. Keep the clean separation.
5. **Close the loop.** The system should get measurably better each week from its own results.

---

## 1. Where the current version tops out (honest baseline)

The v1 pipeline is solid and *works*, but its retention ceiling is capped by:

| Limitation | Why it hurts retention |
|---|---|
| Static AI stills + Ken Burns only | Reads slightly "slideshow"; no true motion/depth. Motion holds attention. |
| One image per scene (~4.5s) | Pacing too uniform/slow for many niches; no pattern interrupts. |
| edge-tts default voice | Competent but flat; emotion is a top-3 retention lever. |
| Per-scene independent image seeds | Character/style drifts between shots → feels incoherent. |
| Generic LLM hook/script prompts | Hooks are the single biggest retention factor and are only lightly engineered. |
| No music/SFX by default | Sound design drives energy and emotional pull. |
| Uniform captions | Good already, but no emphasis/animation tuned per beat. |
| **Open loop** | Never learns from what actually performed. Can't improve systematically. |
| No quality gate | Ships whatever it makes, including duds. |

v2 attacks each of these with a free, cloud-light approach.

---

## 2. Target architecture (v2)

```
faceless/
  config.yaml
  playbooks/                      # NEW: niche mastery packs (YAML), + a generated/ cache
    _base.yaml                    #   shared defaults every playbook inherits
    story-brainrot.yaml
    historical-pov.yaml
    explainer.yaml
    motivational.yaml
    ...                           #   one per known niche; unknown niches -> synthesized
  memory/                         # NEW: the learning store (what performed, learnings)
    performance.jsonl             #   one row per uploaded video's analytics snapshot
    learnings.md                  #   distilled, human-readable rules the LLM maintains
  faceless/
    trends/            (as today, + saturation/novelty checks)
    plan/
      mastery.py       # NEW: load/generate a niche playbook; inject into every prompt
      selector.py      # + retention-aware format choice, novelty/angle scoring
      hook_lab.py      # NEW: generate N hooks, self-score, pick the strongest
      script.py        # + retention-structured beats, driven by the playbook
      qc.py            # NEW: pre-render quality gate (script + spec sanity + score)
    assets/
      tts.py           # + Chatterbox/Kokoro cloud → Gemini TTS → edge-tts ladder, prosody
      subtitles.py     # + emphasis words, per-beat caption styling
      images.py        # + consistency (seed+style lock, character sheet), negative prompts
      motion.py        # NEW: 2.5D parallax (rembg depth layers) + optional AI-video clips
      broll.py         # (was stock.py) smarter keyword→clip matching, relevance filter
      music.py         # + mood-matched selection from a bundled CC library, auto-duck
      sfx.py           # NEW: cue → free SFX asset, timed to beats
      grade.py         # NEW: color grade / LUT-ish look per playbook (Remotion-side hints)
    render/
      spec.py          # extended schema (motion, layers, sfx, grade, caption styles)
      remotion.py      # (fixed) bridge
    publish/
      metadata.py      # + title A/B variants, description SEO, chapters (long-form)
      thumbnail.py     # + subject cutout composition, 2-3 variants, curiosity framing
      package.py       # NEW: assemble a clean review folder + an "upload checklist"
    learn/
      youtube_analytics.py  # NEW: OAuth + pull retention/CTR/AVD for your channel
      ingest.py             # NEW: map analytics → performance.jsonl
      reflect.py            # NEW: LLM turns performance history → updated playbooks/learnings
    core/               (as today, + provider health + quota guard + resumable runs)
  remotion/
    src/
      Root.tsx
      Video.tsx          # + music/sfx bed, grade layer, transition system
      Scene.tsx          # + 2.5D parallax layers, video-clip scenes, per-scene look
      Captions.tsx       # + emphasis, pop-on, position presets
      Transitions.tsx    # NEW: whip/zoom/flash/slide library (via @remotion/transitions)
      Layers.tsx         # NEW: foreground/background parallax renderer
    ...
  scripts/
    smoke_test.py        # (added)
    backfill_analytics.py  # NEW: one-off pull of past uploads
  assets_lib/
    music/               # bundled CC music, tagged by mood/bpm
    sfx/                 # bundled CC SFX (whoosh, riser, impact, click, ...)
    fonts/               # bundled caption/thumbnail fonts (licensed for embedding)
```

New top-level pipeline (per run):
`trends → selector(+playbook) → hook_lab → script(playbook-shaped) → QC gate →
voice(prosody) → captions(emphasis) → visuals(consistent) → motion(parallax/clip) →
music+sfx(mood) → grade → spec → render → thumbnail(variants) → metadata(+A/B) →
package(review + checklist)`. Separately, on demand: `learn: pull analytics → ingest →
reflect → update playbooks`.

---

## 3. The retention model (what actually makes videos enjoyable)

Encode these as first-class, measurable design targets. They drive the playbooks and the QC gate.

1. **The first 2 seconds decide everything.** Open on the single most curious/visually
   arresting frame + the hook line. No logos, no slow intro. Cold open.
2. **Open a loop, close it late.** State a question/stakes early; withhold the payoff to the end.
3. **Change something every 1.5–3s** (visual, motion, caption emphasis, SFX) — a "pattern
   interrupt" cadence tuned per niche. Stills that just sit are death.
4. **Motion + depth** beat flat pans. Even fake 2.5D parallax reads as "produced."
5. **Voice carries emotion.** Vary pace/energy; punch the hook and the payoff.
6. **Word-by-word captions with emphasis** on the key word of each beat. Most viewers watch muted.
7. **Sound design** (music bed matched to mood + BPM, SFX on cuts/reveals) raises perceived quality a lot.
8. **Coherence.** Consistent character/style/color across scenes so it feels like one piece.
9. **Payoff + loop.** End on a satisfying resolution and, for Shorts, a line that makes the
   first frame make *more* sense on re-watch (drives loops).
10. **Novelty.** Avoid over-saturated angles; the LLM must find a *fresh* take, not the obvious one.

---

## 4. Workstreams

Each has: **Goal → Why (retention) → Tasks → Free/cloud providers → Spec/plumbing →
Acceptance → Risks/fallback.**

### A. Niche Mastery Engine (the core of your ask)

**Goal.** For *any* niche the trend selector surfaces, produce content crafted to that
niche's proven conventions — not a one-size template.

**Why.** The best channels win by mastering a format's specific hook style, pacing, shot
grammar, caption look, music mood, and payoff structure. Mastery ≠ more words in a prompt;
it's an explicit, reusable, data-backed spec.

**Tasks.**
- Define a **Playbook schema** (`playbooks/*.yaml`) capturing, per niche:
  - `hook_formulas` (list of proven opening patterns + examples)
  - `structure` (beat map: e.g. hook → escalation → twist → payoff → loop line)
  - `pacing` (target seconds/scene, cuts-per-second, interrupt cadence, total length band)
  - `voice` (delivery style, energy curve, target WPM, SSML/prosody hints)
  - `visual` (art direction, palette, shot types, consistency rules, negative prompts)
  - `motion` (parallax intensity, when to use AI-video clips vs stills, transition set)
  - `captions` (style preset, emphasis rules, position)
  - `music` (mood tags, BPM band), `sfx` (which cues, where)
  - `thumbnail` (composition + text style), `title` (headline patterns), `cta`
  - `retention_targets` (expected AVD %, hook-hold %, etc. — updated by the learn loop)
- Author **starter playbooks** for the config's allowed niches (historical-pov, explainer,
  motivational, top-list, story-brainrot, science-facts, sports-facts).
- Build **`plan/mastery.py`**:
  - `get_playbook(niche)` → exact match, else **synthesize** one: the LLM, given the niche
    name + a few exemplar trending titles + the base schema + accumulated `learnings.md`,
    writes a new playbook, which is cached under `playbooks/generated/<niche>.yaml`. **This
    is what makes mastery generalize to unseen niches.**
  - Inject the resolved playbook into every downstream prompt (selector, hook_lab, script,
    voice, captions, music, thumbnail, metadata) so the whole run speaks that niche's language.
- Feed playbooks with real references: a curated, periodically-refreshed set of top-performing
  titles/structures per niche (from the trend + analytics data), so "mastery" is grounded in
  what's currently working, not just LLM priors.

**Providers.** Gemini/Groq (free) for synthesis. No new external deps.

**Spec/plumbing.** Playbook id + resolved parameters recorded in `selection.json` and echoed
into `video_spec.json.meta` for reproducibility.

**Acceptance.** Two runs of different niches produce visibly different pacing, caption style,
music mood, and structure — each matching that niche's convention. An unseen niche still gets a
coherent, sensible playbook.

**Risks/fallback.** Synthesized playbook could be generic → mitigate with the base schema +
few-shot exemplars + a validator that rejects empty/degenerate playbooks and falls back to the
closest known one.

---

### B. Script & Hook intelligence

**Goal.** Hooks that stop the scroll and scripts engineered for watch-through.

**Why.** Hook = the highest-leverage single lever. Structure keeps people to the payoff.

**Tasks.**
- **`plan/hook_lab.py`:** generate **N candidate hooks** (per the playbook's hook_formulas),
  then have the LLM **self-score** each on curiosity, specificity, stakes, and "scroll-stop"
  and pick the winner (or produce 2 for A/B). Log all candidates.
- Rework `script.py` to be **beat-structured from the playbook** (not a flat scene list):
  explicit hook / escalation / turn / payoff / loop-line beats, each with its retention role.
- Enforce **spoken-word pacing** precisely (WPM from playbook), and **write for the ear**
  (short clauses, concrete nouns, no filler). Add a "cut every dead word" pass.
- Add a **loop line** for Shorts (last line recontextualizes frame 1).
- **Novelty guard:** the selector/script checks the chosen angle against recent trend titles
  and `performance.jsonl` to avoid a saturated take; ask the LLM for a fresher angle if too similar.

**Providers.** Gemini primary, Groq fallback (free). Existing JSON-schema plumbing.

**Acceptance.** Hook candidates are visibly varied and the chosen one is the strongest; scripts
have a clear open-loop→payoff arc; measured AVD improves over v1 baseline (via learn loop).

**Risks.** LLM self-scoring bias → keep candidates in the log so the learn loop can validate
which hook *shapes* actually perform, and feed that back into hook_formulas.

---

### C. Voice & audio (expressive, free, cloud)

**Goal.** Emotive, natural narration + a full sound bed.

**Why.** Voice emotion and sound design are massive perceived-quality/retention levers.

**Tasks — voice ladder (all free):**
1. **Chatterbox** (expressive, emotion-exaggeration control) on a free HF Space / Colab —
   primary when reachable. ([Chatterbox is purpose-built for expressive TTS and beat ElevenLabs in its maker's blind test.](https://findskill.ai/blog/best-open-source-tts-2026/))
2. **Kokoro-82M** on a free HF Space — excellent, ultra-light natural narration, great default
   when Chatterbox is queued. ([Kokoro is the efficiency champion, ~free on CPU/T4.](https://localaimaster.com/blog/best-local-tts-models))
3. **Gemini AI Studio TTS** (free tier) — natural, no-GPU, another cloud option. ([Google's Gemini AI Studio offers free, natural TTS.](https://ocdevel.com/blog/20250720-tts))
4. **edge-tts** — always-works fallback with word boundaries.
- Add **prosody control**: per-beat energy/pace from the playbook (SSML where supported;
  edge rate/pitch otherwise). Punch the hook and payoff; soften mid-beats.
- Keep **word-level timings** working across the ladder: edge gives boundaries natively; for
  Chatterbox/Kokoro/Gemini use **Groq Whisper** forced alignment (free, 2000 req/day) — already scaffolded.

**Tasks — music & SFX:**
- **`assets/music.py`:** bundle a **CC/royalty-free music library** (`assets_lib/music/`) tagged
  by mood + BPM; select by the playbook's mood tags and match energy to pacing; auto-duck under
  narration (`duckDb`). Optional Pixabay Music search when a key exists.
- **`assets/sfx.py`:** bundle CC SFX (`whoosh/riser/impact/click/pop`), map script `sfx` cues to
  assets, and time them to scene cuts/reveals in the spec.
- **Audio mastering:** loudness-normalize narration, duck music, add gentle limiter (ffmpeg,
  light/CPU) so levels are consistent and "produced."

**Providers.** HF Spaces (Chatterbox/Kokoro), Gemini TTS, edge-tts, Groq Whisper — all free.
Music/SFX from bundled CC packs (+ optional Pixabay).

**Spec/plumbing.** `video_spec.json` gains `music{src,gain,bpm,mood}`, per-scene `sfx[]` with
frame-accurate timing, and per-scene voice engine metadata.

**Acceptance.** Narration sounds emotive and varies with the beat; music mood matches the niche;
SFX land on cuts; levels are consistent. Fallbacks proven via smoke test.

**Risks.** HF Spaces rate-limit/cold-start → health-check + timeout + immediate fallback to
Kokoro→edge. Never block a run on a Space.

---

### D. Motion & visuals (the biggest visual upgrade)

**Goal.** Replace "still + Ken Burns" with real depth, movement, coherence, and grade — free & light.

**Why.** Motion and coherence are what separate "AI slideshow" from "real faceless channel."

**Tasks — reliable core (no GPU):**
- **2.5D parallax (`assets/motion.py` + Remotion `Layers.tsx`):** use **rembg** (CPU, light) to
  cut the subject from each still, then render **foreground/background as separate layers** with
  a virtual camera dolly → genuine parallax depth. This alone makes stills feel 3D and alive.
- **Transition system (`Transitions.tsx` via `@remotion/transitions`):** whip-pan, zoom-punch,
  flash, slide — chosen per playbook and timed to beats/SFX (not a single global fade).
- **Motion tuned to audio:** subtle push-in on emphasis words / SFX hits; camera settles on payoff.

**Tasks — visual coherence:**
- **Consistency in `images.py`:** lock a **style string + seed family** per run; build a short
  **"character/style sheet"** (recurring subject descriptor) the LLM threads into every scene's
  image prompt so the subject/look stays consistent. Add **negative prompts** (no text artifacts,
  no watermarks, no extra fingers) and a **quality reject+retry** (re-generate a scene image if it
  fails a basic sanity check).
- **Provider ladder:** Pollinations (no key) primary; Cloudflare Flux backup — as today, plus the
  consistency layer on top.

**Tasks — optional AI-video enhancement (flaky → optional):**
- **`motion.py` AI-clip mode:** for 1–2 hero beats, optionally fetch a short **image-to-video**
  clip from a **free HF Space (LTX-Video / SVD)** to get true generative motion, with a strict
  timeout and **fallback to 2.5D parallax** if the Space is slow/down. Never on the critical path.
  ([Free image-to-video today = HF Spaces running LTX-Video (fastest) or SVD; treat as best-effort.](https://huggingface.co/Lightricks/LTX-Video)) Note SVD's community license is free under $1M revenue.
- **Smarter B-roll (`broll.py`):** keep Pexels/Pixabay, but add a **relevance filter** (reject
  off-topic clips) and orientation/length matching so stock actually fits the beat.

**Tasks — look/grade:**
- **`grade.py` + Remotion grade layer:** apply a per-playbook **color look** (contrast/saturation/
  vignette/film-grain via CSS/Remotion filters — free, GPU-free) so each niche has a signature look.

**Providers.** rembg (CPU), Remotion (`@remotion/transitions`), Pollinations/Cloudflare, HF Spaces
(optional), Pexels/Pixabay — all free.

**Spec/plumbing.** Scenes gain `layers[]` (fg/bg + depth), `transition{type,frames}`,
`clip{src}` (optional), `grade{...}`; motion keyframes tied to audio emphasis frames.

**Acceptance.** Side-by-side vs v1: scenes have depth and movement, transitions vary and hit on
SFX, subject/look is consistent across scenes, and each niche has a distinct grade — with the AI
clip layer fully optional and never breaking a run.

**Risks.** rembg edge artifacts → feather/matte cleanup; keep parallax subtle to hide seams. AI
Spaces unreliable → optional + timeout + fallback (already the rule).

---

### E. Captions (advanced karaoke)

**Goal.** Muted-viewing captions that guide the eye and punch key words.

**Why.** Most watch on mute; captions ARE the retention surface.

**Tasks.**
- **Emphasis detection:** mark the key word(s) per beat (LLM or heuristic) → bigger/colored/pop.
- **Style presets per playbook** (font, weight, outline, color, position — e.g. brainrot bottom-third
  bounce vs explainer clean top). Bundle fonts in `assets_lib/fonts/`.
- **Pop-on animation** synced to the spoken word (already word-timed) + optional shake/scale on emphasis.
- **Safe-area & readability**: auto-contrast scrim, never overlap the on-screen title.

**Providers.** None new (Remotion). Whisper/edge timings already available.

**Acceptance.** Key words visibly pop in time with speech; each niche's captions look distinct;
always legible on busy backgrounds.

---

### F. Thumbnail & packaging (CTR)

**Goal.** Thumbnails and titles that earn the click (long-form especially), plus a clean review handoff.

**Why.** For long-form, CTR × AVD is the whole game; even Shorts benefit from a strong first frame.

**Tasks.**
- **`thumbnail.py`:** subject **cutout (rembg) composited** on an AI background, bold text with the
  playbook's thumbnail style, **curiosity framing** (arrow/highlight/emoji-free-but-punchy), and
  **2–3 variants** so you can pick. Face/subject-forward when relevant.
- **`metadata.py`:** **title A/B variants** (playbook headline patterns), SEO description with
  front-loaded hook + hashtags, **chapters** for long-form, and tags from actual trend keywords.
- **`package.py`:** write a tidy `output/<run>/` with the video, thumbnail variants, metadata,
  and an **`UPLOAD_CHECKLIST.md`** (chosen title/thumb, description to paste, best-time-to-post hint,
  and the fields the learn loop will want you to report back).

**Acceptance.** Each run yields multiple title+thumbnail options and a paste-ready upload kit.

---

### G. Analytics learning loop (manual upload + learn)

**Goal.** Get measurably better every week from the real performance of videos *you* uploaded.

**Why.** This is the difference between "a generator" and "a system that masters niches." Open-loop
tools plateau; this one compounds.

**Tasks.**
- **`learn/youtube_analytics.py`:** OAuth (free, one-time consent) to **YouTube Data + Analytics
  APIs**; pull per-video **AVD, average view %, retention curve, CTR, impressions, likes/comments,
  subs gained**. (Google APIs are free; needs a one-time OAuth token stored locally.)
- **`learn/ingest.py`:** join each uploaded video back to its run (by a run-id you record at package
  time) and append a row to **`memory/performance.jsonl`** (niche, playbook params, hook shape,
  pacing, thumbnail variant chosen, and the metrics).
- **`learn/reflect.py`:** periodically, the LLM reads `performance.jsonl` + current playbooks and
  **updates**: hook_formulas (which shapes held attention), pacing targets, thumbnail/title patterns,
  and `retention_targets`. Writes distilled rules to **`memory/learnings.md`** (human-readable) and
  patches the relevant `playbooks/*.yaml`. Every future run inherits the lessons.
- **`scripts/backfill_analytics.py`:** one-off import of your existing uploads to seed the memory.
- **Guardrails:** never auto-upload; the loop only *reads* analytics and *updates playbooks*. You
  stay in control of what goes live.

**Providers.** Google/YouTube APIs (free, OAuth), Gemini/Groq for reflection.

**Acceptance.** After N uploads, `learnings.md` contains concrete, non-generic rules and the
playbooks visibly shift toward what performed; new runs reflect those changes.

**Risks.** OAuth setup friction (one-time) → document clearly. Small-sample overfitting → require a
minimum count before changing a parameter; keep changes conservative and logged/reversible.

---

### H. Quality gate (don't ship duds)

**Goal.** Catch weak outputs before they waste an upload slot.

**Tasks.**
- **`plan/qc.py` (pre-render):** score the script/spec on hook strength, pacing sanity (no dead
  scenes, cuts within band), coherence, and policy (blocked terms). Below threshold → **auto-revise
  or regenerate** the weak part (usually the hook or a flat beat) before rendering.
- **Post-render sanity:** verify duration matches spec, audio present, captions within safe area,
  no black frames; else flag in the summary.
- **Optional self-review:** feed the final script + first-frame + thumbnail to the LLM as a harsh
  "would you swipe?" critic; attach its verdict to the review folder.

**Acceptance.** Runs that would've been flat get caught and improved; the review folder includes a
QC verdict.

---

### I. Robustness & infra

**Goal.** Free tiers shift and Spaces flake; the system must shrug it off.

**Tasks.**
- **Provider health checks + circuit breaker:** ping/timeout each optional provider; skip fast to
  fallback; remember failures within a run.
- **Quota guards:** track YouTube units / Groq req / etc.; back off before hitting caps.
- **Resumable runs:** cache each stage's output (trends, script, audio, images) keyed by run-id so a
  failed render or a flaky Space doesn't redo everything.
- **Cost/latency budget:** keep the default path light; AI-video and cloud-TTS Spaces are opt-in and
  time-boxed.

**Acceptance.** Kill any single optional provider mid-run → the run still completes with a graceful
fallback and a clear log of what was substituted.

---

## 5. Phased roadmap (ordered by impact ÷ effort)

Do them roughly in this order; each phase ships an end-to-end improvement.

- **Phase 1 — Voice + Sound (biggest perceived-quality jump, low risk).**
  Voice ladder (Chatterbox/Kokoro/Gemini→edge) + prosody, music library + auto-duck, SFX on cuts,
  audio mastering. *Ship: same pipeline, dramatically better audio.*
- **Phase 2 — Motion + Coherence (biggest visual jump).**
  2.5D parallax via rembg + Remotion layers, transition system, image consistency (style/seed lock +
  character sheet + negative prompts), per-niche grade. *Ship: looks "produced," not slideshow.*
- **Phase 3 — Niche Mastery Engine.**
  Playbook schema + starter playbooks + `mastery.py` generalization + inject everywhere. *Ship:
  niche-appropriate everything.*
- **Phase 4 — Script/Hook intelligence + QC gate.**
  hook_lab, beat-structured scripts, novelty guard, pre/post QC. *Ship: stronger writing, fewer duds.*
- **Phase 5 — Packaging + Thumbnail/Title A/B.**
  Cutout thumbnails + variants, title A/B, chapters, upload checklist. *Ship: better CTR + clean handoff.*
- **Phase 6 — Analytics Learning Loop.**
  YouTube Analytics OAuth, ingest, reflect → playbook updates, backfill. *Ship: compounding improvement.*
- **Phase 7 — Optional AI-video hero clips + long-form polish.**
  HF Space LTX/SVD clips (time-boxed, optional), long-form pacing/chapters. *Ship: occasional true
  generative motion; long-form ready.*
- **Continuous — Robustness/infra** woven through every phase.

---

## 6. Provider matrix (all free, with fallbacks)

| Layer | Primary (free) | Fallback(s) (free) | Notes |
|---|---|---|---|
| LLM | Gemini 2.5 Flash | Groq Llama 3.3 70B | JSON schema, backoff (as today) |
| Voice | Chatterbox (HF Space) | Kokoro (HF Space) → Gemini TTS → **edge-tts** | edge always works; time-box Spaces |
| Word timings | edge boundaries | Groq Whisper large-v3-turbo | for non-edge engines |
| Images | Pollinations (no key) | Cloudflare Flux | + consistency + negative prompts |
| Motion | **2.5D parallax (rembg+Remotion)** | (optional) LTX/SVD HF Space clip | AI clip is opt-in, time-boxed |
| B-roll | Pexels | Pixabay | relevance-filtered |
| Music | bundled CC library | Pixabay Music (optional key) | mood/BPM tagged, auto-duck |
| SFX | bundled CC library | — | cue→asset, beat-timed |
| Thumbnail | Flux bg + rembg cutout + Pillow | gradient bg | 2–3 variants |
| Trends | YouTube Data API | Reddit (PRAW) → synthetic | + saturation/novelty |
| Analytics | YouTube Analytics API (OAuth) | — | read-only; manual upload |
| Render | Remotion (Node) | — | fixed bridge |

> **Verify-before-trust:** free Spaces (Chatterbox/Kokoro/LTX/SVD) and free-tier quotas move fast.
> The smoke test must probe each and the pipeline must fall back instantly — a queued Space is
> expected, not exceptional.

---

## 7. How we'll know it's actually better (metrics)

- **Primary:** average view duration / average-view-% and swipe-away rate on the first 3s (from the
  learn loop). Target: each phase moves these up on comparable niches.
- **Secondary:** CTR (long-form), re-watch/loop rate (Shorts), likes+comments per 1k views, subs gained.
- **Internal proxies (pre-upload):** QC hook score, cuts-per-second within playbook band, caption
  legibility, audio loudness consistency, image-consistency check.
- **Baseline:** keep v1 as a control; compare v2 outputs on the same topics.

---

## 8. Risks & honest limitations (not hidden)

- **Free cloud TTS/video Spaces are flaky** (queues, cold starts, occasional downtime). Mitigation:
  they're always optional with instant fallback to edge-tts / 2.5D parallax. Expressive-voice and
  true-AI-motion availability will *vary run to run* — the floor stays high, the ceiling is best-effort.
- **rembg cutouts aren't perfect** on complex images → keep parallax subtle; feather mattes.
- **LLM self-scoring/novelty is imperfect** until the learn loop has data → conservative changes,
  keep logs, require minimum sample sizes before adjusting playbooks.
- **Analytics OAuth is a one-time setup** and needs a channel with uploads to learn from.
- **"Best free" still trails paid** (ElevenLabs voice, Kling/Runway video) in raw fidelity; we close
  most of the *perceived* gap with sound design, motion, coherence, captions, and writing — the levers
  that actually move retention — rather than raw model fidelity.
- **Saturation risk:** trend-chasing can feel generic → the novelty guard + learn loop specifically
  fight this, but human taste on the final pick still helps.

---

## 9. Open questions for you (answer any; I'll proceed on sensible defaults otherwise)

1. **Channel(s):** Shorts-first (9:16) to start, and add long-form later? Or both from the outset?
2. **Language/voice:** English only, or multi-language? Any preferred narrator vibe (calm docu,
   hype, storyteller)?
3. **Music/SFX packs:** OK for me to bundle a curated CC library into `assets_lib/`? Any genre/mood
   preferences to bias toward?
4. **Analytics:** do you already have a channel with uploads to learn from (for backfill), and are you
   OK doing a one-time Google OAuth consent for the free Analytics API?
5. **Niche breadth:** any niches to hard-allow or hard-avoid beyond the current `deny_niches`?
6. **AI-video hero clips:** want me to include the optional LTX/SVD Space layer now (best-effort true
   motion), or defer until the 2.5D-parallax core is proven?

---

### TL;DR
Keep the reliable free core, then stack the levers that actually drive enjoyment and retention —
**expressive voice + sound design, real 2.5D motion + visual coherence, per-niche mastery playbooks
that generalize, engineered hooks, a quality gate, strong packaging, and a learning loop that
compounds from your real analytics** — every piece free, cloud-light, and fully fallback-guarded.
