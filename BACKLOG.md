# BACKLOG — feature ideas & requests

The running list of things to build/improve. All 7 planned phases are **done** (see
`CLAUDE.md`); everything here is optional future work. When you want one of these (or a
new idea), just say *"plan and implement <item>"* and the agent will follow the workflow
in `DEVELOPMENT.md` §0.

**Status legend:** `idea` → not scoped · `planned` → scoped below · `in-progress` ·
`done` (then move the record to `CLAUDE.md`).

### How to add an item (template)

```
### <short title>            [status: idea|planned|in-progress]
- **Goal:** what the user gets.
- **Why:** the payoff (retention/CTR/quality/reliability/effort).
- **Touches:** files/config/spec/playbook fields expected to change.
- **Fallback:** how it degrades when off/unavailable (must never break a run).
- **Acceptance:** the concrete check that proves it works (end with a real render).
```

---

## Open items

### Lower default render concurrency to avoid the OOM+retry            [status: idea]
- **Goal:** long (~1400-frame) renders stop failing once at `concurrency=2` before the
  auto-retry at 1.
- **Why:** faster, cleaner logs on long-form; removes a scary-looking WARNING.
- **Touches:** `config.yaml render.remotion_concurrency` (2→1), or make `remotion.py`
  auto-pick based on frame count / available RAM.
- **Fallback:** n/a (pure default change); keep the existing retry as a safety net.
- **Acceptance:** a long-form render completes first try, no exit-143 warning.

### Bundle a curated CC music/SFX library                              [status: idea]
- **Goal:** real mood-matched music beds instead of the procedural fallback.
- **Why:** production feel; music is a big retention lever.
- **Touches:** `assets_lib/music/` (files + a small tags manifest), `assets/music.py`
  (mood/BPM selection over the manifest).
- **Fallback:** keep procedural synthesis when no file matches.
- **Acceptance:** a run picks a real track by mood; narration-only still possible via
  `render.music.enabled: false`.

### Wire a real, reliable free AI-video Space                          [status: idea]
- **Goal:** turn on Phase 7 AI hero clips for real (currently off; needs a Space id).
- **Why:** occasional true generative motion on the hook/payoff beats.
- **Touches:** `config.yaml providers.aivideo.space` (+ maybe `api_name`); verify the
  Space's Gradio signature against `motion._predict_clip`'s result-unwrapping.
- **Fallback:** already built — time-box + fall back to 2.5D parallax/still.
- **Acceptance:** `smoke_test check_aivideo` PASSes and a run produces `ai_clips >= 1`
  that renders as motion.

### Smarter B-roll relevance filter                                     [status: idea]
- **Goal:** reject off-topic stock clips; match orientation/length to the beat.
- **Why:** stock currently takes the first hit; irrelevant clips hurt more than help.
- **Touches:** `assets/stock.py` (score candidates by keyword/orientation/duration).
- **Fallback:** current first-match behavior when scoring is inconclusive.
- **Acceptance:** given a beat, a clearly off-topic candidate is skipped in favor of a
  relevant one (unit-checkable with a stubbed response).

### Long-form deep-dive verification pass                               [status: idea]
- **Goal:** prove the new long-form pacing/chapters end-to-end with a real 3-5 min render.
- **Why:** Phase 7 long-form was unit-checked; a full long render hasn't been watched yet.
- **Touches:** none (verification only) — or minor pacing tuning if it reads slow.
- **Acceptance:** a `format: long` run renders, chapters land on real beats, pacing
  doesn't feel like a slideshow.
