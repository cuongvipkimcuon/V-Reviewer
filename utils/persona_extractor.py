# utils/persona_extractor.py - V6 MODULE 2: Persona Extraction Service
"""
Input: Raw Chunk + Persona (e.g. @Analyst).
Logic: Use persona's extractor_prompt to map synonyms (e.g. "BLK" -> "Black"), capture intents (e.g. "Cancelled").
Output: Structured content + meta_json for storage in chunks.
"""
import json
import re
from typing import Any, Dict, List, Optional

from persona import PersonaSystem


def _get_extractor_prompt(persona_key: str) -> str:
    p = PersonaSystem.get_persona(persona_key)
    return (p.get("extractor_prompt") or "").strip()


def _call_extractor_llm(raw_content: str, extractor_prompt: str) -> Optional[str]:
    """Call LLM with extractor_prompt to normalize and extract. Returns LLM text or None."""
    try:
        from config import init_services
        from ai_engine import AIService, _get_default_tool_model
    except ImportError:
        return None
    if not extractor_prompt or not raw_content.strip():
        return None
    prompt = """%s

RAW CHUNK (from Excel/CSV row):
---
%s
---

Tasks:
1. Map abbreviations/synonyms to canonical terms (e.g. BLK -> Black, Cancelled -> Status: Cancelled).
2. Capture intents and structured fields.
3. Output a clean Markdown or JSON representation suitable for storage. Preserve traceability hints (sheet, row) in your summary if needed.

Output only the normalized content, no explanation.""" % (
        extractor_prompt,
        raw_content[:8000],
    )
    try:
        resp = AIService.call_openrouter(
            messages=[{"role": "user", "content": prompt}],
            model=_get_default_tool_model(),
            temperature=0.2,
            max_tokens=2000,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return None


class PersonaExtractionService:
    """
    Extract and normalize chunk content using persona's extractor_prompt.
    Saves raw_content + meta_json (with source_metadata and extracted intents/synonyms).
    """

    @staticmethod
    def extract(
        raw_content: str,
        persona_key: str,
        meta_json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Input: raw_content (e.g. one Excel row as text), persona_key (e.g. "Analyst"), optional meta_json.
        Returns: {content: str, meta_json: dict} where content is normalized and meta_json includes
        source_metadata + any extracted intents/synonyms (e.g. intent: "Cancelled", synonyms: {"BLK": "Black"}).
        """
        meta = dict(meta_json or {})
        extractor_prompt = _get_extractor_prompt(persona_key)
        normalized = _call_extractor_llm(raw_content, extractor_prompt)
        content = normalized if normalized else raw_content
        if normalized:
            meta["extracted"] = True
            meta["persona_key"] = persona_key
        return {"content": content, "meta_json": meta}
