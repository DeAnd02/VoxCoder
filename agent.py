"""Mistral Agent creation & multi-turn conversation logic."""

import json
import logging
import os
import re
from dataclasses import dataclass, field

from mistralai import Mistral

log = logging.getLogger("voxcoder.agent")

AGENT_INSTRUCTIONS = """\
You are VoxCoder, a voice-controlled pair programmer.
The user speaks commands to you via voice (transcribed to text).

Rules:
- When the user asks for simple code (e.g. algorithms, functions, simple logic), provide only the code block. Do NOT use the code interpreter unless specifically asked to test it.
- If the user asks for complex tasks like creating a website, a web interface, or a full application with frontend and backend, output HTML, CSS, and JavaScript in separate or combined code blocks.
- The platform supports a live "Preview" for web code (HTML/CSS/JS) and for execution output including images and plots.
- When writing Python code that produces visual output (matplotlib, seaborn, plotly, PIL, pandas plots, charts, graphs, diagrams), ALWAYS execute it with the code interpreter so the plot/image appears in the Preview panel. Never skip execution for visualization code.
- For simple Python code without visual output (algorithms, utilities, functions), provide only the code block without executing.
- Keep responses extremely concise — the user is speaking, not typing.
- If the user says something ambiguous, ask a SHORT clarifying question.
- Support iterative development: the user can say "fix that", "add error handling", "make it faster" etc.
- When the user says "save" or "export", output the final complete code.
- Respond in the same language the user speaks (Italian or English).
"""

_client: Mistral | None = None


def _get_client() -> Mistral:
    global _client
    if _client is None:
        _client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    return _client


@dataclass
class AgentSession:
    """Holds state for one user session (agent + conversation)."""
    agent_id: str | None = None
    conversation_id: str | None = None


# Robust regex for markdown code blocks
_CODE_BLOCK_RE = re.compile(r"```(?P<lang>\w+)?\s*\n?(?P<code>.*?)```", re.DOTALL)


