# Troubleshooting

Common issues and their solutions.

---

## Startup Issues

### ChromaDB telemetry error in logs

**Symptom**: Noisy error messages about PostHog telemetry on startup.

**Cause**: Version mismatch between chromadb 0.5.23 and its PostHog dependency.

**Fix**: Set `ANONYMIZED_TELEMETRY=False` in `.env`. This is harmless and does not affect functionality.

---

### Neo4j connection refused

**Symptom**: `ServiceUnavailable: Unable to connect to bolt://localhost:7687`

**Cause**: Neo4j Docker container is not running.

**Fix**:
```bash
docker-compose up -d
```

Verify the container is healthy:
```bash
docker ps
```

Wait for the health check to pass (may take 15-30 seconds on first start).

---

### "Model not found" or Gemini API errors

**Symptom**: 500 errors when querying, with Gemini-related error messages in logs.

**Possible causes**:
1. **Invalid API key**: Check `GEMINI_API_KEY` in `.env`
2. **Deprecated model**: Ensure the code uses `gemini-2.5-flash` and `gemini-2.5-pro` (not 1.5 versions)
3. **Rate limiting**: Google AI Studio free tier has request limits. Wait and retry, or upgrade to a paid plan
4. **Network issue**: Verify the server can reach `generativelanguage.googleapis.com`

---

### Embedding model download fails

**Symptom**: Error on first startup when downloading `BAAI/bge-large-en-v1.5`.

**Cause**: Network connectivity issue or disk space shortage (~1.3 GB needed).

**Fix**: Ensure internet access and sufficient disk space. The model is cached after first download in the HuggingFace cache directory.

---

## Query Issues

### Low confidence scores

**Symptom**: Answers have confidence below 50%.

**Possible causes**:
1. **Knowledge base is empty**: Check `GET /health` for `vector_store_count`. If 0, run ingestion
2. **Question is outside KB scope**: The system only knows about indexed APIs. Advisory mode can use general knowledge for broader questions
3. **Wrong mode classification**: Try forcing a specific mode in the UI to see if results improve

---

### Classifier picks the wrong mode

**Symptom**: A planning question gets classified as lookup, or a comparison question gets classified as advisory.

**Cause**: The keyword heuristics or Gemini fallback misclassified the question.

**Fix**:
1. Use the mode selector in the UI to force the correct mode
2. If a pattern is consistently misclassified, add keywords to the relevant signal list in [query/classifier.py](../query/classifier.py)

Classification priority: advisory > comparison > planning > lookup. A question matching advisory keywords will never be classified as comparison.

---

### Planning queries return generic answers (no plan steps)

**Symptom**: Planning response has an `answer` but empty `plan_steps`.

**Cause**: Sparse graph relationships in Neo4j. The REQUIRES, TRIGGERS, and PRECEDES edges are extracted by Gemini during ingestion. If source docs do not clearly describe API dependencies, relationships may be missing.

**Diagnosis**: Check graph relationship density in Neo4j Browser (http://localhost:7474):
```cypher
MATCH ()-[r]->() RETURN type(r), count(r) ORDER BY count(r) DESC
```

**Fix**: Add relationships manually via the `requires`, `triggers`, and `precedes` fields when adding APIs through the UI or API.

---

### Comparison query shows low relevance

**Symptom**: Comparison sources show relevance scores below 50%.

**Cause**: This was a known issue (resolved in v2). If it still occurs, it may be because:
1. The concepts extracted by Gemini do not match well to any KB entries
2. The platform coherence filter is excluding relevant entries

**Fix**: Check the logs for which concepts were extracted and which platforms were inferred. If the inferred platforms are wrong, try adding a platform filter to the query.

---

## Ingestion Issues

### Scrape returns 0 entries for a platform

**Symptom**: `POST /admin/scrape` completes but a platform shows 0 entries.

**Possible causes**:
1. **Meta platforms**: Meta blocks headless browsers. Use curated JSON files instead of Playwright
2. **OpenAPI spec URL changed**: The GitHub repository may have reorganized. Check the URL in `OPENAPI_SOURCES`
3. **Rate limiting**: GitHub raw content URLs may rate-limit requests. Wait and retry
4. **Spec format changed**: The OpenAPI spec structure may have changed. Check parser compatibility

---

### Playwright scraping times out

**Symptom**: "From Website" single-URL scraping hangs or returns 0 blocks.

**Possible causes**:
1. **Meta URLs**: Meta developer docs block all headless browsers. This is expected behavior
2. **JavaScript-heavy page**: Some sites require full JS rendering. The scraper waits for `domcontentloaded`, not `networkidle`
3. **Bot detection**: Some sites block automated browsers despite realistic user-agent strings

**Fix**: For blocked sites, use curated JSON definitions instead of scraping.

---

### Duplicate entries after re-ingestion

**Symptom**: Entry count doubles after running ingestion again.

**This should not happen**: Both ChromaDB and Neo4j use upsert semantics with `(name, platform)` as the unique key. If duplicates appear, check whether entries have slightly different names across ingestion runs.

---

## Frontend Issues

### UI not loading

**Symptom**: http://localhost:8000 shows a blank page or 404.

**Cause**: The static file mount may not be working.

**Fix**: Verify that the `static/` directory exists and contains `index.html`. The FastAPI app mounts it at startup in `main.py`.

---

### Dark mode not toggling

**Symptom**: Theme toggle button does not switch between light and dark.

**Fix**: Hard refresh the page (Ctrl+Shift+R) to clear cached CSS.

---

## Database Issues

### ChromaDB data lost after restart

**Symptom**: `vector_store_count` drops to 0 after server restart.

**Cause**: ChromaDB was initialized with an in-memory path instead of persistent storage.

**Fix**: Ensure `CHROMA_PATH=./chroma_db` is set in `.env` and the directory exists.

---

### Neo4j "authentication failed"

**Symptom**: `AuthError: The client is unauthorized due to authentication failure`

**Cause**: `NEO4J_PASSWORD` in `.env` does not match the password set in the Docker container.

**Fix**: The Neo4j password is set on first container start from the `NEO4J_AUTH` environment variable in `docker-compose.yml`. To reset:

1. Stop the container: `docker-compose down`
2. Remove the data volume: `docker volume rm apirag_neo4j_data`
3. Update `NEO4J_PASSWORD` in `.env`
4. Start fresh: `docker-compose up -d`

**Warning**: Removing the volume deletes all graph data. Re-run ingestion to rebuild.

---

## Windows-Specific Issues

### `curl` commands fail in PowerShell

**Symptom**: curl commands from documentation return errors like `A parameter cannot be found that matches parameter name 'X'`.

**Cause**: On Windows PowerShell, `curl` is an alias for `Invoke-WebRequest`, which has completely different syntax.

**Fix**: Use PowerShell-native syntax:
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health"
```

Or use the examples in this documentation, which provide both PowerShell and bash/curl commands.

---

### Playwright event loop error

**Symptom**: `RuntimeError: This event loop is already running` when using Playwright.

**Cause**: Windows uses ProactorEventLoop which conflicts with Playwright's asyncio requirements inside FastAPI.

**Fix**: This is already handled in the codebase. Playwright runs in an isolated subprocess (`subprocess.run()`). If you see this error, ensure you are using the scraper through the API endpoints rather than calling Playwright directly.
