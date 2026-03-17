# API Reference

Base URL: `http://localhost:8000`

Interactive Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Query

### POST /api/query

Ask a question. The system auto-classifies the query and routes it to the appropriate handler.

**Request Body**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `question` | string | Yes | The question in plain English |
| `platform_filter` | string | No | Restrict search to a specific platform (e.g., "Stripe") |
| `category_filter` | string | No | Restrict search to a specific category |

**Example Request**

```json
{
  "question": "How do I charge a customer for their order?",
  "platform_filter": "Stripe",
  "category_filter": null
}
```

**Response Body**

| Field | Type | Description |
| --- | --- | --- |
| `answer` | string | The generated answer in plain English |
| `query_type` | string | One of: `lookup`, `planning`, `advisory`, `comparison` |
| `sources` | array | List of source API entries used to generate the answer |
| `plan_steps` | array | Step-by-step plan (planning mode only; empty for other modes) |
| `confidence` | float | Mean relevance score of sources (0.0 - 1.0) |
| `confidence_label` | string | One of: `high`, `medium`, `low` |

**Source Object**

| Field | Type | Description |
| --- | --- | --- |
| `name` | string | API entry name |
| `platform` | string | Platform name |
| `category` | string | Category name |
| `endpoint` | string | URL path (e.g., `/v1/payment_intents`) |
| `method` | string | HTTP method |
| `doc_url` | string | Link to source documentation |
| `relevance` | float | Cross-encoder relevance score (0.0 - 1.0) |
| `source` | string | Retrieval method: `vector` or `graph` |

**Plan Step Object** (planning mode only)

| Field | Type | Description |
| --- | --- | --- |
| `step` | int | Step number in the sequence |
| `api_name` | string | Name of the API to call |
| `platform` | string | Platform name |
| `endpoint` | string | Full endpoint (e.g., `POST /v1/payment_intents`) |
| `purpose` | string | Why this step is needed |
| `parameters` | array[string] | Required and optional parameters with descriptions |
| `returns` | string | What this step returns (used by subsequent steps) |

**Example Response (lookup)**

```json
{
  "answer": "The Stripe Payment Intent API lets you create and manage payment transactions...",
  "query_type": "lookup",
  "sources": [
    {
      "name": "Stripe Create Payment Intent",
      "platform": "Stripe",
      "category": "Payments",
      "endpoint": "/v1/payment_intents",
      "method": "POST",
      "doc_url": "https://stripe.com/docs/api/payment_intents",
      "relevance": 0.94,
      "source": "vector"
    }
  ],
  "plan_steps": [],
  "confidence": 0.92,
  "confidence_label": "high"
}
```

**Example Response (planning)**

```json
{
  "answer": "To charge a customer, follow these steps...",
  "query_type": "planning",
  "sources": [...],
  "plan_steps": [
    {
      "step": 1,
      "api_name": "Stripe Create Payment Intent",
      "platform": "Stripe",
      "endpoint": "POST /v1/payment_intents",
      "purpose": "Create a payment intent to process the charge",
      "parameters": [
        "amount (required) -> order total in smallest currency unit",
        "currency (required) -> e.g. 'inr'"
      ],
      "returns": "client_secret for confirming the payment"
    }
  ],
  "confidence": 0.88,
  "confidence_label": "high"
}
```

---

## API Management

### GET /api/apis

List all stored API entries. Supports optional query parameters for filtering.

**Query Parameters**

| Parameter | Type | Description |
| --- | --- | --- |
| `platform` | string | Filter by platform name |
| `category` | string | Filter by category name |

**Response**: Array of APIEntry objects.

---

### POST /api/apis

Add a single API entry manually.

**Request Body**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | Yes | Descriptive name |
| `platform` | string | Yes | Platform name |
| `category` | string | Yes | Category or sub-grouping |
| `method` | string | No | HTTP method (default: `GET`) |
| `endpoint` | string | Yes | URL path |
| `base_url` | string | No | Base URL |
| `auth` | string | No | Authentication method |
| `description` | string | Yes | Technical description |
| `plain_explanation` | string | Yes | Non-technical explanation |
| `parameters` | array | No | List of APIParameter objects |
| `response_fields` | array | No | Key response fields |
| `requires` | array | No | APIs that must be called first |
| `triggers` | array | No | Events/APIs this fires |
| `precedes` | array | No | APIs typically called after |
| `doc_url` | string | No | Documentation URL |
| `is_internal` | bool | No | Internal API wrapper flag |
| `internal_notes` | string | No | Internal-only context |

