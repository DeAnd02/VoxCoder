"""Audio conversion utilities — WebM/Opus to WAV via ffmpeg."""

import subprocess
import tempfile
import os


def convert_webm_to_wav(webm_bytes: bytes) -> bytes:
    """Convert WebM/Opus audio bytes to 16kHz mono WAV for Voxtral API."""
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f_in:
        f_in.write(webm_bytes)
        f_in_path = f_in.name

    f_out_path = f_in_path.replace(".webm", ".wav")

    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", f_in_path,
                "-ar", "16000",
                "-ac", "1",
                "-f", "wav",
                f_out_path,
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg error: {result.stderr.decode()}")

        with open(f_out_path, "rb") as f_out:
            return f_out.read()
    finally:
        for path in (f_in_path, f_out_path):
            if os.path.exists(path):
                os.unlink(path)
