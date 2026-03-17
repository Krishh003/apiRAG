# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it privately to the development team. Do not open a public issue.

**Contact**: Reach out to the project maintainers directly via internal communication channels.

**Response time**: We aim to acknowledge reports within 48 hours and provide a resolution timeline within 5 business days.

---

## Security Considerations

### API Keys

- The `.env` file contains sensitive API keys (Gemini, Neo4j). It must never be committed to version control
- `.env` is listed in `.gitignore` by default
- Use `.env.example` as a template with placeholder values only

### Authentication

- This application has **no built-in authentication or authorization**
- It is designed for internal use behind a corporate VPN or reverse proxy with authentication
- Do not expose the application directly to the public internet without adding an authentication layer

### Data Handling

- The knowledge base contains API documentation, not user data or PII
- Internal API wrapper entries (`is_internal: true`) may contain environment-specific details (staging URLs, credential locations). Treat these as sensitive
- ChromaDB stores vector embeddings locally on disk. Protect the `chroma_db/` directory accordingly

### External Connections

The application makes outbound connections to:

| Service | Purpose | Data Sent |
| --- | --- | --- |
| Google Generative AI API | LLM inference (Gemini) | User questions + retrieved API context |
| GitHub (raw.githubusercontent.com) | Fetching OpenAPI specs | HTTP GET requests only |
| Documentation URLs (via Playwright) | Single-URL scraping | HTTP GET requests to user-specified URLs |

### Neo4j

- Neo4j runs in a Docker container with password authentication
- Default ports (7474, 7687) should be firewalled in production to prevent external access
- Use a strong, unique password for the Neo4j instance

### Dependencies

- Review `requirements.txt` for known vulnerabilities periodically
- Pin dependency versions to avoid supply-chain risks
- The Playwright browser (Chromium) runs in a subprocess with limited scope

---

## Supported Versions

| Version | Supported |
| --- | --- |
| 2.x (current) | Yes |
| 1.x | No |
