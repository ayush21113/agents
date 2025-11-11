
# LiveKit Voice Interruption Handler

## Overview

This solution enhances LiveKit Agents with intelligent interruption handling that distinguishes meaningful user interruptions from filler words, ensuring seamless natural dialogue. The system extends the LiveKit Agents framework without modifying core SDK code, providing a configurable extension layer for real-time conversational AI agents.

## Features Implemented

### Core Functionality
- Filler word detection with configurable ignored words list
- Context-aware filtering - only ignores fillers during agent speech
- Real-time interruption handling - immediate stop for genuine commands
- Mixed speech processing - detects valid commands within filler phrases
- Configurable parameters via environment variables
- Comprehensive logging for debugging and monitoring

### Technical Achievements
- Extension layer design - no changes to LiveKit core VAD
- Async/thread-safe implementation
- Language-agnostic architecture
- Scalable design for dynamic word list updates
- Integration with LiveKit agent event loop

## Architecture

The system operates as an extension layer to LiveKit Agents:

```
LiveKit Room Events
        ↓
[ FillerInterruptHandler ]
        ↓
    ├── Agent Speaking? → Yes → Check for fillers vs commands
    │                       ├── Filler detected → Ignore, continue speaking
    │                       └── Command detected → Stop agent immediately
    │
    └── Agent Quiet? → Yes → Process all speech normally
```

### Scenario Handling

| Agent State | User Speech | Confidence | Outcome |
|-------------|-------------|------------|---------|
| Speaking | "uh", "hmm" | High | Ignored filler |
| Speaking | "wait", "stop" | High | Immediate stop |
| Quiet | "umm hello" | High | Process normally |
| Speaking | "umm stop now" | High | Stops (contains command) |
| Speaking | Background murmur | Low | Ignored (low confidence) |

## Installation & Setup

### Prerequisites
- Python ≥ 3.10
- LiveKit server
- Deepgram API key (for STT)
- ElevenLabs API key (for TTS)

### 1. Install Dependencies
```bash
pip install livekit-agents livekit-plugins-deepgram livekit-plugins-elevenlabs python-dotenv
```

### 2. Environment Configuration
Create `.env` file:
```env
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=your_api_key_here
LIVEKIT_API_SECRET=your_api_secret_here
DEEPGRAM_API_KEY=your_deepgram_key_here
ELEVENLABS_API_KEY=your_elevenlabs_key_here

# Filler Handler Configuration
IGNORED_WORDS=uh,umm,hmm,haan
FILLER_HANDLER_LOG_LEVEL=DEBUG
```

## Windows Setup & Execution

### Step 1: Generate LiveKit Keys
```powershell
cd "C:\Users\PRO\Desktop\project\agents\livekit-server"
.\livekit-server.exe generate-keys
```

### Step 2: Set Permanent Environment Variables
```powershell
setx LIVEKIT_API_KEY "your_api_key_here"
setx LIVEKIT_API_SECRET "your_api_secret_here" 
setx LIVEKIT_URL "ws://localhost:7880"
```

### Step 3: Three-Terminal Setup

#### Terminal 1 - LiveKit Server
```powershell
cd "C:\Users\PRO\Desktop\project\agents\livekit-server"
& ".\livekit-server.exe" --dev --keys "your_api_key:your_api_secret"
```

#### Terminal 2 - Python Agent
```powershell
# Set environment variables for this session
$env:LIVEKIT_API_KEY = "your_api_key_here"
$env:LIVEKIT_API_SECRET = "your_api_secret_here"
$env:LIVEKIT_URL = "ws://localhost:7880"
$env:DEEPGRAM_API_KEY = "your_deepgram_key_here"
$env:ELEVENLABS_API_KEY = "your_elevenlabs_key_here"

# Set Python path
$env:PYTHONPATH = "C:\Users\PRO\Desktop\project\agents"
echo $env:PYTHONPATH

# Start the agent
python examples/other/transcription/multi-user-transcriber.py start

# Or for development mode:
python examples\other\transcription\multi-user-transcriber.py dev
```

