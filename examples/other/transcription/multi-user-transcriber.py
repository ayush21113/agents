import asyncio
import logging
import traceback
from dotenv import load_dotenv

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    RoomInputOptions,
    RoomIO,
    RoomOutputOptions,
    StopResponse,
    WorkerOptions,
    cli,
    llm,
    utils,
)
from livekit.agents.tts import StreamAdapter
from livekit.plugins import deepgram, silero, elevenlabs
from livekit_agents_extensions.filler_interrupt_handler import FillerInterruptHandler

# ==============================================================
# LOGGING SETUP
# ==============================================================
load_dotenv()
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("transcriber")


# ==============================================================
# ENHANCED AGENT: With interruption handling but SAME TTS approach
# ==============================================================
class Transcriber(Agent):
    def __init__(self, *, participant_identity: str, tts=None, room_io=None, handler=None):
        super().__init__(instructions="not-needed", stt=deepgram.STT(), tts=tts)
        self.participant_identity = participant_identity
        self.room_io = room_io
        self.handler = handler
        self._agent_session = None
        self._is_speaking = False  # Track speaking state for interruptions
        logger.debug(f"[INIT] Transcriber created for {participant_identity}")

    async def stop_speaking(self):
        """Stop TTS immediately when interruption is detected"""
        self._is_speaking = False
        logger.info(f"[INTERRUPTION] TTS stopped for {self.participant_identity}")

    async def on_user_turn_completed(self, chat_ctx: llm.ChatContext, new_message: llm.ChatMessage):
        """Triggered after user finishes speaking."""
        user_transcript = new_message.text_content
        logger.info(f"{self.participant_identity} -> {user_transcript}")

        # Check if this should interrupt current speech
        if self._is_speaking and self.handler:
            should_interrupt = await self._check_interruption(user_transcript)
            if should_interrupt:
                await self.stop_speaking()
                # Don't process this speech - it was an interruption
                raise StopResponse()

        response_text = f"Got it. You said: {user_transcript[:200]}"

        try:
            if self.tts and self._agent_session and not self._is_speaking:
                logger.debug(f"[TTS] Generating response for {self.participant_identity}: {response_text}")

                # Set speaking state BEFORE starting TTS
                self._is_speaking = True
                if self.handler:
                    await self.handler.set_agent_speaking(True)

                # ✅ USE THE WORKING APPROACH: session.say() 
                await self._agent_session.say(response_text)
                
                # Reset speaking state AFTER TTS completes
                self._is_speaking = False
                if self.handler:
                    await self.handler.set_agent_speaking(False)
                    
                logger.info(f"[TTS] Finished speaking for {self.participant_identity}")
            else:
                missing = []
                if not self.tts: missing.append("tts")
                if not self._agent_session: missing.append("session")
                if self._is_speaking: missing.append("already_speaking")
                logger.warning(f"[TTS not available] Missing: {missing}. Response would be: {response_text}")

        except Exception as e:
            logger.error(f"[TTS ERROR] {e}")
            traceback.print_exc()
            self._is_speaking = False
            if self.handler:
                await self.handler.set_agent_speaking(False)

        raise StopResponse()

    async def _check_interruption(self, text: str) -> bool:
        """Check if text should interrupt current speech - SIMPLE VERSION"""
        if not self.handler:
            return False
            
        text_lower = text.lower()
        
        # Check for force-stop words
        force_stop_words = ["stop", "wait", "pause", "end", "terminate", "shut up", "be quiet", "halt"]
        if any(stop in text_lower for stop in force_stop_words):
            logger.info(f"[INTERRUPTION DETECTED] Force-stop word: '{text}'")
            return True
            
        # Check if it's not just filler words
        ignored_words = ["uh", "umm", "hmm", "haan", "uhh", "uhm"]
        tokens = [t for t in text_lower.split() if t]
        non_filler = [t for t in tokens if t not in ignored_words]
        if non_filler:
            logger.info(f"[INTERRUPTION DETECTED] Non-filler content: '{text}'")
            return True
            
        return False


