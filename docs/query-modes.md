# Query Modes

The system supports four query modes. Every incoming question is automatically classified and routed to the appropriate handler. Users can also force a specific mode via the UI mode selector.

**Classification priority**: advisory > comparison > planning > lookup

---

## Lookup

**Handler**: [query/lookup_handler.py](../query/lookup_handler.py)
**LLM**: Gemini 2.5 Flash
**Purpose**: Answer factual questions about what a specific API does.

### When it triggers

- "What does the WhatsApp Send Message API do?"
- "Tell me about Stripe Payment Intents"
- "How does the SendGrid Mail Send endpoint work?"

Any question that does not match advisory, comparison, or planning patterns defaults to lookup.

### How it works

1. **Hybrid search** (`top_k=6`): Vector similarity + BM25 keyword matching, merged via RRF
2. **Rerank** (`top_k=4`): Cross-encoder scores each (question, document) pair
3. **Filter**: Sources with relevance < 0.15 are excluded from the answer context
4. **Generate**: Gemini Flash produces a plain-English explanation (max 1,500 tokens)
5. **Confidence**: Mean relevance score of remaining sources after filtering

### Response shape

```json
{
  "answer": "The WhatsApp Send Message API lets you...",
  "query_type": "lookup",
  "sources": [
    {
      "name": "WhatsApp Send Message",
      "platform": "WhatsApp",
      "category": "Messaging",
      "endpoint": "/v1/{phone-number-id}/messages",
      "method": "POST",
      "relevance": 0.94,
      "source": "vector"
    }
  ],
  "plan_steps": [],
  "confidence": 0.92,
  "confidence_label": "high"
}
```

---

## Planning

**Handler**: [query/planning_handler.py](../query/planning_handler.py)
**LLM**: Gemini 2.5 Pro
**Purpose**: Generate step-by-step API call plans for achieving a goal.

### When it triggers

- "How do I charge a customer for their order?"
- "What steps are needed to send a verification SMS?"
- "How can I track a shipment with the Shopify API?"

Planning is detected via keywords like "how do I", "steps", "workflow", "integrate", "implement", "sequence".

### How it works

1. **Keyword extraction**: Gemini Flash extracts relevant API/platform keywords from the question
2. **Graph traversal**: Neo4j queries traverse REQUIRES, TRIGGERS, and PRECEDES edges to find multi-hop API workflows
3. **Hybrid search**: Vector + BM25 fills in parameter details for each API in the workflow
4. **Rerank**: Cross-encoder scores and selects top sources
5. **Filter**: Sources with relevance < 0.15 excluded
6. **Generate**: Gemini Pro produces a step-by-step plan with specific endpoints, parameters, and return values

### Response shape

```json
{
  "answer": "To charge a customer, you need to follow these steps...",
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
    },
    {
      "step": 2,
      "api_name": "Stripe Confirm Payment Intent",
      "platform": "Stripe",
      "endpoint": "POST /v1/payment_intents/{id}/confirm",
      "purpose": "Confirm and execute the payment",
      "parameters": ["payment_method (required)"],
      "returns": "Payment status confirmation"
    }
  ],
  "confidence": 0.88,
  "confidence_label": "high"
}
```

### Graph relationship dependency

Planning quality depends on the density of REQUIRES/TRIGGERS/PRECEDES relationships in Neo4j. These are extracted by Gemini Flash during ingestion. If source documentation does not clearly describe dependencies, relationships may be sparse.

Check relationship density:
```cypher
MATCH ()-[r]->() RETURN type(r), count(r) ORDER BY count(r) DESC
```

---

## Advisory

**Handler**: [query/advisory_handler.py](../query/advisory_handler.py)
**LLM**: Gemini 2.5 Pro
**Purpose**: Provide expert data engineering advice for design, diagnostic, and analytical questions.

### When it triggers

- "Why do Shopify numbers differ from GA4?"
- "What SQL query calculates daily revenue from Stripe?"
- "How should we design a data warehouse schema for our marketing data?"
- "What's causing duplicate events in our Firebase analytics?"

Advisory is detected via keywords like "why", "should", "design", "SQL", "schema", "diagnose", "attribute", "discrepancy".

### How it works

