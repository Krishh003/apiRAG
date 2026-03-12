"""
Query Classifier — determines if a query is a LOOKUP or PLANNING query.

LOOKUP  — "What does X API do?" → simple retrieval, Gemini Flash
PLANNING — "How do I achieve Y?" → graph traversal + multi-step plan, Gemini Pro

Uses a fast keyword heuristic first, Gemini Flash as fallback for ambiguous cases.
"""

import logging
import re
from typing import Tuple
import google.generativeai as genai

logger = logging.getLogger(__name__)

# Keywords strongly indicating a planning query
PLANNING_SIGNALS = [
    r"\bhow (do|can|would|should) (i|we|you)\b",
    r"\bwhat (api calls?|apis?|steps?|endpoints?)\b.*(need|require|use|call)\b",
    r"\bwhat do (i|we) need\b",
    r"\bsteps? (to|for)\b",
    r"\bworkflow\b",
    r"\bsequence\b",
    r"\bprocess (to|for)\b",
    r"\bto (achieve|accomplish|implement|set up|enable|create|send|charge|get)\b",
    r"\bintegrat\b",
    r"\bend.to.end\b",
    r"\bwhat.*(required|needed)\b",
    r"\bwalk me through\b",
    r"\bguide me\b",
]

# Keywords strongly indicating a lookup query
LOOKUP_SIGNALS = [
    r"\bwhat (is|does|are)\b",
    r"\bexplain\b",
    r"\bdescribe\b",
    r"\btell me about\b",
    r"\bwhat.*(do|does).*(do|mean|return|accept)\b",
    r"\bwhat.*(purpose|point|use|function)\b",
    r"\bdifference between\b",
    r"\bwhen (to|should)\b",
    r"\blist (all|the)?\b",
    r"\bshow me\b",
]

CLASSIFY_PROMPT = """Classify this user query about APIs as either LOOKUP or PLANNING.

LOOKUP = The user wants to understand what an API does, what it returns, or how it works.
PLANNING = The user wants to know what API calls to make to achieve a specific outcome.

Query: "{query}"

Respond with exactly one word: LOOKUP or PLANNING"""


class QueryClassifier:

    def __init__(self, gemini_api_key: str):
        genai.configure(api_key=gemini_api_key)
        self._model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config={"temperature": 0, "max_output_tokens": 10},
        )

    def classify(self, query: str) -> Tuple[str, str]:
        """
        Returns (query_type, method) where:
          query_type: "lookup" or "planning"
          method: "heuristic" or "gemini" (for debugging)
        """
        query_lower = query.lower().strip()

        # Fast heuristic pass — check keywords
        planning_score = sum(
            1 for pattern in PLANNING_SIGNALS
            if re.search(pattern, query_lower)
        )
        lookup_score = sum(
            1 for pattern in LOOKUP_SIGNALS
            if re.search(pattern, query_lower)
        )

        if planning_score > lookup_score and planning_score >= 1:
            return "planning", "heuristic"
        if lookup_score > planning_score and lookup_score >= 1:
            return "lookup", "heuristic"

        # Ambiguous — use Gemini Flash to classify
        try:
            response = self._model.generate_content(
                CLASSIFY_PROMPT.format(query=query)
            )
            result = response.text.strip().upper()
            if "PLANNING" in result:
                return "planning", "gemini"
            return "lookup", "gemini"
        except Exception as e:
            logger.warning(f"Gemini classifier failed: {e} — defaulting to lookup")
            return "lookup", "fallback"
