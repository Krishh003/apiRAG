# Ingestion Guide

This guide explains how data enters the knowledge base, how to add new platforms, and how to manage the ingestion pipeline.

---

## Ingestion Sources

The system supports three ingestion methods:

| Method | When to Use | Parser |
|---|---|---|
| **OpenAPI specs** | Platform publishes an OpenAPI/Swagger spec (JSON or YAML) | [openapi_parser.py](../ingestion/openapi_parser.py) |
| **Curated JSON** | No OpenAPI spec available; you write definitions by hand | [scheduler.py](../ingestion/scheduler.py) |
| **Playwright scraping** | One-off URL scraping for non-Meta documentation sites | [playwright_scraper.py](../ingestion/playwright_scraper.py) |

Additionally, users can add entries through:
- **Manual entry**: POST /api/apis or the "Add API" button in the UI
- **File upload**: POST /api/upload or the "Upload File" tab (.json, .csv, .txt, .pdf, .md)

---

## Current Platforms

| Platform | Method | Source | Entry Count |
|---|---|---|---|
| Twilio Messaging | OpenAPI JSON | github.com/twilio/twilio-oai | varies |
| Twilio Verify | OpenAPI JSON | github.com/twilio/twilio-oai | varies |
| Twilio Lookup | OpenAPI JSON | github.com/twilio/twilio-oai | varies |
| SendGrid | OpenAPI YAML | github.com/twilio/sendgrid-oai | varies |
| Stripe | OpenAPI JSON | github.com/stripe/openapi | ~20 (filtered) |
| Google Maps | Manual definitions | Hardcoded in openapi_parser.py | 5 |
| WhatsApp | OpenAPI YAML | github.com/facebook/openapi | ~22 (filtered) |
| Meta Graph API | Curated JSON | meta_api_definitions.json | 9 |
| Instagram | Curated JSON | meta_api_definitions.json | 4 |
| GA4 | Curated JSON | ga4_api_definitions.json | 9 |
| Meta Ads | Curated JSON | meta_ads_api_definitions.json | 8 |
| Meta Pixel / CAPI | Curated JSON | meta_pixel_capi_definitions.json | 7 |
| Shopify | Curated JSON | shopify_api_definitions.json | 9 |
| AppsFlyer | Curated JSON | appsflyer_api_definitions.json | 6 |
| Firebase | Curated JSON | firebase_api_definitions.json | 6 |

---

## How to Add a New Platform

### Option A: OpenAPI Spec (Preferred)

If the platform publishes an OpenAPI spec:

1. **Find the spec URL** on GitHub or the platform's developer docs (JSON or YAML)

2. **Add the source** to the `OPENAPI_SOURCES` dict in [ingestion/openapi_parser.py](../ingestion/openapi_parser.py):
   ```python
   OPENAPI_SOURCES = {
       # ...existing sources...
       "NewPlatform": {
           "url": "https://raw.githubusercontent.com/.../spec.json",
           "format": "json",  # or "yaml"
           "platform": "NewPlatform",
           "category": "Payments",  # default category
       }
   }
   ```

3. **Write a parse function** if the spec needs filtering (e.g., Stripe filters to 20 key endpoints):
   ```python
   async def parse_new_platform(spec_data: dict) -> list[APIEntry]:
       # Extract operations, filter if needed
       # Return list of APIEntry objects
   ```

4. **Register in scheduler** -- add the platform name to the `run_scrape_pipeline()` platform list in [ingestion/scheduler.py](../ingestion/scheduler.py)