#### Terminal 3 - Create Test Room
```powershell
cd "C:\Users\PRO\Desktop\project\agents\livekit-cli"

# Create room
.\lk.exe --url ws://localhost:7880 room create testroom

# Generate participant token
.\lk.exe --url ws://localhost:7880 token create --join testroom user1
```

### Step 4: Test via LiveKit Playground
1. Open https://agents-playground.livekit.io/
2. Enter:
   - Project URL: `ws://localhost:7880`
   - Token: [Token generated from Terminal 3]
3. Join room "testroom"
4. Start speaking to test the agent

## Implementation Details

### Core Files

#### filler_interrupt_handler.py
The main interruption handling logic providing:
- Configurable filler word lists
- Force-stop word detection
- Confidence-based filtering
- Async event processing
- Dynamic configuration updates

Key components:
```python
class FillerInterruptHandler:
    def __init__(self, ignored_words=None, force_stop_words=None, ...):
        self.ignored_words = set(ignored_words or DEFAULT_IGNORED_WORDS)
        self.force_stop_words = set(force_stop_words or DEFAULT_FORCE_STOP_WORDS)
        
    async def handle_transcript(self, text: str, confidence: float = None, ...):
        # Core decision logic for filler vs command discrimination
```

#### multi-user-transcriber.py
Main agent with integration:
- Multi-user session management
- Real-time audio input/output with RoomIO
- STT & TTS setup (Deepgram, ElevenLabs)
- Automatic response flow
- Filler and stop-word control

## Testing & Validation

### Test Scenarios Verified

1. **Filler during agent speech**
   - Input: "uh", "hmm" while agent speaking
   - Expected: Agent continues speaking

2. **Genuine interruption** 
   - Input: "wait", "stop" while agent speaking
   - Expected: Agent stops immediately

3. **Filler during quiet**
   - Input: "umm" when agent not speaking
   - Expected: Speech processed normally

4. **Mixed speech**
   - Input: "umm stop please" while agent speaking
   - Expected: Agent stops (contains command)

5. **Low confidence noise**
   - Input: Background murmur
   - Expected: Ignored (below threshold)

### Manual Testing Steps

1. Start the agent: `python multi-user-transcriber.py start`
2. Join room via LiveKit Playground
3. Test scenarios while agent is speaking:
   - Say filler words - should be ignored
   - Say stop commands - should interrupt immediately
4. Test when agent is quiet:
   - Same words should be processed normally

## Performance Characteristics

- Real-time responsiveness: No added latency in interruption detection
- Resource efficient: Minimal CPU/memory overhead
- Scalable: Handles multiple participants concurrently
- Robust: Works under various audio conditions and speech patterns

## Known Issues & Limitations

1. Edge cases: Very rapid speech turn-taking may occasionally miss interruptions
2. Language specific: Currently optimized for English filler patterns
3. Confidence thresholds: May need tuning for specific audio environments
4. TTS interruption: While detection works reliably, TTS cancellation may have brief latency

## Future Enhancements

- Dynamic word list updates during runtime
- Multi-language filler detection (Hindi + English mix)
- Machine learning-based filler detection
- Per-user customization of ignored words
- Advanced context-aware interruption scoring

## Challenge Compliance

### Fully Met Requirements
- Correct filler vs command discrimination
- Real-time performance without VAD modifications  
- Configurable ignored words list
- Context-aware handling (speaking vs quiet)
- Async/thread-safe implementation
- No changes to LiveKit core SDK

### Bonus Features Implemented
- Dynamic configuration via environment variables
- Extensible architecture for multi-language support
- Comprehensive logging system

## Credits

- **LiveKit** - Real-time agent infrastructure
- **Deepgram** - Speech-to-text services  
- **ElevenLabs** - Text-to-speech synthesis
- **LiveKit Agents SDK** - Foundation for extension development

## Quick Start

1. Setup Environment: Set API keys and environment variables
2. Start Server: Terminal 1 - LiveKit server
3. Run Agent: Terminal 2 - Python agent with PYTHONPATH set
4. Create Room: Terminal 3 - Generate room and tokens
5. Test: Use LiveKit Playground to join and test

This solution provides natural conversations without awkward filler-word interruptions while maintaining immediate responsiveness to genuine user commands.
```