@dataclass
class UsageInfo:
    """Token usage from a single agent call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    code_executions: int = 0


@dataclass
class AgentResponse:
    """Parsed response from the agent."""
    text: str = ""
    code_blocks: list[dict] = field(default_factory=list)
    output: str = ""
    images: list[str] = field(default_factory=list)  # base64 data URIs from code_interpreter
    usage: UsageInfo = field(default_factory=UsageInfo)


def _extract_tool_output(output, text_out: list[str], image_out: list[str]) -> None:
    """Recursively extract text and base64 images from code_interpreter output."""
    if output is None:
        return
    if isinstance(output, str):
        if output.strip():
            text_out.append(output)
        return
    if isinstance(output, list):
        for item in output:
            _extract_tool_output_item(item, text_out, image_out)
        return
    # Fallback: stringify
    s = str(output).strip()
    if s:
        text_out.append(s)


def _as_data_uri(raw: str) -> str | None:
    """Convert raw base64 or data URI to a usable data URI string."""
    if not isinstance(raw, str) or not raw:
        return None
    if raw.startswith("data:image"):
        return raw
    # PNG magic bytes in base64 start with "iVBOR"; JPEG start with "/9j/"
    if raw.startswith("iVBOR"):
        return f"data:image/png;base64,{raw}"
    if raw.startswith("/9j/"):
        return f"data:image/jpeg;base64,{raw}"
    return None


def _extract_tool_output_item(item, text_out: list[str], image_out: list[str]) -> None:
    """Handle a single content item (dict or SDK object) from code_interpreter."""
    if isinstance(item, dict):
        t = item.get("type", "")
        if t == "text":
            txt = item.get("text", "").strip()
            if txt:
                text_out.append(txt)
        elif t in ("image_url", "image", "image_data"):
            # Try every plausible key that could hold the image
            for key in ("image_url", "url", "data", "image_data", "src"):
                raw = item.get(key, "")
                if isinstance(raw, dict):
                    raw = raw.get("url", raw.get("data", ""))
                uri = _as_data_uri(raw)
                if uri:
                    image_out.append(uri)
                    log.info(f"[parse] image extracted from dict key='{key}' len={len(uri)}")
                    break
        else:
            for key in ("text", "content", "value"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    text_out.append(val.strip())
                    break
    else:
        # SDK object — try all likely attribute names
        item_type = getattr(item, "type", None)
        if item_type == "text":
            txt = getattr(item, "text", "")
            if txt and txt.strip():
                text_out.append(txt.strip())
        elif item_type in ("image_url", "image", "image_data"):
            for attr in ("image_url", "url", "data", "image_data", "src"):
                raw = getattr(item, attr, None)
                if raw is None:
                    continue
                if hasattr(raw, "url"):
                    raw = raw.url
                uri = _as_data_uri(str(raw))
                if uri:
                    image_out.append(uri)
                    log.info(f"[parse] image extracted from obj attr='{attr}' len={len(uri)}")
                    break
        elif hasattr(item, "text") and item.text:
            text_out.append(str(item.text).strip())
        elif hasattr(item, "content") and item.content:
            _extract_tool_output(item.content, text_out, image_out)


async def create_agent() -> str:
    """Create the VoxCoder agent and return its ID."""
    client = _get_client()
    agent = await client.beta.agents.create_async(
        model="mistral-large-latest",
        name="VoxCoder",
        description="A voice-controlled coding assistant that writes and executes Python code.",
        instructions=AGENT_INSTRUCTIONS,
        tools=[{"type": "code_interpreter"}],
        completion_args={
            "temperature": 0.3,
            "top_p": 0.9,
        },
    )
    return agent.id


def _parse_response(response) -> AgentResponse:
    """Extract text, code blocks, execution output, and usage from response."""
    result = AgentResponse()
    text_parts: list[str] = []
    output_parts: list[str] = []
    code_exec_count = 0

    log.debug(f"Parsing response from Mistral. Outputs: {response.outputs if hasattr(response, 'outputs') else 'No outputs'}")

    # Robust extraction of outputs
    outputs = getattr(response, "outputs", [])
    if not outputs:
        # Fallback for other response types
        log.warning("Response has no 'outputs' attribute. Attempting fallback.")
        if hasattr(response, "content"):
             outputs = [response] # Treat the response itself as an entry

    for idx, entry in enumerate(outputs):
        log.debug(f"Output entry {idx} type: {type(entry).__name__}")
        
        # Check for direct text content
        content = getattr(entry, "content", None)
        if content:
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for p_idx, part in enumerate(content):
                    if hasattr(part, "text") and part.text:
                        text_parts.append(part.text)
                    elif hasattr(part, "code") and part.code:
                        result.code_blocks.append({
                            "language": getattr(part, "language", "python"), 
                            "content": part.code
                        })
                    elif isinstance(part, str):
                        text_parts.append(part)
        
        # Check for text attribute
        elif hasattr(entry, "text") and entry.text:
             text_parts.append(entry.text)

        # Log entry type for debugging
        entry_typename = type(entry).__name__
        log.info(f"[parse] entry[{idx}] type={entry_typename}")

        # Check for tool execution outputs (text + images)
        if hasattr(entry, "output") and entry.output is not None:
            log.info(f"[parse] tool output at [{idx}]: {repr(entry.output)[:500]}")
            _extract_tool_output(entry.output, output_parts, result.images)

        # Check for tool calls (built-in code_interpreter appears differently)
        if hasattr(entry, "tool_calls") and entry.tool_calls:
            for call in entry.tool_calls:
                fn_name = getattr(getattr(call, "function", None), "name", "") or ""
                if fn_name == "code_interpreter":
                    try:
                        args = json.loads(call.function.arguments)
                        if "code" in args:
                            result.code_blocks.append({
                                "language": "python",
                                "content": args["code"]
                            })
                    except Exception:
                        pass

        # Count code executions — match by substring to handle SDK version differences
        if any(k in entry_typename for k in ("ToolExecution", "CodeInterpreter", "ToolResult")):
            code_exec_count += 1
            log.info(f"[parse] code execution detected at entry [{idx}]")

    full_text = "\n".join(text_parts).strip()
    result.text = full_text

    # Extract markdown code blocks from the full text
    # We use a very lenient regex to catch as much as possible
    blocks = re.findall(r"```(\w+)?\s*\n?(.*?)```", full_text, re.DOTALL)
    for lang, code in blocks:
        lang = lang.lower() if lang else ""
        code = code.strip()
        
        if not lang:
            if "<html>" in code.lower() or "<div>" in code.lower():
                lang = "html"
            else:
                lang = "python"
        
        if not any(b["content"] == code for b in result.code_blocks):
            result.code_blocks.append({"language": lang, "content": code})

    if output_parts:
        result.output = "\n".join(output_parts)

    if output_parts:
        result.output = "\n".join(output_parts)

    # Extract usage
    if hasattr(response, "usage") and response.usage:
        u = response.usage
        result.usage = UsageInfo(
            prompt_tokens=u.prompt_tokens or 0,
            completion_tokens=u.completion_tokens or 0,
            total_tokens=u.total_tokens or 0,
            code_executions=code_exec_count,
        )

    return result


async def chat(session: AgentSession, user_message: str) -> AgentResponse:
    """Send a message to the agent and return parsed response.

    On first call, starts a new conversation. Subsequent calls continue
    the same conversation for multi-turn context.
    """
    client = _get_client()

    if session.conversation_id is None:
        response = await client.beta.conversations.start_async(
            agent_id=session.agent_id,
            inputs=user_message,
        )
    else:
        response = await client.beta.conversations.append_async(
            conversation_id=session.conversation_id,
            inputs=user_message,
        )

    session.conversation_id = response.conversation_id
    return _parse_response(response)
