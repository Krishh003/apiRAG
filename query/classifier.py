"""
Query Classifier — determines if a query is LOOKUP, PLANNING, or ADVISORY.

LOOKUP   — "What does X API do?" → simple retrieval, Gemini Flash
PLANNING — "How do I achieve Y?" → graph traversal + multi-step plan, Gemini Pro
ADVISORY — "Why do Shopify numbers differ from GA4?" / "What SQL query calculates ROAS?"
           → data engineering expert knowledge + KB context, Gemini Pro

Uses a fast keyword heuristic first, Gemini Flash as fallback for ambiguous cases.
"""

import logging
import re
from typing import Tuple
import google.generativeai as genai

logger = logging.getLogger(__name__)

# Keywords strongly indicating an ADVISORY query
# These take priority — checked before planning/lookup signals
ADVISORY_SIGNALS = [
    # Design / schema / architecture questions
    r"\bhow should (we|i|you) (design|structure|model|build|architect|set up|organise|organize)\b",
    r"\bwhat.*(schema|table|warehouse|dashboard|pipeline|etl|data model)\b",
    r"\brecommended.*(schema|table|architecture|approach|design|structure|model)\b",
    r"\bbest (way|practice|approach|method) (to|for)\b",
    # Diagnostic / "why" questions
    r"\bwhy (did|does|is|do|are|doesn't|don't|isn't|aren't)\b",
    r"\bwhy.*(differ|mismatch|drop|decrease|increase|fail|not appear|discrepan|wrong|off)\b",
    r"\bhow (do|can) we (detect|diagnose|debug|monitor|troubleshoot|reconcile|fix)\b",
    r"\bhow.*(debug|diagnose|troubleshoot)\b",
    # SQL / data questions
    r"\bsql\b",
    r"\b(query|queries).*(calculate|compute|join|write|build|design)\b",
    r"\b(calculate|compute).*(sql|query|revenue|roas|ltv|cac|ctr|cvr)\b",
    r"\bwrite.*(sql|query)\b",
    # Attribution / analytics concepts
    r"\battribution (window|model|differ|discrepan)\b",
    r"\b(reconcile|reconciliation)\b",
    r"\bunified attribution\b",
    r"\bmulti.touch\b",
    r"\blast.touch\b",
    r"\bdata.driven attribution\b",
    r"\bROAS\b",
    r"\bLTV\b",
    r"\bcohort (analysis|table)\b",
    r"\bconversion rate.*(calculate|compute|across|between)\b",
    r"\bfunnel (drop.off|analysis|dashboard|report)\b",
    # Data engineering / pipeline topics
    r"\b(incremental|full.refresh).*(pull|load|sync|extract)\b",
    r"\bretry logic\b",
    r"\brate limit.*(handle|design|strategy)\b",
    r"\bduplicate.*(prevent|avoid|dedupli|ingest)\b",
    r"\bdata (freshness|latency|delay|lag)\b",
    r"\bpipeline (fail|monitor|alert|miss)\b",
    r"\bnear.real.time\b",
    r"\bmonitoring (alert|pipeline|data)\b",
    # Tracking infrastructure
    r"\b(gtm|google tag manager).*(structure|set up|container|configure)\b",
    r"\bdeduplication\b",
    r"\bconsent mode\b",
    r"\bevent naming (schema|convention|standard)\b",
    r"\bstandardized? event\b",
    r"\bcustom event.* vs .*(standard|recommended)\b",
    # Dashboard / reporting topics
    r"\bdashboard.*(structure|design|build|architect)\b",
    r"\bmetrics.*(include|dashboard|report|monitor)\b",
    r"\bgrowth (dashboard|report|metric)\b",
    r"\bcampaign performance (dashboard|table|report)\b",
    # Ecommerce analytics
    r"\bdata warehouse (schema|design|table)\b",
    r"\bsku.level\b",
    r"\bdaily revenue\b",
    r"\bad spend\b",
    r"\bwarehouse schema\b",
]

# Keywords strongly indicating a PLANNING query
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

# Keywords strongly indicating a LOOKUP query
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

CLASSIFY_PROMPT = """Classify this user query into exactly one of three categories: LOOKUP, PLANNING, or ADVISORY.

LOOKUP   = The user wants to understand what a specific API does, what it returns, or how it works.
           Examples: "What does the Stripe Payment Intent API do?", "What fields does the GA4 Run Report return?"

PLANNING = The user wants to know what API calls to make, in what order, to achieve a specific outcome.
           Examples: "How do I charge a customer?", "What APIs do I need to send a WhatsApp message?"

ADVISORY = The user wants data engineering design advice, SQL queries, diagnostic help, attribution
           explanations, schema design, pipeline patterns, dashboard architecture, or wants to understand
           why numbers differ between platforms.
           Examples: "Why do Shopify purchases differ from GA4?", "What SQL calculates daily revenue?",
           "How should we design a warehouse schema?", "Why is ROAS decreasing?"

Query: "{query}"

Respond with exactly one word: LOOKUP, PLANNING, or ADVISORY"""


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
          query_type: "lookup", "planning", or "advisory"
          method: "heuristic" or "gemini" (for debugging)
        """
        query_lower = query.lower().strip()

        # Score each category
        advisory_score = sum(
            1 for pattern in ADVISORY_SIGNALS
            if re.search(pattern, query_lower)
        )
        planning_score = sum(
            1 for pattern in PLANNING_SIGNALS
            if re.search(pattern, query_lower)
        )
        lookup_score = sum(
            1 for pattern in LOOKUP_SIGNALS
            if re.search(pattern, query_lower)
        )

        # Advisory takes priority when it has the highest score
        max_score = max(advisory_score, planning_score, lookup_score)
        if max_score >= 1:
            if advisory_score == max_score:
                return "advisory", "heuristic"
            if planning_score == max_score:
                return "planning", "heuristic"
            return "lookup", "heuristic"

        # No heuristic match — use Gemini Flash to classify
        try:
            response = self._model.generate_content(
                CLASSIFY_PROMPT.format(query=query)
            )
            result = response.text.strip().upper()
            if "ADVISORY" in result:
                return "advisory", "gemini"
            if "PLANNING" in result:
                return "planning", "gemini"
            return "lookup", "gemini"
        except Exception as e:
            logger.warning(f"Gemini classifier failed: {e} — defaulting to lookup")
            return "lookup", "fallback"
