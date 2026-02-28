# VoxCoder

A voice-controlled AI pair programmer built for the Mistral AI Hackathon. Speak a coding request, VoxCoder transcribes it in real time, generates code with a Mistral agent, executes it locally, and renders the output — all in a single browser session.

---

## How it works

```
Microphone (PCM 16kHz)
        |
        v
  Voxtral Realtime         -- streaming speech-to-text (deltas appear as you speak)
        |
        v
  Mistral Agent            -- mistral-large-latest, generates code only (no tools)
        |
        v
  Local Executor           -- asyncio subprocess, matplotlib capture, auto-install
        |
        v
  WebSocket -> Browser     -- code panel, live preview, output panel, cost tracker
```

The entire pipeline runs over a single WebSocket connection. Audio chunks are sent as binary frames; all other messages are JSON.

The agent is intentionally kept tool-free: it outputs only markdown code blocks. The server is responsible for executing every block locally and streaming results back to the browser.

---

## Features

**Voice pipeline**
- Real-time transcription — words appear as you speak via Voxtral Realtime (PCM 16kHz streaming, no upload round-trip)
- Push-to-talk via mic button or spacebar hold

**Code generation**
- Multi-turn conversation — the agent retains context across requests ("fix that", "add labels", "make it faster")
- Responds in the same language as the user (Italian / English)
- Always outputs runnable code blocks, never plain descriptions

**Local execution engine**
- Python and Bash blocks are executed on the server automatically after generation
- Matplotlib figures are captured headlessly (Agg backend) and sent to the browser as base64 PNG
- `ModuleNotFoundError` triggers automatic `pip install` and a single retry
- 30-second execution timeout per script
- Manual re-run via the RUN button on each code block, without speaking again

**Live preview panel**
- HTML/CSS/JS → sandboxed iframe with live rendering
- Python/Bash → syntax-highlighted code display, switches to image when execution output arrives
- Matplotlib plots, seaborn charts, PIL images → rendered in the preview panel

**UI**
- Code tabs — one tab per generated block, switchable
- Streaming code animation — code appears character by character
- COPY and SAVE (download) buttons on every code block
- ANSI color parsing in the output panel
- Boot sequence animation on connect
- Glitch effect on status transitions
- Matrix rain background, CRT scanline overlay
- Session cost tracker with per-service breakdown and progress bars

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| Real-time transport | WebSocket (binary for audio, JSON for control messages) |
| Speech-to-text | Mistral Voxtral Realtime (`voxtral-mini-transcribe-realtime-2602`) |
| Code generation | Mistral Agents API (`mistral-large-latest`, no tools) |
| Code execution | Python `asyncio.create_subprocess_exec` + temp file |
| Plot capture | Matplotlib Agg backend → base64 PNG via stderr markers |
| Frontend | Vanilla JS, Prism.js (syntax highlighting) |
| Deployment | Docker (port 7860, compatible with Hugging Face Spaces) |

---

## Project structure

```
hackton_project/
├── server.py          # FastAPI app, WebSocket endpoint, execution pipeline, cost tracking
├── agent.py           # Mistral agent creation, multi-turn chat, markdown code block parsing
├── transcriber.py     # Voxtral Realtime streaming transcription
├── executor.py        # Local Python/Bash execution, matplotlib capture, auto pip-install
├── static/
│   ├── index.html     # Single-page app shell
│   ├── app.js         # WebSocket client, audio capture, code tabs, preview logic
│   └── style.css      # Terminal/hacker theme
├── requirements.txt
├── Dockerfile
└── .dockerignore
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

# Pass the key inline
docker run --rm -p 7860:7860 -e MISTRAL_API_KEY=your_key_here voxcoder

# Or use the .env file
docker run --rm -p 7860:7860 --env-file .env voxcoder

# Open http://localhost:7860
```

---

## Usage

| Action | How |
|---|---|
| Start recording | Hold **Space** or hold the mic button |
| Stop recording | Release **Space** or release the mic button |
| Re-run a code block | Click **RUN** on any Python/Bash block |
| Switch between code blocks | Click the tabs above the code panel |
| Copy / download code | **COPY** and **SAVE** buttons on each block |
| Refresh the live preview | Click the refresh icon on the preview panel header |
| Close the live preview | Click **X** on the preview panel header |
| View cost breakdown | Click the **$0.000** counter in the header |

---

## API pricing reference

| Service | Rate |
|---|---|
| Voxtral Realtime STT | $0.006 / minute |
| Mistral Large input | $2.00 / 1M tokens |
| Mistral Large output | $6.00 / 1M tokens |

---

## Limitations

- Code execution runs in the same Python environment as the server with no sandboxing. Do not expose the server on a public network without additional isolation.
- Auto-installed packages persist in the server environment for the lifetime of the process; each restart starts clean.
- Voxtral Realtime requires a live microphone. No file upload mode is implemented.
- Browser microphone access requires HTTPS in production (works on `localhost` without it).
