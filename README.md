# Board Game Concierge

Telegram bot that helps a regular board game group get through setup faster: it can explain rules from imported rulebooks, answer follow-up questions, give strategy tips, and recommend games from the local catalog.
Telegram is the primary product surface, while the backend uses Pinecone for rulebook memory, the local masterlist CSVs for recommendation candidates, and a fallback search chain for live strategy lookups.

## Setup

### 1. Install dependencies

Create and activate a Python environment, then install the requirements:

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

Create a local `.env` file at the repo root. Do not commit secrets.

Required keys used by the backend:

- `OPENAI_API_KEY`
- `PINECONE_API_KEY`
- `SERP_API_KEY`
- `SERPER_API_KEY`
- `TAVILY_API_KEY`

Optional backend settings:

- `CHAT_MODEL` defaults to `gpt-4o-mini`
- `EMBEDDING_MODEL` defaults to `text-embedding-3-small`
- `PINECONE_INDEX_NAME` defaults to `board-game-concierge`
- `PINECONE_CLOUD` defaults to `aws`
- `PINECONE_REGION` defaults to `us-east-1`
- `RAG_MIN_SCORE` defaults to `0.3`

Telegram credentials are configured in n8n, not in this repo.

### 3. Build the vector index

Run the ingestion job once to chunk the pilot rulebooks and upsert them into Pinecone:

```bash
python -m app.ingestion.ingest
```

### 4. Start the backend

Run the FastAPI service:

```bash
uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload
```

The backend listens on port `8000`. n8n must point to a public URL if it runs in n8n Cloud.

### 5. Import the n8n workflow

Import `n8n/board-game-concierge.workflow.json` into n8n and ensure the Telegram nodes have a valid bot credential.

If you are using a tunnel for local development, update the HTTP Request node base URL to the current public tunnel URL before importing or saving the workflow.

## How to Run

1. Start the backend with `uvicorn`.
2. Make sure Pinecone contains the ingested rulebook vectors.
3. Import and activate the n8n workflow.
4. Send a Telegram command such as:
   - `/help Wingspan`
   - `/ask how does scoring work?`
   - `/tips`
   - `/recommend 6 adults, light, around 120 minutes`

## File Map

- `app/server.py` - FastAPI endpoints for `/report`, `/ask`, `/tips`, `/recommend`, `/games`, `/reset`, and `/greeting`.
- `app/synthesis.py` - LLM prompt/synthesis layer for reports, follow-ups, tips, and recommendations.
- `app/rag/vectorstore.py` - Pinecone retrieval for rulebook chunks.
- `app/ingestion/` - PDF chunking and Pinecone indexing pipeline.
- `app/clients/game_lookup.py` - local game name resolution against the masterlist CSV.
- `app/clients/game_catalog.py` - recommendation candidate filtering and ranking from the masterlist CSVs.
- `app/clients/tips_client.py` - external tip lookup with failover across SerpApi, Serper, and Tavily.
- `app/memory.py` - in-memory chat session and pending-intent state.
- `app/persona.py` - concierge voice and response rules.
- `app/phrasing.py` - canned fallback phrases.
- `rulebooks/` - source PDFs for the imported rulebooks.
- `masterlist/` - CSV catalogs and enrichment data.
- `n8n/board-game-concierge.workflow.json` - Telegram routing and HTTP orchestration.
- `n8n/board-game-concierge.diagram.md` - workflow diagram and route notes.

## Architecture Overview

The system is split into two layers:

1. **n8n handles Telegram orchestration**
   - Telegram Trigger receives messages.
   - Command routing decides which backend endpoint to call.
   - Send Typing Action runs in parallel so the chat shows activity while the backend works.
   - Send Reply delivers the final answer back to Telegram.

2. **FastAPI handles the actual concierge logic**
   - `/report` retrieves rulebook chunks from Pinecone and synthesizes a grounded digest.
   - `/ask` answers one follow-up question from the active session context.
   - `/tips` prefers the active session game, otherwise resolves an explicit title, then queries the tip providers.
   - `/recommend` filters the local board game catalog by player count, rating, playtime, and complexity using the masterlist CSVs as the source of truth.
   - `/games` and `/greeting` return lightweight informational responses.
   - The tips flow uses SerpApi, Serper.dev, and Tavily because the BGG XML API would have required admin approval and Reddit's community-thread access has changed.

### Tool / API List

- **Telegram Bot API** - command intake and reply delivery through n8n.
- **OpenAI API** - embeddings and chat synthesis.
- **Pinecone** - vector storage and retrieval for the rulebook chunks.
- **SerpApi** - first live search source for `/tips`, using Brave AI Mode.
- **Serper.dev** - second live search source if SerpApi fails.
- **Tavily** - fallback live search source if SerpApi and Serper both fail.

## Notes

- No secrets are committed to the repo.
- The repo uses a small pilot library, but the structure is ready for the full rulebook set.
- If the cloud tunnel URL changes, the n8n workflow needs to be updated to match the new public backend URL.
