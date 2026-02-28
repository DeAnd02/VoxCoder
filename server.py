"""FastAPI backend — serves the UI and handles the WebSocket pipeline."""

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
import uvicorn

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from agent import AgentSession, chat, create_agent
from executor import execute_python
from transcriber import AudioStream, transcribe_stream

# Pricing (USD)
PRICE_STT_PER_MIN = 0.006        # Voxtral Realtime
PRICE_INPUT_PER_TOKEN = 2.0 / 1_000_000   # Mistral Large input
PRICE_OUTPUT_PER_TOKEN = 6.0 / 1_000_000  # Mistral Large output
PRICE_CODE_EXEC = 0.03            # per code_interpreter execution

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("voxcoder")

_agent_id: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the Mistral agent once at server startup."""
    global _agent_id
    log.info("Creating VoxCoder agent…")
    _agent_id = await create_agent()
    log.info("Agent ready: %s", _agent_id)
    yield


app = FastAPI(title="VoxCoder", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _send(ws: WebSocket, msg_type: str, **kwargs):
    await ws.send_json({"type": msg_type, **kwargs})


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session = AgentSession(agent_id=_agent_id)
    log.info("Client connected")

    audio_stream: AudioStream | None = None
    transcribe_task: asyncio.Task | None = None
    transcript_parts: list[str] = []
    recording_start: float = 0.0

    # Cumulative cost tracking for this session
    totals = {
        "stt_cost": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "agent_cost_in": 0.0,
        "agent_cost_out": 0.0,
        "code_executions": 0,
        "exec_cost": 0.0,
        "total_cost": 0.0,
        "audio_minutes": 0.0,
    }

    async def _run_transcription(stream: AudioStream):
        """Background task: consume realtime transcript deltas and send to client."""
        try:
            async for delta in transcribe_stream(stream):
                transcript_parts.append(delta)
                await _send(ws, "transcript_delta", text=delta)
        except RuntimeError as exc:
            log.error("Transcription error: %s", exc)
            await _send(ws, "status", status="error", message=str(exc))

    try:
        while True:
            raw = await ws.receive()

            # --- Text messages (JSON commands) ---
            if "text" in raw:
                msg = json.loads(raw["text"])
                cmd = msg.get("cmd")

                if cmd == "start":
                    audio_stream = AudioStream()
                    transcript_parts.clear()
                    recording_start = time.monotonic()
                    transcribe_task = asyncio.create_task(
                        _run_transcription(audio_stream)
                    )
                    await _send(ws, "status", status="transcribing", message="Listening…")

                elif cmd == "end":
                    # Calculate audio duration
                    audio_secs = time.monotonic() - recording_start if recording_start else 0
                    audio_mins = audio_secs / 60.0

                    if audio_stream:
                        await audio_stream.end()
                    if transcribe_task:
                        await transcribe_task
                        transcribe_task = None

                    full_transcript = "".join(transcript_parts).strip()
                    transcript_parts.clear()
                    audio_stream = None

                    # Update STT cost
                    stt_cost = audio_mins * PRICE_STT_PER_MIN
                    totals["audio_minutes"] += audio_mins
                    totals["stt_cost"] += stt_cost

                    if not full_transcript:
                        await _send(ws, "status", status="ready", message="No speech detected")
                        await _send_costs(ws, totals, audio_mins, 0, 0, 0, stt_cost, 0, 0, 0)
                        continue

                    await _send(ws, "transcript", text=full_transcript)

                    # --- Run Mistral Agent ---
                    await _send(ws, "status", status="thinking", message="Agent is thinking…")
                    try:
                        agent_resp = await chat(session, full_transcript)
                    except Exception as exc:
                        log.exception("Agent call failed")
                        await _send(ws, "status", status="error", message=f"Agent error: {exc}")
                        continue

                    EXEC_LANGS = {"python", "py", "bash", "sh"}

                    for block in agent_resp.code_blocks:
                        lang = block.get("language", "python").lower()
                        await _send(ws, "code", language=lang, content=block["content"])

                        # Execute Python/Bash locally
                        if lang in EXEC_LANGS:
                            await _send(ws, "status", status="executing", message="Executing code…")
                            exec_result = await execute_python(block["content"])
                            if exec_result.installed:
                                await _send(ws, "message", text=f"Auto-installed: {', '.join(exec_result.installed)}")
                            if exec_result.stdout:
                                await _send(ws, "output", content=exec_result.stdout)
                            for img_data in exec_result.images:
                                await _send(ws, "image", data=img_data)
                            if exec_result.error:
                                await _send(ws, "output", content=f"[stderr]\n{exec_result.error}")

                    if agent_resp.text:
                        # Send text message to the UI
                        # We try to strip code blocks for the chat bubble, but if nothing is left, we send the original
                        clean_text = re.sub(r"```.*?```", "", agent_resp.text, flags=re.DOTALL).strip()
                        if clean_text:
                            await _send(ws, "message", text=clean_text)
                        elif not agent_resp.code_blocks:
                            await _send(ws, "message", text=agent_resp.text)

                    # Calculate agent costs for this request
                    u = agent_resp.usage
                    req_agent_cost_in = u.prompt_tokens * PRICE_INPUT_PER_TOKEN
                    req_agent_cost_out = u.completion_tokens * PRICE_OUTPUT_PER_TOKEN
                    req_exec_cost = u.code_executions * PRICE_CODE_EXEC

                    totals["input_tokens"] += u.prompt_tokens
                    totals["output_tokens"] += u.completion_tokens
                    totals["agent_cost_in"] += req_agent_cost_in
                    totals["agent_cost_out"] += req_agent_cost_out
                    totals["code_executions"] += u.code_executions
                    totals["exec_cost"] += req_exec_cost
                    totals["total_cost"] = (
                        totals["stt_cost"] + 
                        totals["agent_cost_in"] + 
                        totals["agent_cost_out"] + 
                        totals["exec_cost"]
                    )

                    await _send_costs(
                        ws, totals, audio_mins,
                        u.prompt_tokens, u.completion_tokens, u.code_executions,
                        stt_cost, req_agent_cost_in, req_agent_cost_out, req_exec_cost,
                    )

                    await _send(ws, "status", status="ready", message="Ready")

                elif cmd == "run_code":
                    code = msg.get("code", "").strip()
                    lang = msg.get("language", "python").lower()
                    if not code:
                        await _send(ws, "status", status="ready", message="Ready")
                        continue
                    await _send(ws, "status", status="executing", message="Executing code…")
                    exec_result = await execute_python(code)
                    if exec_result.installed:
                        await _send(ws, "message", text=f"Auto-installed: {', '.join(exec_result.installed)}")
                    if exec_result.stdout:
                        await _send(ws, "output", content=exec_result.stdout)
                    for img_data in exec_result.images:
                        await _send(ws, "image", data=img_data)
                    if exec_result.error:
                        await _send(ws, "output", content=f"[stderr]\n{exec_result.error}")
                    await _send(ws, "status", status="ready", message="Ready")

            # --- Binary messages (PCM audio chunks) ---
            elif "bytes" in raw and raw["bytes"] and audio_stream:
                await audio_stream.push(raw["bytes"])

    except WebSocketDisconnect:
        log.info("Client disconnected")
        if audio_stream:
            await audio_stream.end()
        if transcribe_task and not transcribe_task.done():
            transcribe_task.cancel()
    except Exception as e:
        log.exception("WebSocket error: %s", e)
        try:
            await _send(ws, "status", status="error", message=f"Internal error: {e}")
        except:
            pass


async def _send_costs(
    ws: WebSocket,
    totals: dict,
    req_audio_min: float,
    req_input_tokens: int,
    req_output_tokens: int,
    req_code_execs: int,
    req_stt_cost: float,
    req_agent_cost_in: float,
    req_agent_cost_out: float,
    req_exec_cost: float,
):
    """Send cost breakdown to the client."""
    await _send(
        ws, "cost",
        request={
            "audio_sec": round(req_audio_min * 60, 1),
            "input_tokens": req_input_tokens,
            "output_tokens": req_output_tokens,
            "code_executions": req_code_execs,
            "stt_cost": round(req_stt_cost, 6),
            "agent_cost_in": round(req_agent_cost_in, 6),
            "agent_cost_out": round(req_agent_cost_out, 6),
            "exec_cost": round(req_exec_cost, 6),
            "total": round(req_stt_cost + req_agent_cost_in + req_agent_cost_out + req_exec_cost, 6),
        },
        session={
            "audio_minutes": round(totals["audio_minutes"], 2),
            "input_tokens": totals["input_tokens"],
            "output_tokens": totals["output_tokens"],
            "code_executions": totals["code_executions"],
            "stt_cost": round(totals["stt_cost"], 6),
            "agent_cost_in": round(totals["agent_cost_in"], 6),
            "agent_cost_out": round(totals["agent_cost_out"], 6),
            "exec_cost": round(totals["exec_cost"], 6),
            "total": round(totals["total_cost"], 6),
        },
    )

# ---------------------------------------------------------------------------
# Serve static files (must be mounted AFTER routes)
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)