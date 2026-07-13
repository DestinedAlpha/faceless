"""End-to-end orchestration: trends -> selection -> script -> assets -> render.

This is the one place the whole pipeline is wired together. Every stage already
degrades gracefully on its own (provider fallbacks, template scripts, synthetic
trends), so `run()` produces *something* watchable even with zero API keys — just
edge-tts narration over Pollinations stills with karaoke captions.

Flow:
  1. discover ranked topics from real trends (or synthetic offline)
  2. the LLM selects topic + format + style; writes a scene-by-scene script
  3. TTS every scene (real audio durations drive the timeline)
  4. generate an AI still per scene (+ optional stock B-roll clip)
  5. build karaoke captions from word timings
  6. assemble video_spec.json, then render with Remotion
  7. write YouTube metadata + a thumbnail

Returns a summary dict; all artifacts land under output/<slug>/.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .assets import music as music_mod
from .assets import sfx as sfx_mod
from .assets import stock, subtitles, tts
from .assets import images
from .core.config import load_config
from .core.log import get_logger
from .core.util import slugify, write_json
from .plan import hook_lab, mastery, qc
from .plan.script import write_script
from .plan.selector import select
from .publish import metadata as metadata_mod
from .publish import package as package_mod
from .publish import thumbnail as thumbnail_mod
from .render.spec import build_spec
from .trends.finder import find_topics

log = get_logger(__name__)
_cfg = load_config()


def _dims(selection: dict) -> tuple[int, int]:
    fmt = _cfg.get(f"format.{selection['format']}", {})
    return int(fmt.get("width", 1080)), int(fmt.get("height", 1920))


def _visual_consistency(playbook: dict, selection: dict) -> tuple[str, str]:
    """Build the run-level (style_anchor, negative) threaded into every image prompt.

    The anchor locks art direction + palette + a short 'style sheet' line so the
    subject/look stays coherent across scenes; the negative suppresses the usual
    text/watermark/anatomy artifacts. Both come from the niche playbook (with base
    defaults), so this generalizes to any niche the selector picks.
    """
    v = (playbook or {}).get("visual", {})
    anchor_bits = [
        v.get("art_direction", ""),
        v.get("palette", ""),
        v.get("style_suffix", ""),
        v.get("consistency", ""),
        selection.get("style", ""),
    ]
    anchor = ", ".join(b.strip() for b in anchor_bits if b and b.strip())
    negative = v.get("negative", "") or (
        "text, watermark, logo, caption, extra fingers, deformed, blurry, low quality")
    return anchor, negative


def run(*, allow_synthetic: bool = True, skip_render: bool = False,
        skip_stock: bool = False) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    # 1. Trends -> ranked topics
    log.info("[pipeline] discovering trends...")
    topics = find_topics(allow_synthetic=allow_synthetic)
    if not topics:
        raise RuntimeError("no topics discovered (and synthetic disabled)")

    # 2. Selection + niche mastery playbook + engineered hook + script + QC gate
    selection = select(topics)
    playbook = mastery.get_playbook(selection["niche"], topics)
    # Hook lab: forge/score candidate hooks and pin the winner onto scene 1.
    hooks = hook_lab.develop_hooks(selection, playbook)
    script = write_script(selection, playbook, hook=hooks["winner"])
    # Pre-render quality gate: score, and auto-revise the weak parts if below threshold.
    script, qc_report = qc.gate(script, selection, playbook)

    slug = slugify(script.get("title_working") or selection["topic"])
    run_dir = _cfg.output_dir / f"{stamp}_{slug}"
    (run_dir / "audio").mkdir(parents=True, exist_ok=True)
    (run_dir / "img").mkdir(parents=True, exist_ok=True)
    (run_dir / "video").mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "selection.json", selection)
    write_json(run_dir / "playbook.json", playbook)
    write_json(run_dir / "hooks.json", hooks)
    write_json(run_dir / "qc_report.json", qc_report)
    write_json(run_dir / "script.json", script)
    log.info("[pipeline] '%s' -> %s (%s, %ss) -> %s", selection["topic"],
             selection["niche"], selection["format"],
             selection["target_seconds"], run_dir.name)

    scenes = script["scenes"]
    width, height = _dims(selection)
    portrait = height >= width

    # 3. Narration (real durations drive the whole timeline); voice per playbook
    scene_audio = tts.synth_scenes(scenes, run_dir / "audio",
                                   voice_cfg=playbook.get("voice"))

    # 4. Per-scene visuals: AI still (+ optional stock clip)
    #    Consistency (Phase 2): a locked style anchor + negative terms threaded into
    #    every prompt, and a seed family (one base seed + scene index) so the whole
    #    set shares a look/palette while composition varies scene to scene.
    want_stock = stock.available() and not skip_stock
    style_anchor, negative = _visual_consistency(playbook, selection)
    base_seed = images.run_seed(run_dir.name)
    want_parallax = float((playbook.get("motion") or {}).get("parallax_intensity", 0.0) or 0.0) > 0
    scene_assets: list[dict] = []
    staged: list[Path] = []
    for i, scene in enumerate(scenes):
        img_path = run_dir / "img" / f"scene_{i:02d}.jpg"
        image_name: str | None = None
        try:
            images.generate(scene["image_prompt"], img_path, width, height,
                            seed=base_seed + i, style_anchor=style_anchor, negative=negative)
            staged.append(img_path)
            image_name = img_path.name
        except Exception as exc:  # noqa: BLE001
            log.warning("[pipeline] scene %d image failed: %s", i, exc)

        # 2.5D parallax layers (rembg fg cutout + bg plate). Fully optional: any
        # failure or a missing dep just leaves the flat still + Ken Burns in place.
        layers = None
        if image_name and want_parallax:
            try:
                from .assets import motion  # lazy: rembg/onnx only when parallax is on
                layers = motion.build_layers(img_path, run_dir / "img", i)
                if layers:
                    staged.append(run_dir / "img" / layers["fg"])
                    staged.append(run_dir / "img" / layers["bg"])
            except Exception as exc:  # noqa: BLE001
                log.warning("[pipeline] scene %d parallax failed: %s", i, exc)
                layers = None

        video_name: str | None = None
        if want_stock:
            clip = run_dir / "video" / f"scene_{i:02d}.mp4"
            res = stock.fetch_broll(scene.get("stock_keywords", ""), clip, portrait=portrait)
            if res:
                staged.append(clip)
                video_name = clip.name

        scene_assets.append({"image": image_name, "video": video_name, "layers": layers})

    # 5. Captions from word timings (grouping + emphasis per playbook)
    captions = subtitles.build_captions(scene_audio, scenes, playbook)

    # 6. Sound design: per-scene SFX (synthesized library) + mood-matched music bed
    total_seconds = sum(sa["duration"] for sa in scene_audio)
    scene_sfx: list[str | None] = []
    if _cfg.get("render.sfx.enabled", True):
        sfx_mod.ensure_library()
        for scene in scenes:
            asset = sfx_mod.resolve(scene.get("sfx", ""))
            if asset:
                staged.append(Path(asset))
                scene_sfx.append(asset.name)
            else:
                scene_sfx.append(None)
    else:
        scene_sfx = [None] * len(scenes)

    music_path = music_mod.select(playbook, total_seconds, run_dir / "audio",
                                  seed=len(scene_audio))
    if music_path:
        staged.append(Path(music_path))
    staged += [Path(sa["audio"]) for sa in scene_audio]

    spec = build_spec(
        selection=selection, script=script, scene_audio=scene_audio,
        captions=captions, scene_assets=scene_assets,
        music=str(music_path) if music_path else None, playbook=playbook,
        scene_sfx=scene_sfx,
    )
    spec_path = write_json(run_dir / "video_spec.json", spec)

    # 7. Packaging (independent of render; always produced): metadata + title A/B,
    #    thumbnail variants (with a subject-forward hero cutout), upload checklist.
    meta = metadata_mod.generate(selection, script, playbook)
    write_json(run_dir / "metadata.json", meta)
    # Hero image for the subject-cutout thumbnail: prefer scene 1's still.
    hero = next((run_dir / "img" / sa["image"] for sa in scene_assets if sa.get("image")),
                None)
    try:
        thumbs = thumbnail_mod.generate_variants(meta, selection, run_dir, hero_image=hero)
    except Exception as exc:  # noqa: BLE001
        log.warning("[pipeline] thumbnail variants failed: %s", exc)
        thumbs = []
    thumb = thumbs[0] if thumbs else None

    summary = {
        "run_dir": str(run_dir),
        "run_id": run_dir.name,
        "title": meta["title"],
        "title_variants": meta.get("title_variants", []),
        "niche": selection["niche"],
        "format": selection["format"],
        "scenes": len(scenes),
        "duration_frames": spec["meta"]["durationInFrames"],
        "spec": str(spec_path),
        "thumbnail": str(thumb) if thumb else None,
        "thumbnails": [str(t) for t in thumbs],
        "video": None,
        "hook": hooks["winner"],
        "hook_alt": hooks.get("alt"),
        "qc_score": qc_report.get("score"),
        "qc_passed": qc_report.get("passed"),
    }

    # 8. Render
    if not skip_render:
        from .render import remotion  # lazy: only needs node when actually rendering
        out_mp4 = run_dir / f"{slug}.mp4"
        try:
            remotion.render(spec=spec, assets=staged, out_path=out_mp4)
            summary["video"] = str(out_mp4)
        except Exception as exc:  # noqa: BLE001
            log.error("[pipeline] render failed: %s", exc)
            summary["render_error"] = str(exc)
        # Post-render sanity gate (duration/audio/file) — flag, never crash.
        qc_post = qc.post_render_check(spec, scene_audio, summary["video"])
        write_json(run_dir / "qc_post.json", qc_post)
        summary["qc_post_passed"] = qc_post["passed"]
        if not qc_post["passed"]:
            summary["qc_post_issues"] = qc_post["issues"]
    else:
        log.info("[pipeline] skip_render set -> spec + assets ready, not rendered")
        qc_post = None

    # Paste-ready upload kit (title A/B, thumbnails, description, learn-loop fields).
    try:
        checklist = package_mod.write_checklist(
            run_dir, run_id=run_dir.name, selection=selection, script=script,
            metadata=meta, summary=summary, thumbnails=thumbs,
            qc_report=qc_report, qc_post=qc_post, hooks=hooks)
        summary["checklist"] = str(checklist)
    except Exception as exc:  # noqa: BLE001
        log.warning("[pipeline] checklist failed: %s", exc)

    write_json(run_dir / "summary.json", summary)
    log.info("[pipeline] done -> %s", run_dir)
    return summary
