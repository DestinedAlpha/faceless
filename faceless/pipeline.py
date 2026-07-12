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
from .plan import mastery
from .plan.script import write_script
from .plan.selector import select
from .publish import metadata as metadata_mod
from .publish import thumbnail as thumbnail_mod
from .render.spec import build_spec
from .trends.finder import find_topics

log = get_logger(__name__)
_cfg = load_config()


def _dims(selection: dict) -> tuple[int, int]:
    fmt = _cfg.get(f"format.{selection['format']}", {})
    return int(fmt.get("width", 1080)), int(fmt.get("height", 1920))


def run(*, allow_synthetic: bool = True, skip_render: bool = False,
        skip_stock: bool = False) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    # 1. Trends -> ranked topics
    log.info("[pipeline] discovering trends...")
    topics = find_topics(allow_synthetic=allow_synthetic)
    if not topics:
        raise RuntimeError("no topics discovered (and synthetic disabled)")

    # 2. Selection + niche mastery playbook + script
    selection = select(topics)
    playbook = mastery.get_playbook(selection["niche"], topics)
    script = write_script(selection, playbook)

    slug = slugify(script.get("title_working") or selection["topic"])
    run_dir = _cfg.output_dir / f"{stamp}_{slug}"
    (run_dir / "audio").mkdir(parents=True, exist_ok=True)
    (run_dir / "img").mkdir(parents=True, exist_ok=True)
    (run_dir / "video").mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "selection.json", selection)
    write_json(run_dir / "playbook.json", playbook)
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
    want_stock = stock.available() and not skip_stock
    scene_assets: list[dict] = []
    staged: list[Path] = []
    for i, scene in enumerate(scenes):
        img_path = run_dir / "img" / f"scene_{i:02d}.jpg"
        try:
            images.generate(scene["image_prompt"], img_path, width, height, seed=i + 1)
            staged.append(img_path)
            image_name: str | None = img_path.name
        except Exception as exc:  # noqa: BLE001
            log.warning("[pipeline] scene %d image failed: %s", i, exc)
            image_name = None

        video_name: str | None = None
        if want_stock:
            clip = run_dir / "video" / f"scene_{i:02d}.mp4"
            res = stock.fetch_broll(scene.get("stock_keywords", ""), clip, portrait=portrait)
            if res:
                staged.append(clip)
                video_name = clip.name

        scene_assets.append({"image": image_name, "video": video_name})

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

    # 7. Packaging (independent of render; always produced)
    meta = metadata_mod.generate(selection, script)
    write_json(run_dir / "metadata.json", meta)
    try:
        thumb = thumbnail_mod.generate(meta, selection, run_dir / "thumbnail.jpg")
    except Exception as exc:  # noqa: BLE001
        log.warning("[pipeline] thumbnail failed: %s", exc)
        thumb = None

    summary = {
        "run_dir": str(run_dir),
        "title": meta["title"],
        "niche": selection["niche"],
        "format": selection["format"],
        "scenes": len(scenes),
        "duration_frames": spec["meta"]["durationInFrames"],
        "spec": str(spec_path),
        "thumbnail": str(thumb) if thumb else None,
        "video": None,
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
    else:
        log.info("[pipeline] skip_render set -> spec + assets ready, not rendered")

    write_json(run_dir / "summary.json", summary)
    log.info("[pipeline] done -> %s", run_dir)
    return summary
