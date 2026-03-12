"""
Shared Pydantic models for the unified API entry schema.
Every ingestion source normalizes to APIEntry before storage.
"""

from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field


class APIParameter(BaseModel):
    name: str
    required: bool = False
    type: str = "string"
    description: str = ""
    example: str = ""


class APIEntry(BaseModel):
    """
    Unified schema for every API endpoint in the system.
    All ingestion sources (OpenAPI, scraper, manual) normalize to this.
    """
    # Identity
    name: str
    platform: str                          # e.g. WhatsApp, Meta, Stripe
    category: str                          # e.g. Messaging, Payments, Ads

    # Technical
    method: str = "GET"                    # HTTP verb
    endpoint: str                          # e.g. /v1/{phone-number-id}/messages
    base_url: str = ""                     # e.g. https://graph.facebook.com
    auth: str = ""                         # e.g. Bearer token
    parameters: List[APIParameter] = []
    response_fields: List[str] = []

    # Documentation
    description: str                       # Full technical description
    plain_explanation: str                 # Non-technical plain English
    doc_url: str = ""

    # Graph relationships (populated by structuring step)
    requires: List[str] = Field(default_factory=list)    # Must call these first
    triggers: List[str] = Field(default_factory=list)    # Calling this fires these
    precedes: List[str] = Field(default_factory=list)    # Typically followed by these

    # Internal API wrapper flag
    is_internal: bool = False
    internal_notes: str = ""

    class Config:
        extra = "ignore"


class QueryRequest(BaseModel):
    question: str
    platform_filter: Optional[str] = None
    category_filter: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    query_type: str                        # "lookup" or "planning"
    sources: List[dict] = []
    plan_steps: List[dict] = []           # Only populated for planning queries


class ScrapeRequest(BaseModel):
    platforms: Optional[List[str]] = None  # None = scrape all
