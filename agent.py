"""Mistral Agent creation & multi-turn conversation logic."""

import logging
import os
import re
from dataclasses import dataclass, field

from mistralai import Mistral

log = logging.getLogger("voxcoder.agent")

AGENT_INSTRUCTIONS = """\
You are VoxCoder, a voice-controlled pair programmer.
The user speaks their request via voice (already transcribed to text).
The platform executes code automatically and shows the output in a live preview.

RULES:
1. ALWAYS respond with a code block. Never describe code without writing it.
2. For Python (scripts, graphs, algorithms, data, utilities): write complete runnable Python code in a ```python block.
3. For graphs/plots/charts: use matplotlib. Use random or example data if not specified. Do NOT ask for data.
4. For web apps/interfaces/websites: write a single self-contained HTML file (with embedded CSS and JS) in a ```html block.
5. For Bash/shell tasks: write a ```bash block.
6. NEVER use any tools. NEVER execute code yourself. Just output the code block — the platform runs it.
7. Keep any explanation to one sentence max. The user is speaking, not reading.
8. For follow-up requests ("fix it", "add labels", "make it blue"): output the full updated code.
9. Respond in the same language the user speaks (Italian or English).
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
    images: list[str] = field(default_factory=list)
    usage: UsageInfo = field(default_factory=UsageInfo)


async def create_agent() -> str:
    """Create the VoxCoder agent and return its ID."""
    client = _get_client()
    agent = await client.beta.agents.create_async(
        model="mistral-large-latest",
        name="VoxCoder",
        description="A voice-controlled coding assistant that writes code for local execution.",
        instructions=AGENT_INSTRUCTIONS,
        tools=[],
        completion_args={
            "temperature": 0.2,
            "top_p": 0.9,
        },
    )
    return agent.id


def _parse_response(response) -> AgentResponse:
    """Extract text and code blocks from agent response (no tool outputs)."""
    result = AgentResponse()
    text_parts: list[str] = []

    outputs = getattr(response, "outputs", [])
    if not outputs and hasattr(response, "content"):
        outputs = [response]

    for entry in outputs:
        content = getattr(entry, "content", None)
        if content:
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if hasattr(part, "text") and part.text:
                        text_parts.append(part.text)
                    elif isinstance(part, str):
                        text_parts.append(part)
        elif hasattr(entry, "text") and entry.text:
            text_parts.append(entry.text)

    full_text = "\n".join(text_parts).strip()
    result.text = full_text
    log.info("[parse] full_text length=%d", len(full_text))

    # Extract markdown code blocks
    blocks = re.findall(r"```(\w+)?\s*\n?(.*?)```", full_text, re.DOTALL)
    for lang, code in blocks:
        lang = lang.lower().strip() if lang else ""
        code = code.strip()
        if not code:
            continue
        if not lang:
            if "<html" in code.lower() or "<!doctype" in code.lower():
                lang = "html"
            else:
                lang = "python"
        result.code_blocks.append({"language": lang, "content": code})

    log.info("[parse] found %d code block(s)", len(result.code_blocks))

    # Usage
    if hasattr(response, "usage") and response.usage:
        u = response.usage
        result.usage = UsageInfo(
            prompt_tokens=u.prompt_tokens or 0,
            completion_tokens=u.completion_tokens or 0,
            total_tokens=u.total_tokens or 0,
            code_executions=0,
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
