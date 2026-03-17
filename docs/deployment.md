# Deployment Guide

This guide covers deploying the API Knowledge Base RAG v2 system for production use.

---

## Prerequisites

- Python 3.10+
- Docker and Docker Compose
- A Google AI Studio API key ([aistudio.google.com](https://aistudio.google.com))
- Minimum 4 GB RAM (embedding model + reranker + ChromaDB)
- ~2 GB disk space for models (downloaded on first run)

---

## Local Development

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:
```
GEMINI_API_KEY=your_key_here
NEO4J_PASSWORD=a_secure_password
```

### 2. Start Neo4j

```bash
docker-compose up -d
```

Verify Neo4j is running:
- Browser UI: http://localhost:7474
- Login: neo4j / your_password

### 3. Install Python dependencies

```bash
python -m venv venv
source venv/bin/activate        # Linux/macOS
# or
.\venv\Scripts\activate         # Windows PowerShell

pip install -r requirements.txt
playwright install chromium
```

### 4. Start the server

```bash
uvicorn main:app --reload --port 8000
```

### 5. Initial data load

Trigger the ingestion pipeline to populate the knowledge base:

```powershell
# PowerShell (Windows)
Invoke-RestMethod -Uri "http://localhost:8000/admin/scrape" -Method POST -ContentType "application/json" -Body '{}'
```

```bash
# bash (Linux/macOS)
curl -X POST http://localhost:8000/admin/scrape -H "Content-Type: application/json" -d '{}'
```

Monitor progress:
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/admin/scrape/status"
```

---

## Production Deployment

### Option A: Direct Server Deployment

1. **Set up a virtual environment** on the production server:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Configure environment** with production values in `.env`

3. **Start Neo4j** via Docker Compose:
   ```bash
   docker-compose up -d
   ```

4. **Run with a production ASGI server**:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
   ```

   **Note**: Use `--workers 1` because the application holds in-memory state (BM25 index, loaded models). Multiple workers would each load their own copies, consuming excessive memory.

5. **Set up a reverse proxy** (nginx example):
   ```nginx
   server {
       listen 80;
       server_name api-kb.internal.company.com;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_read_timeout 120s;  # LLM responses can take time
       }
   }
   ```

6. **Set up a process manager** (systemd example):
   ```ini
   [Unit]
   Description=API Knowledge Base RAG
   After=network.target docker.service

   [Service]
   Type=simple
   User=appuser
   WorkingDirectory=/opt/api-rag
   Environment="PATH=/opt/api-rag/venv/bin"
   EnvironmentFile=/opt/api-rag/.env
   ExecStart=/opt/api-rag/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

### Option B: Full Docker Deployment

To containerize the entire application, create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System dependencies for Playwright and ML models
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium && playwright install-deps chromium

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

Add the app service to `docker-compose.yml`:

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      neo4j:
        condition: service_healthy
    volumes:
      - ./chroma_db:/app/chroma_db
    restart: unless-stopped

  neo4j:
    # ...existing neo4j config...
```

---

## Resource Requirements

| Component | Memory | Disk | Notes |
| --- | --- | --- | --- |
| bge-large-en-v1.5 | ~1.3 GB | ~1.3 GB | Downloaded on first run |
| ms-marco reranker | ~80 MB | ~80 MB | Lazy loaded on first query |
| ChromaDB | ~200 MB | Varies | Grows with number of entries |
| Neo4j | ~512 MB | ~100 MB | Docker container |
| FastAPI app | ~100 MB | Minimal | Python process |
| **Total** | **~2.2 GB** | **~1.8 GB** | Minimum recommended: 4 GB RAM |

---

## Health Monitoring

### Health endpoint

```
GET /health
```

Returns `200 OK` with connection status for ChromaDB and Neo4j. Use this for load balancer health checks.

### Scrape status

```
GET /admin/scrape/status
```

Monitor the ingestion pipeline and verify data freshness.

### Key metrics to watch

- `vector_store_count` from `/health` -- total entries in ChromaDB (should be stable between ingestion runs)
- `is_running` from `/admin/scrape/status` -- check for stuck ingestion jobs
- `last_status` from `/admin/scrape/status` -- detect failed ingestion runs
- Application logs -- Gemini API errors, Neo4j connection failures

---

## Backup and Recovery

### ChromaDB

The ChromaDB data is stored in the `./chroma_db/` directory. Back it up by copying the directory:

```bash
cp -r chroma_db/ chroma_db_backup_$(date +%Y%m%d)/
```

To restore, replace the `chroma_db/` directory and restart the server.

### Neo4j

Export graph data:
```bash
docker exec api_rag_neo4j neo4j-admin database dump neo4j --to-path=/data/backups/
docker cp api_rag_neo4j:/data/backups/ ./neo4j_backup/
```

The Docker named volume (`neo4j_data`) also persists data across container restarts.

### Full recovery

If both databases are lost, re-run the ingestion pipeline to rebuild from source:
```bash
curl -X POST http://localhost:8000/admin/scrape -H "Content-Type: application/json" -d '{}'
```

This repopulates everything from OpenAPI specs and curated JSON files.

---

## Security Considerations

- The `.env` file contains API keys -- never commit it to version control
- The application has no built-in authentication. Deploy behind a VPN or reverse proxy with auth for production use
- Neo4j credentials should use a strong password in production
- The Playwright scraper executes in a subprocess with limited scope; it only scrapes URLs explicitly provided by users
- See [SECURITY.md](../SECURITY.md) for the security policy
