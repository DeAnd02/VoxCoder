"""Local Python code execution with matplotlib capture and auto-install."""

import asyncio
import base64
import io
import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field

log = logging.getLogger("voxcoder.executor")

TIMEOUT_SECS = 30

# The script template:
# - Sets matplotlib to non-interactive Agg backend BEFORE user code runs
#   so plt.show() becomes a no-op and figures stay in memory
# - User code runs normally, printing to stdout
# - Epilogue captures all open figures and writes them to stderr as
#   __IMAGE__: markers (separate channel avoids mixing with text output)
_SCRIPT_TPL = '''\
import sys as _sys, io as _io, base64 as _b64, warnings as _w
_w.filterwarnings("ignore")

# Force Agg backend before any user import of matplotlib
try:
    import matplotlib as _mpl
    _mpl.use("Agg")
    import matplotlib.pyplot as _plt
    _HAS_MPL = True
except ImportError:
    _HAS_MPL = False

# ── User code ──────────────────────────────────────────────────────
{user_code}
# ── End user code ──────────────────────────────────────────────────

# Export all open matplotlib figures via stderr (separate from text output)
if _HAS_MPL:
    for _n in _plt.get_fignums():
        _fig = _plt.figure(_n)
        _buf = _io.BytesIO()
        _fig.savefig(_buf, format="png", bbox_inches="tight", dpi=150)
        _buf.seek(0)
        _img = _b64.b64encode(_buf.read()).decode()
        _sys.stderr.write("__IMAGE__:data:image/png;base64," + _img + "\\n")
        _plt.close(_fig)
'''


@dataclass
class ExecResult:
    stdout: str = ""
    images: list[str] = field(default_factory=list)
    error: str = ""
    installed: list[str] = field(default_factory=list)


async def execute_python(code: str) -> ExecResult:
    """Execute Python code locally.

    - Captures stdout as text output.
    - Captures matplotlib figures as base64 PNG data URIs.
    - Auto-installs a missing top-level package if ModuleNotFoundError is raised,
      then retries once.
    """
    result = ExecResult()
    script = _SCRIPT_TPL.format(user_code=code)

    stdout, stderr, ok, missing = await _run_script(script)

    if missing:
        log.info("[executor] auto-installing: %s", missing)
        if await _pip_install(missing):
            result.installed.append(missing)
            stdout, stderr, ok, _ = await _run_script(script)

    # Text output = everything on stdout
    result.stdout = stdout.strip()

    # Images = __IMAGE__: lines from stderr
    err_lines = []
    for line in stderr.splitlines():
        if line.startswith("__IMAGE__:"):
            result.images.append(line[len("__IMAGE__:"):])
        else:
            err_lines.append(line)

    if not ok and err_lines:
        result.error = "\n".join(err_lines).strip()

    return result


async def _run_script(script: str) -> tuple[str, str, bool, str | None]:
    """Write script to a temp file and execute it. Returns (stdout, stderr, ok, missing_pkg)."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    )
    try:
        tmp.write(script)
        tmp.close()

        proc = await asyncio.create_subprocess_exec(
            sys.executable, tmp.name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out_b, err_b = await asyncio.wait_for(
                proc.communicate(), timeout=TIMEOUT_SECS
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return "", f"Execution timed out after {TIMEOUT_SECS}s", False, None

        stdout = out_b.decode("utf-8", errors="replace")
        stderr = err_b.decode("utf-8", errors="replace")
        ok = proc.returncode == 0

        # Detect missing package
        missing = None
        if not ok:
            m = re.search(
                r"ModuleNotFoundError: No module named '([^']+)'", stderr
            )
            if m:
                # Take only the top-level package name (e.g. "sklearn" from "sklearn.datasets")
                missing = m.group(1).split(".")[0]

        return stdout, stderr, ok, missing

    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


async def _pip_install(package: str) -> bool:
    """Install a package via pip. Returns True on success."""
    log.info("[executor] pip install %s …", package)
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", package, "--quiet",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=120)
        success = proc.returncode == 0
        if success:
            log.info("[executor] installed %s", package)
        else:
            log.warning("[executor] failed to install %s", package)
        return success
    except Exception as exc:
        log.warning("[executor] pip error: %s", exc)
        return False
