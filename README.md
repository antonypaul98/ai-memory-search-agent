# AI Memory Search Agent

Semantic search over saved YouTube videos using video transcripts.

**MVP goal:** Save YouTube URLs → extract transcripts → embed with Sentence Transformers → store in ChromaDB → search by meaning, not just keywords.

**Example:** Search `"healthy food"` → results about protein meals, meal prep, nutrition, fiber-rich foods.

---

## Tech Stack

| Layer      | Tool                                       |
|------------|--------------------------------------------|
| Backend    | FastAPI                                    |
| Vector DB  | ChromaDB (Persistent Client)               |
| Embeddings | Sentence Transformers (all-MiniLM-L6-v2)   |
| Frontend   | Streamlit (Phase 5+)                       |
| Language   | Python 3.11+                               |

---

## Project Status

| Phase | Description                         | Status      |
|-------|-------------------------------------|-------------|
| 1     | Folder structure & scaffold         | Complete    |
| 2     | Config, Chroma, health, URL parser, transcript fetch | Complete |
| 3     | Chunking, embeddings, ingest        | Pending     |
| 4     | Semantic search                     | Pending     |
| 5     | Streamlit UI                        | Pending     |

---

## Architecture

```
Streamlit  →  FastAPI (routes)  →  Services  →  Repositories  →  ChromaDB
```

Every stored chunk includes `source_type` and full `MemoryMetadata` (see `app/models/memory.py`).

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Run the API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/api/v1/health

### Run tests

```bash
pytest -v
```

---

## Phase 2 Endpoints

| Method | Endpoint           | Description              |
|--------|--------------------|--------------------------|
| GET    | `/api/v1/health`   | API + ChromaDB health    |

Transcript fetching is available via `TranscriptService` (no HTTP route yet — Phase 3).

---

## License

See [LICENSE](LICENSE).
