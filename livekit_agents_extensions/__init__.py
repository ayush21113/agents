"""
LiveKit Agents Extensions
-------------------------
Custom extensions and utility handlers for LiveKit Agents.

This package currently includes:
- FillerInterruptHandler: Detects filler words (e.g., "uh", "umm") and valid interruptions
  (e.g., "stop", "cancel") during active speech to control TTS and transcription flow.

Usage:
    from livekit_agents_extensions import FillerInterruptHandler
"""

from .filler_interrupt_handler import FillerInterruptHandler

__all__ = ["FillerInterruptHandler"]
__version__ = "1.0.0"
