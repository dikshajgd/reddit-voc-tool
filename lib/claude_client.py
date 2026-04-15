"""
Shared Claude API client using the Anthropic Python SDK.
Replaces the Claude Code CLI subprocess calls used locally.
"""

import os
import anthropic

# Initialize client — reads ANTHROPIC_API_KEY from env (or st.secrets on Streamlit Cloud)
_api_key = os.environ.get("ANTHROPIC_API_KEY")
client = anthropic.Anthropic(api_key=_api_key) if _api_key else None

MODEL = "claude-sonnet-4-20250514"


def call_claude(system_prompt: str, user_message: str, max_tokens: int = 16000) -> str:
    """
    Call Claude via the Anthropic SDK.

    Args:
        system_prompt: The system-level instructions
        user_message: The user's input/request
        max_tokens: Maximum tokens in the response (default 16000)

    Returns:
        The text content of Claude's response
    """
    global client

    # Lazy init for Streamlit Cloud where secrets load after import
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not found. Set it in .env (local) "
                "or Streamlit Cloud secrets."
            )
        client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    return response.content[0].text


def strip_preamble(text: str) -> str:
    """Remove Claude's conversational preamble before the actual content."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or stripped == "---":
            return "\n".join(lines[i:])
    return text