# ==============================================================
# ENHANCED CONTROLLER: With per-participant interruption handlers
# ==============================================================
class MultiUserTranscriber:
    def __init__(self, ctx: JobContext):
        self.ctx = ctx
        self._sessions: dict[str, AgentSession] = {}
        self._agents: dict[str, Transcriber] = {}  # Track agents for interruption handling
        self._tasks: set[asyncio.Task] = set()
        logger.debug("[INIT] MultiUserTranscriber initialized.")

    # ==============================================================
    # Participant Lifecycle
    # ==============================================================
    def start(self):
        logger.debug("[START] MultiUserTranscriber started.")
        self.ctx.room.on("participant_connected", self.on_participant_connected)
        self.ctx.room.on("participant_disconnected", self.on_participant_disconnected)

    async def aclose(self):
        logger.debug("[CLOSE] Shutting down all sessions.")
        await utils.aio.cancel_and_wait(*self._tasks)
        await asyncio.gather(*[self._close_session(s) for s in list(self._sessions.values())])

    def on_participant_connected(self, participant: rtc.RemoteParticipant):
        if participant.identity in self._sessions:
            return
        logger.info(f"[ROOM] New participant joined: {participant.identity}")
        task = asyncio.create_task(self._start_session(participant))
        self._tasks.add(task)
        task.add_done_callback(lambda t: self._tasks.discard(task))

    def on_participant_disconnected(self, participant: rtc.RemoteParticipant):
        sess = self._sessions.pop(participant.identity, None)
        agent = self._agents.pop(participant.identity, None)
        if sess:
            logger.info(f"[ROOM] Participant left: {participant.identity}")
            asyncio.create_task(self._close_session(sess))

    # ==============================================================
    # Session Setup with Interruption Handler
    # ==============================================================
    async def _start_session(self, participant: rtc.RemoteParticipant) -> AgentSession:
        try:
            logger.debug(f"[SESSION START] Setting up session for {participant.identity}")
            session = AgentSession(vad=self.ctx.proc.userdata["vad"])
            room_io = RoomIO(
                agent_session=session,
                room=self.ctx.room,
                participant=participant,
                input_options=RoomInputOptions(text_enabled=False),
                output_options=RoomOutputOptions(transcription_enabled=True, audio_enabled=True),
            )
            await room_io.start()

            # === Initialize ElevenLabs TTS ===
            tts = None
            try:
                tts = elevenlabs.TTS(
                    api_key="sk_bcdee9936c01b819ad9a831f44246d77d6ebd7ef998edb63",
                    model="eleven_flash_v2_5"
                )
                logger.info(f"[TTS] ElevenLabs TTS ready for {participant.identity}")
            except Exception as e:
                logger.error(f"[TTS INIT ERROR] {e}")
                traceback.print_exc()

            # === Create interruption handler for this participant ===
            handler = FillerInterruptHandler(
                ignored_words=["uh", "umm", "hmm", "haan", "uhh", "uhm"],
                force_stop_words=["stop", "wait", "pause", "end", "terminate", "shut up", "be quiet", "halt"],
                ignore_if_confidence_below=0.35,
            )

            # Set up interruption callbacks
            handler.on_valid_interruption(lambda t, m: self._handle_interruption(participant.identity, t, m))
            handler.on_ignored_filler(lambda t, m: logger.debug(f"[IGNORED FILLER] {participant.identity}: {t}"))
            handler.on_speech_registered(lambda t, m: logger.debug(f"[SPEECH REGISTERED] {participant.identity}: {t}"))

            # Create the agent with handler
            transcriber_agent = Transcriber(
                participant_identity=participant.identity, 
                tts=tts, 
                room_io=room_io,
                handler=handler
            )
            
            # Start the agent
            await session.start(agent=transcriber_agent)
            
            # Store references
            transcriber_agent._agent_session = session
            self._sessions[participant.identity] = session
            self._agents[participant.identity] = transcriber_agent

            # === Attach STT listener to handler ===
            try:
                stt_engine = getattr(session._agent, "stt", None)
                if stt_engine and hasattr(stt_engine, "on_transcript"):
                    def on_transcript_event(result):
                        text = getattr(result, "text", "") or getattr(result, "transcript", "")
                        conf = getattr(result, "confidence", 1.0)
                        asyncio.create_task(handler.handle_transcript(text, conf))
                    stt_engine.on_transcript(on_transcript_event)
                    logger.debug(f"[STT] Attached transcript listener for {participant.identity}")
            except Exception as e:
                logger.error(f"[STT Handler Error] {e}")
                traceback.print_exc()

            return session

        except Exception as e:
            logger.error(f"[SESSION ERROR] {participant.identity}: {e}")
            traceback.print_exc()

    async def _handle_interruption(self, participant_identity: str, text: str, meta: dict):
        """Handle valid interruption - stop the agent's TTS immediately"""
        logger.info(f"[INTERRUPTION HANDLER] Stopping TTS for {participant_identity}: '{text}'")
        agent = self._agents.get(participant_identity)
        if agent:
            await agent.stop_speaking()
        else:
            logger.warning(f"[INTERRUPTION HANDLER] No agent found for {participant_identity}")

    async def _close_session(self, sess: AgentSession):
        try:
            await sess.drain()
            await sess.aclose()
            logger.debug("[SESSION CLOSE] Closed successfully.")
        except Exception as e:
            logger.error(f"[SESSION CLOSE ERROR] {e}")
            traceback.print_exc()


# ==============================================================
# JOB ENTRYPOINT (Unchanged)
# ==============================================================
async def entrypoint(ctx: JobContext):
    logger.info("[ENTRYPOINT] Starting MultiUserTranscriber.")
    transcriber = MultiUserTranscriber(ctx)
    transcriber.start()
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    for participant in ctx.room.remote_participants.values():
        transcriber.on_participant_connected(participant)

    ctx.add_shutdown_callback(lambda: asyncio.create_task(transcriber.aclose()))


def prewarm(proc: JobProcess):
    logger.debug("[PREWARM] Loading Silero VAD model...")
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("[PREWARM] Silero VAD ready.")


if __name__ == "__main__":
    logger.info("[BOOT] Starting agent worker...")
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
