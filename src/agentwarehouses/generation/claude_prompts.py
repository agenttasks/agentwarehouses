"""Claude Opus 4.6 integration for cinematic prompt generation.

Uses the Anthropic SDK to generate detailed video prompts suitable for
Veo 3.1 generation, with style-aware formatting and audio direction.
"""

from __future__ import annotations

import os
from typing import Any

import anthropic

from agentwarehouses.models.video import (
    CinematicPromptRequest,
    CinematicPromptResponse,
    PromptStyle,
)

# Style-specific system prompt fragments
_STYLE_DIRECTIONS: dict[PromptStyle, str] = {
    PromptStyle.CINEMATIC: (
        "You are a cinematographer writing shot descriptions. "
        "Use vivid visual language: camera movements (dolly, crane, steadicam), "
        "lighting (golden hour, chiaroscuro, neon), and composition (rule of thirds, "
        "leading lines). Every frame should tell a story."
    ),
    PromptStyle.DOCUMENTARY: (
        "You are a documentary filmmaker. Write observational, grounded descriptions. "
        "Focus on authentic moments, natural lighting, and handheld camera feel. "
        "Include environmental sounds and ambient audio."
    ),
    PromptStyle.COMMERCIAL: (
        "You are directing a high-end product commercial. Write polished, aspirational "
        "descriptions with smooth camera movements, studio lighting, and clean "
        "compositions. Focus on product details and lifestyle imagery."
    ),
    PromptStyle.MUSIC_VIDEO: (
        "You are directing a music video. Write dynamic, rhythm-driven descriptions "
        "with quick cuts, bold colors, dramatic angles, and choreographed movement. "
        "Sync visual beats to implied musical rhythm."
    ),
    PromptStyle.VLOG: (
        "You are creating an authentic vlog-style video. Write casual, personal "
        "descriptions with selfie angles, natural lighting, real locations, "
        "and conversational energy. Include direct-to-camera moments."
    ),
}

_SYSTEM_PROMPT = """You generate detailed video prompts for Google Veo 3.1 AI video generation.

{style_direction}

Rules:
- Output ONLY the prompt text, no preamble or explanation.
- Target duration: {duration}s. Pace the action accordingly.
- Describe visual content frame-by-frame when possible.
- Include specific camera movements, lighting, and color palette.
{audio_line}
- Keep under 2000 characters for optimal Veo 3.1 performance.
- Use present tense, active voice."""

_AUDIO_DIRECTION = "- Include audio/sound design direction (ambient sounds, music style, foley)."
_NO_AUDIO = "- Do NOT include audio direction; video will be silent or have separate audio."


class CinematicPromptGenerator:
    """Generates cinematic video prompts using Claude Opus 4.6."""

    def __init__(self, api_key: str | None = None, model: str = "claude-opus-4-6") -> None:
        self._client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self._model = model

    def generate(self, request: CinematicPromptRequest) -> CinematicPromptResponse:
        """Generate a cinematic prompt from a topic description."""
        system = _SYSTEM_PROMPT.format(
            style_direction=_STYLE_DIRECTIONS[request.style],
            duration=request.duration_seconds,
            audio_line=_AUDIO_DIRECTION if request.include_audio_direction else _NO_AUDIO,
        )

        message = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": request.topic}],
        )

        prompt_text = message.content[0].text
        usage: dict[str, Any] = {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        }
        if hasattr(message.usage, "cache_read_input_tokens"):
            usage["cache_read_input_tokens"] = message.usage.cache_read_input_tokens
        if hasattr(message.usage, "cache_creation_input_tokens"):
            usage["cache_creation_input_tokens"] = message.usage.cache_creation_input_tokens

        return CinematicPromptResponse(
            prompt=prompt_text,
            style=request.style,
            model_used=self._model,
            usage=usage,
        )

    def generate_with_negative(self, request: CinematicPromptRequest) -> CinematicPromptResponse:
        """Generate both a prompt and a negative prompt for better Veo 3.1 results."""
        system = _SYSTEM_PROMPT.format(
            style_direction=_STYLE_DIRECTIONS[request.style],
            duration=request.duration_seconds,
            audio_line=_AUDIO_DIRECTION if request.include_audio_direction else _NO_AUDIO,
        )

        message = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=system,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"{request.topic}\n\n"
                        "After the main prompt, on a new line starting with 'NEGATIVE:', "
                        "list what to avoid (artifacts, distortions, unwanted elements)."
                    ),
                }
            ],
        )

        raw = message.content[0].text
        if "NEGATIVE:" in raw:
            parts = raw.split("NEGATIVE:", 1)
            prompt_text = parts[0].strip()
            negative = parts[1].strip()
        else:
            prompt_text = raw.strip()
            negative = None

        usage: dict[str, Any] = {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        }

        return CinematicPromptResponse(
            prompt=prompt_text,
            negative_prompt=negative,
            style=request.style,
            model_used=self._model,
            usage=usage,
        )
