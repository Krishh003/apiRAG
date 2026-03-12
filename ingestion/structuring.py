"""
Structuring Step — uses Gemini Flash to normalize raw text blocks
(from Playwright scraper) and OpenAPI-parsed entries into the
unified APIEntry schema.

Also responsible for extracting graph relationships:
  requires, triggers, precedes
"""

import json
import logging
import re
from typing import List, Optional, Dict
import google.generativeai as genai
from models import APIEntry, APIParameter

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are an API documentation parser. Extract structured information from the raw API documentation text below.

Return ONLY a valid JSON object with this exact structure. No markdown, no explanation, just JSON.

{{
  "name": "Short descriptive name for this API endpoint",
  "platform": "{platform}",
  "category": "{category}",
  "method": "GET|POST|PUT|PATCH|DELETE",
  "endpoint": "/path/to/endpoint",
  "base_url": "https://...",
  "auth": "How to authenticate (e.g. Bearer token, API Key)",
  "parameters": [
    {{"name": "param_name", "required": true/false, "type": "string/integer/boolean/object", "description": "What this param does", "example": "example value"}}
  ],
  "response_fields": ["field1", "field2"],
  "description": "Full technical description of what this API does",
  "plain_explanation": "Simple non-technical explanation of what this API does and when to use it, written for someone with no technical background",
  "requires": ["Name of API that must be called before this one"],
  "triggers": ["Name of API or event this call triggers, e.g. webhooks"],
  "precedes": ["Name of API typically called after this one in a workflow"],
  "doc_url": "{source_url}"
}}

Rules:
- If a field cannot be determined from the text, use an empty string or empty array
- parameters array can be empty if none are discernible
- plain_explanation must be at least 2 sentences and use zero technical jargon
- requires/triggers/precedes should contain names of OTHER APIs in the {platform} ecosystem
- If the text does not describe a specific API endpoint, return {{"skip": true}}

Raw documentation text:
---
{raw_text}
---"""

ENRICHMENT_PROMPT = """You are an API documentation expert. Improve the plain_explanation and extract graph relationships for this API entry.

Current entry:
{entry_json}

Tasks:
1. Rewrite plain_explanation to be clearer for a non-technical business user. At least 2 sentences. No jargon.
2. Identify requires: what other APIs must be called BEFORE this one? (e.g. "Create Payment Intent" must precede "Confirm Payment Intent")
3. Identify triggers: what webhooks or callbacks does this API fire?
4. Identify precedes: what APIs are typically called AFTER this one?

Return ONLY a JSON object with these fields:
{{"plain_explanation": "...", "requires": [...], "triggers": [...], "precedes": [...]}}"""


class StructuringPipeline:

    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config={"temperature": 0.1},  # Low temp for structured output
        )

    def _call_gemini(self, prompt: str) -> Optional[str]:
        """Call Gemini and return raw text response."""
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            logger.error(f"Gemini call failed: {e}")
            return None

    def _parse_json_response(self, text: str) -> Optional[Dict]:
        """Safely parse JSON from Gemini response, stripping any markdown."""
        if not text:
            return None
        # Strip markdown code fences if present
        text = re.sub(r"```(?:json)?", "", text).strip()
        text = text.strip("`").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        logger.warning(f"Could not parse JSON from response: {text[:200]}")
        return None

    def structure_raw_block(self, block: Dict) -> Optional[APIEntry]:
        """
        Convert a raw scraped text block into a structured APIEntry.
        Used for Playwright-scraped Meta/WhatsApp/Instagram content.
        """
        prompt = EXTRACTION_PROMPT.format(
            platform=block.get("platform", ""),
            category=block.get("category", ""),
            source_url=block.get("source_url", ""),
            raw_text=block.get("raw_text", ""),
        )

        response_text = self._call_gemini(prompt)
        data = self._parse_json_response(response_text)

        if not data:
            return None
        if data.get("skip"):
            return None
        if not data.get("name") or not data.get("description"):
            return None

        # Convert parameters list to APIParameter objects
        params = []
        for p in data.get("parameters", []):
            if isinstance(p, dict) and p.get("name"):
                params.append(APIParameter(
                    name=p.get("name", ""),
                    required=bool(p.get("required", False)),
                    type=str(p.get("type", "string")),
                    description=str(p.get("description", "")),
                    example=str(p.get("example", "")),
                ))

        try:
            return APIEntry(
                name=data.get("name", block.get("heading", "Unknown")),
                platform=data.get("platform", block.get("platform", "")),
                category=data.get("category", block.get("category", "")),
                method=data.get("method", "GET").upper(),
                endpoint=data.get("endpoint", ""),
                base_url=data.get("base_url", ""),
                auth=data.get("auth", ""),
                parameters=params,
                response_fields=data.get("response_fields", []),
                description=data.get("description", ""),
                plain_explanation=data.get("plain_explanation", ""),
                requires=data.get("requires", []),
                triggers=data.get("triggers", []),
                precedes=data.get("precedes", []),
                doc_url=data.get("doc_url", block.get("source_url", "")),
            )
        except Exception as e:
            logger.error(f"Failed to build APIEntry from data: {e}")
            return None

    def enrich_openapi_entry(self, entry: APIEntry) -> APIEntry:
        """
        Enrich an OpenAPI-parsed entry with better plain_explanation
        and graph relationship extraction.
        """
        entry_dict = entry.dict()
        # Keep parameters minimal for the prompt to reduce tokens
        entry_dict_light = {k: v for k, v in entry_dict.items()
                           if k in ["name", "platform", "category", "method",
                                   "endpoint", "description", "plain_explanation"]}

        prompt = ENRICHMENT_PROMPT.format(
            entry_json=json.dumps(entry_dict_light, indent=2)
        )

        response_text = self._call_gemini(prompt)
        data = self._parse_json_response(response_text)

        if data:
            if data.get("plain_explanation"):
                entry.plain_explanation = data["plain_explanation"]
            if data.get("requires"):
                entry.requires = data["requires"]
            if data.get("triggers"):
                entry.triggers = data["triggers"]
            if data.get("precedes"):
                entry.precedes = data["precedes"]

        return entry

    def structure_raw_blocks_batch(
        self, blocks: List[Dict], enrich: bool = True
    ) -> List[APIEntry]:
        """
        Process a list of raw scraped blocks into APIEntry objects.
        Skips blocks that don't resolve to a valid API endpoint.
        """
        entries = []
        seen_names = set()

        for i, block in enumerate(blocks):
            logger.info(f"Structuring block {i+1}/{len(blocks)}: {block.get('heading', '')[:60]}")
            entry = self.structure_raw_block(block)

            if not entry:
                logger.debug(f"Block {i+1} skipped (no valid API found)")
                continue

            # Deduplicate by name
            if entry.name in seen_names:
                logger.debug(f"Duplicate skipped: {entry.name}")
                continue
            seen_names.add(entry.name)

            entries.append(entry)

        logger.info(f"Structuring: {len(entries)} valid API entries from {len(blocks)} blocks")
        return entries

    def enrich_openapi_entries_batch(self, entries: List[APIEntry]) -> List[APIEntry]:
        """
        Enrich a batch of OpenAPI entries with plain explanations and graph relationships.
        """
        enriched = []
        for i, entry in enumerate(entries):
            logger.info(f"Enriching {i+1}/{len(entries)}: {entry.name}")
            enriched.append(self.enrich_openapi_entry(entry))
        return enriched
