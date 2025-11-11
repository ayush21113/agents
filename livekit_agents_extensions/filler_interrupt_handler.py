"""
Filler-aware interruption handler for LiveKit Agents.

Enhanced version with proper TTS interruption capabilities.
"""

import asyncio
import logging
import os
import re
from typing import Callable, Iterable, Optional, Set, Dict, List

logger = logging.getLogger("filler_interrupt_handler")
logger.setLevel(os.getenv("FILLER_HANDLER_LOG_LEVEL", "INFO"))

# Default filler set (can be overridden via env or runtime)
DEFAULT_IGNORED_WORDS = {"uh", "umm", "hmm", "haan", "uhh", "uhm", "erm", "ah", "mm", "mmh", "mhmm"}

# Words that should always be treated as forcing a stop if present
DEFAULT_FORCE_STOP_WORDS = {"stop", "wait", "hold", "pause", "no", "halt", "end", "shut up", "be quiet"}

# A simple normalizer to strip punctuation and lowercase
_TOKEN_RE = re.compile(r"[^\w']+", re.UNICODE)

def normalize_text(text: str) -> str:
    return _TOKEN_RE.sub(" ", text or "").strip().lower()

def tokenize(text: str) -> Iterable[str]:
    return [t for t in normalize_text(text).split() if t]

class FillerInterruptHandler:
    """
    Enhanced handler with proper TTS interruption capabilities.
    """

    def __init__(
        self,
        ignored_words: Optional[Iterable[str]] = None,
        force_stop_words: Optional[Iterable[str]] = None,
        min_confidence_to_consider: float = 0.5,
        ignore_if_confidence_below: float = 0.4,
        logger_name: str = "filler_interrupt_handler",
    ):
        self.ignored_words: Set[str] = set(w.lower() for w in (ignored_words or DEFAULT_IGNORED_WORDS))
        self.force_stop_words: Set[str] = set(w.lower() for w in (force_stop_words or DEFAULT_FORCE_STOP_WORDS))
        self.min_confidence_to_consider = float(min_confidence_to_consider)
        self.ignore_if_confidence_below = float(ignore_if_confidence_below)
        self.agent_speaking = False
        self.lock = asyncio.Lock()
        self._callbacks: Dict[str, List[Callable]] = {
            "valid_interruption": [],
            "ignored_filler": [],
            "speech_registered": []
        }
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(os.getenv("FILLER_HANDLER_LOG_LEVEL", "INFO"))

    # ---------- Public API for attaching callbacks ----------
    def on_valid_interruption(self, cb: Callable[[str, dict], None]):
        """Callback invoked when a valid interruption is detected. cb(text, metadata)"""
        self._callbacks["valid_interruption"].append(cb)

    def on_ignored_filler(self, cb: Callable[[str, dict], None]):
        """Callback invoked when filler-only input is ignored while agent was speaking."""
        self._callbacks["ignored_filler"].append(cb)

    def on_speech_registered(self, cb: Callable[[str, dict], None]):
        """Callback invoked when speech should be registered/handled (agent quiet or valid speech)."""
        self._callbacks["speech_registered"].append(cb)

    # ---------- Tools to update config dynamically ----------
    async def update_ignored_words(self, new_list: Iterable[str]):
        async with self.lock:
            self.ignored_words = set(w.lower() for w in new_list)
            self.logger.info(f"Ignored words updated: {sorted(self.ignored_words)}")

    async def update_force_stop_words(self, new_list: Iterable[str]):
        async with self.lock:
            self.force_stop_words = set(w.lower() for w in new_list)
            self.logger.info(f"Force-stop words updated: {sorted(self.force_stop_words)}")

    # ---------- State management ----------
    async def set_agent_speaking(self, speaking: bool):
        """Update agent speaking state - use this from TTS start/stop events"""
        async with self.lock:
            self.agent_speaking = speaking
            self.logger.debug(f"Agent speaking state: {speaking}")

    # ---------- Event processing ----------
    async def _on_tts_start(self, *args, **kwargs):
        await self.set_agent_speaking(True)

    async def _on_tts_end(self, *args, **kwargs):
        await self.set_agent_speaking(False)

    async def handle_transcript(self, text: str, confidence: Optional[float] = None, words: Optional[list] = None, metadata: Optional[dict] = None):
        """
        Core decision logic - processes transcript and triggers appropriate callbacks.
        """
        metadata = metadata or {}
        text = (text or "").strip()
        if not text:
            return

        tokens = tokenize(text)
        
        # Compute overall confidence
        avg_conf = confidence if confidence is not None else 1.0
        if words:
            confidences = [w.get("confidence", 1.0) for w in words if isinstance(w, dict)]
            if confidences:
                avg_conf = sum(confidences) / len(confidences)

        async with self.lock:
            agent_speaking = self.agent_speaking

        # If agent is speaking, filter using filler-word policy
        if agent_speaking:
            self.logger.debug(f"Agent speaking; evaluating transcript='{text}', tokens={tokens}, avg_conf={avg_conf:.3f}")
            
            # Very low confidence => treat as background/murmur -> ignore
            if avg_conf < self.ignore_if_confidence_below:
                self.logger.info("Ignoring low-confidence background/murmur while agent speaks.")
                for cb in self._callbacks["ignored_filler"]:
                    cb(text, {"reason": "low_confidence", "avg_conf": avg_conf, **metadata})
                return

            # Check for forced stop words (highest priority)
            has_force_stop = any(t in self.force_stop_words for t in tokens)
            if has_force_stop:
                self.logger.info(f"VALID INTERRUPTION (force-stop word): '{text}'")
                for cb in self._callbacks["valid_interruption"]:
                    cb(text, {"reason": "force_stop_word", "avg_conf": avg_conf, **metadata})
                return

            # Check if only filler words
            non_ignored_tokens = [t for t in tokens if t not in self.ignored_words]
            if not non_ignored_tokens:
                # Only filler words - ignore
                self.logger.info(f"Filler-only sound ignored: '{text}'")
                for cb in self._callbacks["ignored_filler"]:
                    cb(text, {"reason": "filler_only", "avg_conf": avg_conf, **metadata})
                return
            else:
                # Mixed filler + real speech => valid interrupt
                self.logger.info(f"VALID INTERRUPTION (non-filler content): '{text}'")
                for cb in self._callbacks["valid_interruption"]:
                    cb(text, {"reason": "mixed_tokens", "non_ignored": non_ignored_tokens, "avg_conf": avg_conf, **metadata})
                return
        else:
            # Agent is quiet -> register speech normally
            self.logger.debug(f"Agent quiet; registering speech: '{text}'")
            for cb in self._callbacks["speech_registered"]:
                cb(text, {"reason": "agent_quiet", "avg_conf": avg_conf, **metadata})