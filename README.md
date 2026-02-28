# VoxCoder

A voice-controlled AI pair programmer built for the Mistral AI Hackathon. Speak a coding request, and VoxCoder transcribes it in real time, generates code with a Mistral agent, executes it locally, and renders the output — all in a single browser session.

---

## How it works

```
Microphone (PCM 16kHz)
        |
        v
  Voxtral Realtime         -- streaming speech-to-text
        |
        v
  Mistral Agent            -- mistral-large-latest with code_interpreter
        |
        v
  Local Executor           -- subprocess Python, matplotlib capture, auto-install
        |
        v
  WebSocket -> Browser     -- live preview, output panel, cost tracker
```

The entire pipeline runs over a single WebSocket connection. Audio chunks are sent as binary frames; all other messages are JSON.

---

## Features

- **Real-time transcription** — words appear as you speak via Voxtral Realtime (PCM streaming, no upload round-trip)
- **AI code generation** — multi-turn conversation with a Mistral agent that understands context ("fix that", "add error handling", "make it faster")
- **Local code execution** — Python and Bash blocks are executed on the server immediately after generation; stdout and matplotlib figures are sent back to the browser
- **Auto-install** — if a `ModuleNotFoundError` is raised, the missing package is installed via pip and the script retried automatically
- **Live preview** — HTML/CSS/JS code renders in a sandboxed iframe; Python/Bash code displays with syntax highlighting; execution output (including plots) renders as an image
- **Manual re-run** — each executable code block has a RUN button to re-execute without speaking again
- **Cost tracking** — per-request and cumulative breakdown of STT, input tokens, output tokens, and code executions
- **Multi-language support** — responds in the same language the user speaks (Italian / English)

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| Real-time transport | WebSocket (binary for audio, JSON for messages) |
| Speech-to-text | Mistral Voxtral Realtime (`voxtral-mini-transcribe-realtime-2602`) |
| Code generation | Mistral Agents API (`mistral-large-latest`) |
| Code execution | Python `asyncio.create_subprocess_exec` |
| Frontend | Vanilla JS, Prism.js (syntax highlighting) |
| Deployment | Docker (exposes port 7860, compatible with Hugging Face Spaces) |

---

## Project structure

```
hackton_project/
├── server.py          # FastAPI app, WebSocket endpoint, cost tracking
├── agent.py           # Mistral agent creation, multi-turn chat, response parsing
├── transcriber.py     # Voxtral Realtime streaming transcription
├── executor.py        # Local Python execution, matplotlib capture, auto-install
├── static/
│   ├── index.html     # Single-page app shell
│   ├── app.js         # WebSocket client, audio capture, UI logic
│   └── style.css      # Terminal/hacker theme
├── requirements.txt
└── Dockerfile
```

---

## Setup

### Prerequisites

- Python 3.11+
- A Mistral API key with access to Voxtral Realtime and the Agents API

### Local

```bash
git clone <repo>
cd hackton_project

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt

# Create a .env file
echo "MISTRAL_API_KEY=your_key_here" > .env

python server.py
# Open http://localhost:8000
```

### Docker

```bash
docker build -t voxcoder .
docker run -e MISTRAL_API_KEY=your_key_here -p 7860:7860 voxcoder
# Open http://localhost:7860
```

---

## Usage

| Action | How |
|---|---|
| Start recording | Hold **Space** or hold the mic button |
| Stop recording | Release **Space** or release the mic button |
| Re-run a code block | Click the **RUN** button on any Python/Bash block |
| Copy / download code | **COPY** and **SAVE** buttons on each code block |
| View cost breakdown | Click the **$0.000** counter in the header |
| Close live preview | Click the X on the preview panel header |

---

## API pricing reference (as of build date)

| Service | Rate |
|---|---|
| Voxtral Realtime STT | $0.006 / minute |
| Mistral Large input | $2.00 / 1M tokens |
| Mistral Large output | $6.00 / 1M tokens |
| Code interpreter execution | $0.03 / run |

---

## Limitations

- Code execution runs in the same Python environment as the server — no sandboxing. Do not expose the server publicly without additional isolation.
- The auto-install feature installs packages globally into the server's environment.
- Voxtral Realtime requires a live microphone; no file upload mode is currently implemented.
