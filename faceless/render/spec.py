"""Assemble video_spec.json — the single contract between Python and Remotion.

Scene durations are driven by the *actual* TTS audio length (not LLM estimates),
so audio and visuals always stay in sync. Timings are emitted in both seconds and
frames. Asset fields are basenames only; the Remotion bridge stages the real files
under remotion/public/render/ and the composition resolves them via staticFile().
"""
from __future__ import annotations

from pathlib import Path

from ..core.config import load_config
from ..core.log import get_logger
from . import grade as grade_mod

log = get_logger(__name__)
_cfg = load_config()


def _ken_burns(index: int, zoom: float) -> dict:
    """Alternate zoom-in/out and pan direction per scene for visual variety."""
    zoom_in = index % 2 == 0
    from_s, to_s = (1.0, 1.0 + zoom) if zoom_in else (1.0 + zoom, 1.0)
    pan_x = (0.02 if index % 3 == 0 else -0.02)
    pan_y = (-0.02 if index % 2 == 0 else 0.015)
    return {"fromScale": round(from_s, 4), "toScale": round(to_s, 4),
            "panX": pan_x, "panY": pan_y}


def build_spec(*, selection: dict, script: dict, scene_audio: list[dict],
               captions: list[dict], scene_assets: list[dict],
               music: str | None, playbook: dict | None = None,
               scene_sfx: list | None = None) -> dict:
    pb = playbook or {}
    kind = selection["format"]
    fmt = _cfg.get(f"format.{kind}", {})
    width = int(fmt.get("width", 1080))
    height = int(fmt.get("height", 1920))
    fps = int(_cfg.get("format.fps", 30))
    zoom = float(_cfg.get("render.ken_burns_zoom", 0.12))
    # Transition + caption look come from the niche playbook when present.
    pb_motion = pb.get("motion", {})
    trans_list = [t for t in (pb_motion.get("transitions") or []) if t] \
        or [_cfg.get("render.transition", "fade")]
    trans = trans_list[0]
    trans_frames = int(_cfg.get("render.transition_frames", 12))
    pb_caps = pb.get("captions", {})

    scenes_out: list[dict] = []
    frame_cursor = 0
    for i, sa in enumerate(scene_audio):
        dur_s = max(sa["duration"], 1.0)
        dur_frames = max(1, round(dur_s * fps))
        asset = scene_assets[i]
        scene_src = script["scenes"][i] if i < len(script["scenes"]) else {}
        scenes_out.append({
            "index": i,
            "startSeconds": round(frame_cursor / fps, 3),
            "durationSeconds": round(dur_s, 3),
            "startFrame": frame_cursor,
            "durationFrames": dur_frames,
            "image": asset.get("image"),
            "video": asset.get("video"),
            "clip": asset.get("clip"),
            "layers": asset.get("layers"),
            "audio": Path(sa["audio"]).name,
            "onScreenText": scene_src.get("on_screen_text", "") or "",
            "sfx": scene_src.get("sfx", "") or "",
            "sfxSrc": (scene_sfx[i] if scene_sfx and i < len(scene_sfx) else None),
            "kenBurns": _ken_burns(i, zoom),
        })
        frame_cursor += dur_frames

    total_frames = max(frame_cursor, 1)

    # Convert caption groups to frame-based tokens for Remotion (carry emphasis).
    cap_out = []
    for g in captions:
        cap_out.append({
            "startFrame": round(g["start"] * fps),
            "endFrame": round(g["end"] * fps),
            "words": [{"word": w["word"],
                       "startFrame": round(w["start"] * fps),
                       "endFrame": round(w["end"] * fps),
                       "emphasis": bool(w.get("emphasis", False))} for w in g["words"]],
        })

    spec = {
        "meta": {
            "kind": kind,
            "width": width,
            "height": height,
            "fps": fps,
            "durationInFrames": total_frames,
            "title": script.get("title_working", selection["topic"]),
            "niche": selection["niche"],
            "style": selection.get("style", ""),
            "playbook": pb.get("niche", selection["niche"]),
        },
        "scenes": scenes_out,
        "captions": cap_out,
        "music": Path(music).name if music else None,
        "render": {
            "transition": trans,
            "transitions": trans_list,
            "transitionFrames": trans_frames,
            "captionsEnabled": bool(_cfg.get("render.captions.enabled", True)),
            "captionFontFamily": pb_caps.get("font_family")
                                 or _cfg.get("render.captions.font_family", "Inter"),
            "captionStyle": pb_caps.get("style", "clean"),
            "captionPosition": pb_caps.get("position", "lower"),
            "parallaxIntensity": float(pb_motion.get("parallax_intensity", 0.0) or 0.0),
            "grade": grade_mod.resolve(pb, selection["niche"]),
            "duckDb": float(_cfg.get("render.music.duck_db", -14)),
            "sfxEnabled": bool(_cfg.get("render.sfx.enabled", True)),
            "sfxGainDb": float(_cfg.get("render.sfx.gain_db", -8)),
        },
    }
    log.info("[spec] %d scenes, %d frames (%.1fs @ %dfps)", len(scenes_out),
             total_frames, total_frames / fps, fps)
    return spec
