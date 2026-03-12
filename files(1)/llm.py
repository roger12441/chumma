"""
services/llm.py
===============
Thin wrapper around the Groq client.

Responsibilities:
  • Make the raw API call
  • Strip markdown fences that LLMs sometimes add around JSON
  • Parse and return clean JSON (dict or list)
  • Raise an HTTPException on parse failure so callers stay clean
"""

import re
import json
from fastapi import HTTPException
from config import groq_client


def llm_call(system: str, user: str, model: str, max_tokens: int = 2500) -> str:
    """
    Synchronous Groq chat-completion call.
    Always strips markdown code fences (```json … ```) from the response
    so callers can safely pass the result straight to `safe_json()`.
    """
    completion = groq_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
    )
    raw = completion.choices[0].message.content.strip()

    # Handles: ```json\n…\n``` and ```\n…\n``` variants
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence_match:
        raw = fence_match.group(1).strip()

    return raw.strip()


def safe_json(raw: str) -> dict | list:
    """
    Parse a JSON string returned by the LLM.
    Raises HTTP 502 (Bad Gateway) if the string is not valid JSON,
    because the fault lies with the upstream LLM, not the caller.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM returned invalid JSON: {exc}\nRaw (first 400 chars): {raw[:400]}",
        )
