"""Voxtral Realtime transcription — streams audio chunks and yields transcript deltas."""

import asyncio
import os
from collections.abc import AsyncIterator

from mistralai import Mistral
from mistralai.models import AudioFormat

REALTIME_MODEL = "voxtral-mini-transcribe-realtime-2602"
AUDIO_FORMAT = AudioFormat(encoding="pcm_s16le", sample_rate=16000)

_client: Mistral | None = None


def _get_client() -> Mistral:
    global _client
    if _client is None:
        _client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    return _client


class AudioStream:
    """Async iterator that receives PCM audio chunks pushed from outside."""

    def __init__(self):
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def push(self, chunk: bytes):
        await self._queue.put(chunk)

    async def end(self):
        await self._queue.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        chunk = await self._queue.get()
        if chunk is None:
            raise StopAsyncIteration
        return chunk


async def transcribe_stream(audio_stream: AudioStream) -> AsyncIterator[str]:
    """Stream audio to Voxtral Realtime and yield transcript text deltas.

    Each yielded string is a partial transcript update (delta).
    """
    client = _get_client()

    async for event in client.audio.realtime.transcribe_stream(
        audio_stream=audio_stream,
        model=REALTIME_MODEL,
        audio_format=AUDIO_FORMAT,
    ):
        etype = type(event).__name__

        if etype == "TranscriptionStreamTextDelta":
            if hasattr(event, "text") and event.text:
                yield event.text
        elif etype == "RealtimeTranscriptionError":
            msg = getattr(event, "message", str(event))
            raise RuntimeError(f"Realtime transcription error: {msg}")


async def transcribe_batch(audio_wav_bytes: bytes, language: str | None = None) -> str:
    """Fallback: batch transcription using voxtral-mini-latest."""
    client = _get_client()

    kwargs: dict = {
        "model": "voxtral-mini-latest",
        "file": {
            "file_name": "recording.wav",
            "content": audio_wav_bytes,
        },
    }
    if language:
        kwargs["language"] = language

    transcription = await client.audio.transcriptions.complete_async(**kwargs)
    return transcription.text
