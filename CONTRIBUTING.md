# Contributing

Guidelines for contributing to the API Knowledge Base RAG v2 project.

---

## Development Setup

1. Clone the repository and set up the environment:
   ```bash
   git clone <repo-url>
   cd apiRAG
   cp .env.example .env
   # Edit .env with your credentials
   ```

2. Start Neo4j:
   ```bash
   docker-compose up -d
   ```

3. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate      # Linux/macOS
   .\venv\Scripts\activate       # Windows
   pip install -r requirements.txt
   playwright install chromium
   ```

4. Start the development server:
   ```bash
   uvicorn main:app --reload --port 8000
   ```

---

## Project Conventions

### Code Style

- Python code follows standard PEP 8 conventions
- Use type hints for function signatures
- Keep functions focused -- one function, one responsibility

### File Organization

- All FastAPI routes live in [main.py](main.py)
- Data models and schemas live in [models.py](models.py)
- Query handlers go in `query/` -- one file per query mode
- Retrieval logic goes in `retrieval/`
- Ingestion logic goes in `ingestion/`
- Frontend files go in `static/`

### Naming

- Query handlers: `{mode}_handler.py` (e.g., `lookup_handler.py`)
- Curated JSON files: `{platform}_api_definitions.json`
- Functions: `snake_case`
- Classes: `PascalCase`

---

## Common Tasks

### Adding a New Query Mode

1. Add classification signals to [query/classifier.py](query/classifier.py):
   - Add a keyword signal set (e.g., `NEW_MODE_SIGNALS`)
   - Add the mode to the heuristic check and Gemini fallback prompt
   - Decide its priority relative to existing modes

2. Create a handler at `query/new_mode_handler.py`:
   - Accept the question, vector store, graph store, and reranker as arguments
   - Implement retrieval strategy
   - Build a Gemini prompt with system instructions
   - Return a `QueryResponse`

3. Register the handler in [main.py](main.py):
   - Import the handler
   - Add a branch in the `/api/query` endpoint

4. Update the frontend:
   - Add a mode button in the mode selector bar
   - Add a badge color for the new mode
   - Handle the new `query_type` in response rendering

5. Update documentation:
   - Add the mode to [docs/query-modes.md](docs/query-modes.md)
   - Update the README overview table

### Adding a New Platform

See [docs/ingestion.md](docs/ingestion.md) for detailed instructions on adding platforms via OpenAPI specs, curated JSON, or file upload.

### Modifying the Data Model

1. Update the `APIEntry` class in [models.py](models.py)
2. Update the document text builder in [retrieval/vector_store.py](retrieval/vector_store.py) (the function that combines fields into a searchable document)
3. If adding relationship fields, update [retrieval/graph_store.py](retrieval/graph_store.py) Neo4j queries
4. Update curated JSON files and ingestion parsers if needed
5. Re-run ingestion to rebuild the knowledge base with the new schema

---

## Branching and Commits

### Branch Naming

- `feature/description` -- new functionality
- `fix/description` -- bug fixes
- `docs/description` -- documentation changes
- `refactor/description` -- code restructuring

### Commit Messages

Use clear, descriptive commit messages:

```
added comparison query mode with per-concept retrieval
fixed classifier priority for advisory vs comparison
updated Meta API definitions with 4 new Instagram entries
```

---

## Key Constraints

Please keep these constraints in mind when contributing:

- **Gemini only** -- do not introduce OpenAI, Anthropic, or other LLM providers. The system uses Google Gemini exclusively
- **No emojis** -- use SVGs for visual elements in the frontend. No emoji characters anywhere in the codebase or UI
- **Non-technical audience** -- all user-facing text (answers, UI copy) must be written for non-technical users. Plain language, analogies, no jargon
- **One chunk per endpoint** -- never split a single API endpoint's documentation across multiple vector store entries
- **Windows compatibility** -- the development environment is Windows. Use PowerShell syntax in examples, and be mindful of path separators and event loop behavior (Playwright subprocess isolation)

---

## Testing

### Manual Testing

- Query each of the four modes with representative questions
- Check confidence scores and source relevance
- Verify the classifier picks the correct mode
- Test file upload with .json, .pdf, and .md files

### Health Verification

```powershell
# Check system health
Invoke-RestMethod -Uri "http://localhost:8000/health"

# Check scrape status
Invoke-RestMethod -Uri "http://localhost:8000/admin/scrape/status"
```

### Graph Density Check

```cypher
-- Run in Neo4j Browser at http://localhost:7474
MATCH ()-[r]->() RETURN type(r), count(r) ORDER BY count(r) DESC
```

### Sample Questions

A set of 50 sample questions is available in `Data engineer's Assistant sample questions.pdf` for evaluating advisory answer quality.