1. **Hybrid search** (`top_k=8`): Retrieves KB entries as grounding context
2. **Rerank** (`top_k=4`): Cross-encoder selects most relevant entries
3. **Generate**: Gemini Pro with a data engineering expert persona + non-technical audience framing

### Key difference from lookup

Unlike lookup (which only answers from KB context), the advisory handler **permits Gemini to use its general knowledge**. KB context serves as supplementary grounding, not a hard constraint. This is intentional -- advisory questions like "why do Shopify and GA4 numbers differ?" require domain expertise that cannot be grounded purely in API documentation.

### System prompt characteristics

- Data engineering expert persona
- Targets non-technical audience (plain language, analogies, no jargon)
- No conversational openers ("Of course.", "Certainly.")
- Explains technical concepts through everyday comparisons

### Response shape

```json
{
  "answer": "Shopify and GA4 often show different numbers because...",
  "query_type": "advisory",
  "sources": [...],
  "plan_steps": [],
  "confidence": 0.78,
  "confidence_label": "medium"
}
```

---

## Comparison

**Handler**: [query/comparison_handler.py](../query/comparison_handler.py)
**LLM**: Gemini 2.5 Flash
**Purpose**: Compare multiple API concepts side-by-side.

### When it triggers

- "What is the difference between capturing and confirming a PaymentIntent?"
- "Compare WhatsApp message templates vs. regular messages"
- "How do Stripe charges differ from payment intents?"

Comparison is detected via keywords like "difference between", "compare", "vs", "versus", "differ".

### How it works

1. **Full-question search** (`top_k=6`): Initial hybrid search to infer which platforms are relevant (top 2 by vote count = `allowed_platforms`)
2. **Concept extraction**: Gemini Flash extracts individual concepts (e.g., `["Capture a PaymentIntent", "Confirm a PaymentIntent"]`)
3. **Per-concept retrieval**: For each concept:
   a. Hybrid search (`top_k=4`, filtered to `allowed_platforms`)
   b. Post-filter results to allowed platforms
   c. Cross-encoder rerank against the **concept** (not the full question)
   d. Take top-1 result as the source for that concept
4. **Generate**: Gemini Flash produces a side-by-side comparison

### Why per-concept retrieval matters

Without per-concept retrieval, all sources are scored against the full comparison question. The cross-encoder penalizes the mismatch between a concept-specific document (e.g., "Capture a PaymentIntent") and a comparison-framed query (e.g., "What is the difference between..."). This produces near-zero relevance scores and ~36% confidence.

With per-concept retrieval, each source scores 80-100% against its specific concept, producing meaningful relevance scores and high overall confidence.

### Platform coherence

The handler infers allowed platforms from the initial full-question search to prevent unrelated matches. For example, a concept like "Create" would otherwise match APIs across all platforms.

### Response shape

```json
{
  "answer": "**Capturing** a PaymentIntent means... **Confirming** a PaymentIntent means...",
  "query_type": "comparison",
  "sources": [
    {
      "name": "Stripe Capture Payment Intent",
      "platform": "Stripe",
      "relevance": 0.96,
      "source": "vector"
    },
    {
      "name": "Stripe Confirm Payment Intent",
      "platform": "Stripe",
      "relevance": 0.93,
      "source": "vector"
    }
  ],
  "plan_steps": [],
  "confidence": 0.95,
  "confidence_label": "high"
}
```

---

## Classification Logic

The classifier ([query/classifier.py](../query/classifier.py)) uses a two-stage approach:

### Stage 1: Keyword Heuristics (fast)

Pattern-matched keyword sets for each mode:

| Mode | Signal Keywords |
|---|---|
| Advisory | "why", "should", "design", "SQL", "schema", "diagnose", "discrepancy", "attribute" |
| Comparison | "difference between", "compare", "vs", "versus", "differ" |
| Planning | "how do I", "steps", "workflow", "integrate", "implement", "sequence" |

If a clear signal is detected, classification is immediate (no LLM call).

### Stage 2: Gemini Flash Fallback

If heuristics are ambiguous, the full question is sent to Gemini Flash with a classification prompt. The model returns one of: `lookup`, `planning`, `advisory`, `comparison`.

### Priority

When multiple signals match, priority determines the winner:
**advisory > comparison > planning > lookup**

This means a question like "Why is the difference between X and Y important?" would be classified as advisory, not comparison.