5. **Trigger ingestion**:
   ```powershell
   Invoke-RestMethod -Uri "http://localhost:8000/admin/scrape" -Method POST `
     -ContentType "application/json" -Body '{"platforms": ["NewPlatform"]}'
   ```

6. **Verify**: Check the health endpoint and query the new platform
   ```powershell
   Invoke-RestMethod -Uri "http://localhost:8000/health"
   ```

### Option B: Curated JSON

If no OpenAPI spec is available:

1. **Create a JSON file** in `ingestion/` following this format:
   ```json
   [
     {
       "name": "Platform Get Resource",
       "category": "PlatformName",
       "endpoint": "GET /v1/resources/{id}",
       "base_url": "https://api.platform.com",
       "auth": "Bearer token in Authorization header",
       "description": "Technical description of what this endpoint does, including parameters and response format.",
       "plain_explanation": "In simple terms, this lets you look up a specific resource by its ID. Think of it like searching for a customer record in a database."
     }
   ]
   ```

2. **Register in scheduler** -- add a `_load_json_definitions()` call in `run_scrape_pipeline()`:
   ```python
   self._load_json_definitions(
       filename="newplatform_api_definitions.json",
       platforms=["NewPlatform"],
       default_base_url="https://api.platform.com",
       default_auth="Bearer token"
   )
   ```

3. **Trigger ingestion** (same as above)

### Option C: File Upload

For one-off additions without modifying code:

1. Prepare a `.json` file with an array of API definitions (same format as curated JSON above)
2. Upload via the UI ("Add API" button > "Upload File" tab) or API:
   ```powershell
   Invoke-RestMethod -Uri "http://localhost:8000/api/upload" -Method POST `
     -InFile "path/to/definitions.json" -ContentType "multipart/form-data"
   ```

---

## Curated JSON Schema

Each entry in a curated JSON file supports these fields:

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Short descriptive name (e.g., "Stripe Create Payment Intent") |
| `category` | Yes | Platform name or sub-grouping |
| `endpoint` | Yes | HTTP method + path (e.g., "POST /v1/payment_intents") |
| `base_url` | No | Base URL (e.g., "https://api.stripe.com") |
| `auth` | No | Authentication method description |
| `description` | Yes | Technical description |
| `plain_explanation` | Yes | Non-technical explanation in simple terms |

The `_load_json_definitions()` function maps these to full `APIEntry` objects, applying defaults for `base_url` and `auth` if not specified per-entry.

---

## Scheduled Ingestion

The system uses APScheduler to run the full ingestion pipeline on a weekly cron schedule.

**Default**: Every Sunday at 02:00 IST (Asia/Kolkata)

Configure via environment variables:
```
SCRAPE_CRON_DAY=sun     # mon, tue, wed, thu, fri, sat, sun
SCRAPE_CRON_HOUR=2      # 0-23
```

The scheduler starts automatically when the FastAPI app starts (configured in `main.py` lifespan).

### Manual Trigger

```powershell
# All platforms
Invoke-RestMethod -Uri "http://localhost:8000/admin/scrape" -Method POST `
  -ContentType "application/json" -Body '{}'

# Specific platforms only
Invoke-RestMethod -Uri "http://localhost:8000/admin/scrape" -Method POST `
  -ContentType "application/json" -Body '{"platforms": ["Stripe", "Twilio"]}'
```

### Check Status

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/admin/scrape/status"
```

Returns:
```json
{
  "last_run": "2026-03-17T02:00:00",
  "last_status": "success",
  "last_counts": {"Stripe": 20, "Twilio": 15},
  "is_running": false,
  "total_apis_stored": 177,
  "next_scheduled_run": "2026-03-24T02:00:00"
}
```

---

## Gemini Enrichment

When ingesting from OpenAPI specs or Playwright scraping, raw API data is enriched by Gemini Flash:

- **plain_explanation**: A non-technical explanation of what the endpoint does
- **requires**: APIs that must be called before this one
- **triggers**: Events or APIs this call fires
- **precedes**: APIs typically called after this one

These relationship fields populate the Neo4j graph and are critical for planning query quality.

Curated JSON definitions skip Gemini enrichment because `plain_explanation` is written by hand and relationship fields are optional.

---

## Storage Layer

Every ingested `APIEntry` is stored in two places:

1. **ChromaDB**: Vector embeddings (bge-large-en-v1.5) + BM25 keyword index for retrieval
2. **Neo4j**: Graph nodes and relationships for workflow traversal

Both stores use upsert semantics -- re-ingesting the same entry updates it rather than creating duplicates. The unique key is `(name, platform)`.

---

## Internal API Wrappers

A template for internal API wrapper entries is available at [internal_api_template.json](../internal_api_template.json).

Internal entries have `is_internal: true` and can include `internal_notes` with environment-specific context (staging URLs, credential locations, etc.) that should not be exposed to external documentation.

Upload via the UI or API using the same process as curated JSON files.