**Response**

```json
{
  "message": "API 'Stripe Create Payment Intent' added successfully"
}
```

---

### DELETE /api/apis/{id}

Delete an API entry by its ChromaDB document ID.

**Path Parameters**

| Parameter | Type | Description |
| --- | --- | --- |
| `id` | string | ChromaDB document ID |

**Response**

```json
{
  "message": "API deleted successfully"
}
```

---

### GET /api/platforms

List all unique platform names in the knowledge base.

**Response**: Array of strings.

```json
["AppsFlyer", "Firebase", "GA4", "Google Maps", "Instagram", "Meta", "Meta Ads", "Meta Pixel/CAPI", "SendGrid", "Shopify", "Stripe", "Twilio", "WhatsApp"]
```

---

### GET /api/categories

List all unique category names. Optionally filter by platform.

**Query Parameters**

| Parameter | Type | Description |
| --- | --- | --- |
| `platform` | string | Filter categories by platform |

**Response**: Array of strings.

---

## File Upload

### POST /api/upload

Bulk import API entries from a file.

**Request**: Multipart form data with a `file` field.

**Supported Formats**

| Format | Description |
| --- | --- |
| `.json` | Array of APIEntry objects (or single object) |
| `.csv` | Rows with columns: name, platform, category, endpoint, etc. |
| `.txt` | Key-value blocks separated by blank lines |
| `.pdf` | Text extracted page-by-page; each page treated as one entry |
| `.md` | Parsed by headers (H1/H2/H3); each section treated as one entry |

**Response**

```json
{
  "added": ["API Name 1", "API Name 2"],
  "errors": [],
  "count": 2
}
```

---

## Admin

### POST /admin/scrape

Trigger the full ingestion pipeline. Runs in the background.

**Request Body**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `platforms` | array[string] | No | Specific platforms to scrape. Empty or omitted = all platforms |

**Response**

```json
{
  "message": "Scrape started",
  "platforms": ["Stripe", "Twilio"],
  "status": "running"
}
```

---

### POST /admin/scrape/url

Scrape a single URL via Playwright and ingest the extracted API definitions.

**Request Body**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `url` | string | Yes | Documentation URL to scrape |
| `platform` | string | No | Platform name to assign |
| `category` | string | No | Category to assign |

**Response**

```json
{
  "message": "Scraped successfully",
  "status": "success",
  "count": 3,
  "names": ["API Name 1", "API Name 2", "API Name 3"]
}
```

**Note**: Does not work on Meta developer documentation URLs (Meta blocks headless browsers).

---

### GET /admin/scrape/status

Check the status of the last scrape job.

**Response**

| Field | Type | Description |
| --- | --- | --- |
| `last_run` | string (ISO 8601) | Timestamp of last scrape |
| `last_status` | string | `success`, `failed`, or `running` |
| `last_counts` | object | Per-platform entry counts from last run |
| `is_running` | bool | Whether a scrape is currently in progress |
| `total_apis_stored` | int | Total entries in ChromaDB |
| `next_scheduled_run` | string (ISO 8601) | Next scheduled cron run |

---

## Health

### GET /health

System health check. Verifies ChromaDB, Neo4j connectivity, and platform counts.

**Response**

```json
{
  "status": "healthy",
  "vector_store_count": 177,
  "neo4j": "connected",
  "platforms": ["Stripe", "Twilio", "WhatsApp", "..."]
}
```

---

## Error Responses

All endpoints return standard HTTP error codes:

| Code | Meaning |
| --- | --- |
| 400 | Bad request (missing required fields, invalid format) |
| 404 | Resource not found |
| 422 | Validation error (Pydantic schema mismatch) |
| 500 | Internal server error (LLM failure, DB connection issue) |

Error response body:

```json
{
  "detail": "Description of what went wrong"
}
```
