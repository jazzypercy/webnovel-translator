"""
Core LLM translation logic.

Builds the master prompt (with the live glossary injected), calls Gemini
via the modern `google-genai` SDK, and parses the structured response
(translation text + any newly-observed glossary terms).

Uses google.genai.Client(), NOT the legacy google-generativeai package.
"""

import json
import time
from typing import Any, Dict, Tuple

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

import config

_client = None


def get_client() -> genai.Client:
    """Lazily create a single shared genai.Client.

    The client reads GEMINI_API_KEY / GOOGLE_API_KEY from the environment
    automatically -- no key is ever hardcoded in this codebase. Set it
    with:

        export GEMINI_API_KEY="your-key-here"

    or place it in a .env file in the project root.
    """
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


# --- Structured output schema ---------------------------------------------
# Asking Gemini to return JSON matching this schema means we get the
# translation AND any new glossary terms it noticed in a single call,
# instead of needing a separate "extract terms" pass.

_TERM_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "original": {
            "type": "string",
            "description": "The term exactly as it appears in the raw source text.",
        },
        "translation": {
            "type": "string",
            "description": "The chosen English rendering of the term.",
        },
        "notes": {
            "type": "string",
            "description": "Brief context: role, gender, tone, or usage notes.",
        },
    },
    "required": ["original", "translation"],
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "translation": {
            "type": "string",
            "description": "The complete, publication-ready English translation of the chapter.",
        },
        "glossary_additions": {
            "type": "object",
            "description": "Any proper nouns, skills, locations, or recurring terms encountered "
            "in this chapter that are not already in the supplied glossary.",
            "properties": {
                "characters": {"type": "array", "items": _TERM_ENTRY_SCHEMA},
                "locations": {"type": "array", "items": _TERM_ENTRY_SCHEMA},
                "skills_and_items": {"type": "array", "items": _TERM_ENTRY_SCHEMA},
                "terms": {"type": "array", "items": _TERM_ENTRY_SCHEMA},
            },
        },
    },
    "required": ["translation", "glossary_additions"],
}


def build_system_instruction(glossary_text: str) -> str:
    """Assemble the master prompt that governs tone, consistency, and
    output format. The live glossary is injected verbatim so the model
    can enforce it."""
    glossary_block = glossary_text if glossary_text else (
        "(empty -- this is the first chapter processed, so there are no "
        "established terms yet. Populate glossary_additions generously.)"
    )

    return f"""You are a professional literary translator specializing in web novels \
translated from their original language into English for a native English-reading audience.

STYLE / TONE
{config.TRANSLATION_TONE}

CONSISTENCY RULES (follow strictly)
1. Use the EXISTING GLOSSARY below verbatim for every name, location, skill, or \
term it contains. Never invent an alternate spelling or rendering for anything \
already listed there.
2. If you encounter a new proper noun, skill/technique name, faction, title, or \
other recurring term that is NOT yet in the glossary, choose a natural English \
rendering for it and report it under `glossary_additions` in your JSON response \
so it can be reused in later chapters. Only report genuinely new terms -- do not \
re-report anything already in the existing glossary.
3. The source language frequently drops pronouns and subjects. Repair this: add \
"he/she/I/they/it" etc. wherever it's implied, based on context, so every \
sentence reads naturally in English. Never leave a sentence subject-less if \
English requires one.
4. Translate the FULL chapter. Do not summarize, skip, paraphrase-shorten, or \
censor any content.
5. Preserve the source's paragraph breaks and dialogue structure.

EXISTING GLOSSARY
{glossary_block}

OUTPUT FORMAT
Respond with ONLY a JSON object matching the provided schema -- no markdown code \
fences, no commentary before or after the JSON.
"""


def translate_chapter(raw_text: str, glossary_text: str) -> Tuple[str, Dict[str, Any]]:
    """Translate one chapter's raw text.

    Returns (translation, glossary_additions) where glossary_additions is
    the raw dict the model returned (categories -> list of term entries),
    ready to hand to GlossaryManager.add_entries().

    Retries on transient API errors (rate limits, server hiccups) with
    exponential backoff.
    """
    client = get_client()
    system_instruction = build_system_instruction(glossary_text)

    gen_config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        temperature=config.TEMPERATURE,
        max_output_tokens=config.MAX_OUTPUT_TOKENS,
    )

    backoff = config.INITIAL_BACKOFF_SECONDS
    last_error: Exception = RuntimeError("no attempts were made")

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=config.MODEL_NAME,
                contents=raw_text,
                config=gen_config,
            )
            return _parse_response(response)

        except genai_errors.APIError as exc:
            last_error = exc
            print(f"  [warn] Gemini API error (attempt {attempt}/{config.MAX_RETRIES}): {exc}")

        except (json.JSONDecodeError, RuntimeError) as exc:
            # The model returned something that didn't parse -- worth a
            # retry since Gemini can occasionally wobble on strict JSON.
            last_error = exc
            print(f"  [warn] Response parsing error (attempt {attempt}/{config.MAX_RETRIES}): {exc}")

        if attempt < config.MAX_RETRIES:
            print(f"  [warn] retrying in {backoff:.0f}s...")
            time.sleep(backoff)
            backoff *= config.BACKOFF_MULTIPLIER

    raise RuntimeError(
        f"Translation failed after {config.MAX_RETRIES} attempts. Last error: {last_error}"
    )


def _parse_response(response) -> Tuple[str, Dict[str, Any]]:
    raw_text = getattr(response, "text", None)
    if not raw_text:
        raise RuntimeError(f"Empty response from model: {response!r}")

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Model did not return valid JSON: {exc}\nRaw output: {raw_text!r}")

    translation = (data.get("translation") or "").strip()
    additions = data.get("glossary_additions") or {}

    if not translation:
        raise RuntimeError("Model response was missing a non-empty 'translation' field.")

    return translation, additions
