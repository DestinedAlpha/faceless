"""JSON schemas for LLM-structured outputs (selection + script)."""
from __future__ import annotations

SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string", "description": "Refined, specific video topic"},
        "niche": {"type": "string", "description": "One of the allowed niches"},
        "format": {"type": "string", "enum": ["short", "long"]},
        "target_seconds": {"type": "integer"},
        "style": {"type": "string", "description": "Visual style/aesthetic direction"},
        "voice_style": {"type": "string", "description": "Delivery: e.g. suspenseful, upbeat"},
        "hook_angle": {"type": "string", "description": "The specific angle the hook plays on"},
        "rationale": {"type": "string", "description": "Why this topic+format wins, tied to trend signals"},
    },
    "required": ["topic", "niche", "format", "target_seconds", "style",
                 "voice_style", "hook_angle", "rationale"],
}

SCENE_SCHEMA = {
    "type": "object",
    "properties": {
        "narration": {"type": "string", "description": "What the voiceover says this scene"},
        "visual_direction": {"type": "string", "description": "What is on screen"},
        "image_prompt": {"type": "string", "description": "Text-to-image prompt for an AI still"},
        "stock_keywords": {"type": "string", "description": "Fallback stock B-roll search terms"},
        "on_screen_text": {"type": "string", "description": "Optional big on-screen title text"},
        "sfx": {"type": "string", "description": "Optional sound effect cue, or empty"},
        "duration": {"type": "number", "description": "Estimated seconds (refined later by TTS)"},
    },
    "required": ["narration", "visual_direction", "image_prompt", "stock_keywords",
                 "on_screen_text", "sfx", "duration"],
}

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title_working": {"type": "string"},
        "hook": {"type": "string", "description": "The first spoken line — must stop the scroll"},
        "scenes": {"type": "array", "items": SCENE_SCHEMA},
        "cta": {"type": "string", "description": "Closing call to action"},
    },
    "required": ["title_working", "hook", "scenes", "cta"],
}

METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Clickable YouTube title (<=100 chars)"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "thumbnail_text": {"type": "string", "description": "3-5 punchy words for the thumbnail"},
        "thumbnail_prompt": {"type": "string", "description": "Image prompt for thumbnail background"},
    },
    "required": ["title", "description", "tags", "thumbnail_text", "thumbnail_prompt"],
}
