# Feature: Hybrid Semantic Search

**Date:** 2026-01-16
**Status:** Design approved

## Context

The current King Context server has a cascade search system (cache → metadata → FTS5) that fails with natural language queries.

**Observed problem:**
- Query "OpenRouter API curl requests implementation" → `found: false`
- Query "chat completions" → found

**Root cause:** FTS5 treats the query as an exact phrase and metadata search uses LIKE with the full string, which doesn't match individual keywords.

**Impact:** The agent needs multiple attempts with different queries to find documentation, wasting tokens and time.

## Decisions

### Embedding Model
`sentence-transformers/all-MiniLM-L6-v2` - runs locally, no API keys, ~90MB, ~10ms per embedding.

### Storage
Numpy file (`embeddings.npy`) - loads into memory, <5MB for ~500 sections, search in <1ms.

### Search Strategy
Hybrid with reranking:
1. FTS5 retrieves ~20 candidates (high recall)
2. Embeddings reorder by similarity (high precision)
3. Threshold 0.5 filters irrelevant results
4. Returns top N

### Embedding Generation
At seed time - `seed_data.py` generates embeddings during indexing, server loads on startup.

## Section 1: Seed Modifications

Update `seed_data.py` to generate embeddings during indexing.

**Analysis hints:** sentence-transformers, numpy save, embedding generation, seed_data.py

## Section 2: Embedding Storage

Create structure to save and load embeddings with section_id → embedding_index mapping.

**Analysis hints:** numpy array, embeddings.npy, section mapping, load on startup

## Section 3: Hybrid Search

Modify `search_cascade` in `db.py` to use reranking with embeddings.

**Analysis hints:** cosine similarity, FTS5 candidates, rerank, similarity threshold, db.py

## Section 4: Server Integration

Load model and embeddings on server startup, keep in memory.

**Analysis hints:** server.py, model loading, startup, FastMCP

## Success Criteria

**Functional:**
- Query "how to do OAuth on OpenRouter" finds OAuth PKCE section
- Query "curl API request" finds quickstart section
- Irrelevant queries return `found: false`, not garbage

**Performance:**
- Seed with 100 sections in <30 seconds
- Search in <100ms
- Server startup in <2 seconds

**Transparency:**
- Response includes `similarity_score` (0.0-1.0) for each chunk
- Response indicates method: "hybrid_rerank"
- Configurable threshold

**Compatibility:**
- MCP tools API remains unchanged
- Fallback to pure FTS5 if embeddings fail
- Works offline
