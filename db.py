"""
Database module for King Context.
Handles SQLite + FTS5 schema and cascade search.
"""

import sqlite3
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

import numpy as np
from sentence_transformers import SentenceTransformer

# Module-level state for embedding model and embeddings
_embedding_model: Optional[SentenceTransformer] = None
_embeddings: Optional[np.ndarray] = None
_section_id_to_idx: Dict[int, int] = {}

DB_PATH = Path(__file__).parent / "docs.db"
EMBEDDINGS_PATH = Path(__file__).parent / "data" / "embeddings.npy"
SECTION_MAPPING_PATH = Path(__file__).parent / "data" / "_internal" / "section_mapping.json"


def init_db() -> None:
    """Initialize the database with complete schema.

    Creates tables:
    - documentations: stores documentation metadata
    - sections: stores document sections with JSON fields for keywords, use_cases, tags
    - sections_fts: FTS5 virtual table for full-text search on title and content
    - query_cache: caches search results for faster retrieval
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")

    # Create documentations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documentations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            version TEXT,
            base_url TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create sections table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            path TEXT NOT NULL,
            url TEXT NOT NULL,
            keywords JSON,
            use_cases JSON,
            tags JSON,
            priority INTEGER DEFAULT 0,
            content TEXT,
            FOREIGN KEY (doc_id) REFERENCES documentations(id) ON DELETE CASCADE
        )
    """)

    # Create sections_fts FTS5 virtual table for full-text search
    # content='' makes it an external content table linked to sections
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
            title,
            content,
            content='sections',
            content_rowid='id'
        )
    """)

    # Create query_cache table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS query_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_normalized TEXT NOT NULL,
            doc_name TEXT,
            section_id INTEGER NOT NULL,
            hit_count INTEGER DEFAULT 1,
            last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (section_id) REFERENCES sections(id) ON DELETE CASCADE,
            UNIQUE(query_normalized, doc_name)
        )
    """)

    conn.commit()
    conn.close()


def search_cascade(
    query: str,
    doc_name: Optional[str] = None,
    max_results: int = 5
) -> Dict[str, Any]:
    """Perform cascade search: cache -> metadata -> FTS5.

    Returns on first hit. Includes search_path and latency_ms for transparency.

    Args:
        query: The search query string
        doc_name: Optional documentation name filter
        max_results: Maximum number of results to return

    Returns:
        Dict with keys:
        - found: bool indicating if results were found
        - chunks: list of matching chunks
        - transparency: dict with method, latency_ms, search_path, from_cache
    """
    start_time = time.perf_counter()
    search_path: List[str] = []
    chunks: List[Dict] = []
    method: str = ""
    from_cache: bool = False

    # Normalize the query for consistent matching
    query_norm = _normalize_query(query)

    conn = _get_connection()
    try:
        # Step 1: Check cache
        cache_result = _check_cache(conn, query_norm, doc_name)
        if cache_result:
            search_path.append("cache_hit")
            chunks = cache_result
            method = "cache"
            from_cache = True
        else:
            search_path.append("cache_miss")

            # Step 2: Search metadata (keywords, use_cases, tags)
            metadata_result = _search_metadata(conn, query_norm, doc_name, max_results)
            if metadata_result:
                search_path.append("metadata_hit")
                chunks = metadata_result
                method = "metadata"
                # Update cache with first result
                _update_cache(conn, query_norm, doc_name, metadata_result[0]["section_id"])
            else:
                search_path.append("metadata_miss")

                # Step 3: Full-text search via FTS5 with hybrid reranking
                # Request ~20 candidates for reranking, not max_results
                fts_candidates = 20
                fts_result = _search_fts(conn, query_norm, doc_name, fts_candidates)
                if fts_result:
                    search_path.append("fts_hit")

                    # Try hybrid reranking with embeddings
                    reranked = _rerank_with_embeddings(query_norm, fts_result, max_results)

                    if reranked and len(reranked) > 0:
                        # Hybrid reranking succeeded
                        chunks = reranked
                        method = "hybrid_rerank"
                        _update_cache(conn, query_norm, doc_name, reranked[0]["section_id"])
                    else:
                        # Fallback to FTS-only (embeddings unavailable or all filtered)
                        chunks = fts_result[:max_results]
                        method = "fts"
                        _update_cache(conn, query_norm, doc_name, fts_result[0]["section_id"])
                else:
                    search_path.append("fts_miss")

    finally:
        conn.close()

    # Calculate latency
    end_time = time.perf_counter()
    latency_ms = (end_time - start_time) * 1000

    return {
        "found": len(chunks) > 0,
        "chunks": chunks,
        "transparency": {
            "method": method,
            "latency_ms": latency_ms,
            "search_path": search_path,
            "from_cache": from_cache
        }
    }


def _check_cache(
    conn: sqlite3.Connection,
    query_norm: str,
    doc_name: Optional[str]
) -> Optional[List[Dict]]:
    """Check cache for matching query and return section details if found.

    Searches query_cache table for matching query_normalized and doc_name.
    If found, increments hit_count and updates last_used timestamp.
    Joins with sections table to get full section details.

    Args:
        conn: SQLite connection (provided by caller)
        query_norm: Normalized query string
        doc_name: Documentation name filter (can be None to match entries with NULL doc_name)

    Returns:
        List of section dicts if found, None if not found.
        Section dict format: {"section_id": int, "title": str, "content": str,
                              "keywords": list, "source_url": str}
    """
    cursor = conn.cursor()

    # Build query based on whether doc_name is None or not
    if doc_name is None:
        # Match cache entries where doc_name is NULL
        select_query = """
            SELECT qc.id, s.id, s.title, s.content, s.keywords, s.url
            FROM query_cache qc
            JOIN sections s ON qc.section_id = s.id
            WHERE qc.query_normalized = ?
              AND qc.doc_name IS NULL
        """
        cursor.execute(select_query, (query_norm,))
    else:
        # Match cache entries with specific doc_name
        select_query = """
            SELECT qc.id, s.id, s.title, s.content, s.keywords, s.url
            FROM query_cache qc
            JOIN sections s ON qc.section_id = s.id
            WHERE qc.query_normalized = ?
              AND qc.doc_name = ?
        """
        cursor.execute(select_query, (query_norm, doc_name))

    rows = cursor.fetchall()

    if not rows:
        return None

    # Update hit_count and last_used for found cache entries
    cache_ids = [row[0] for row in rows]
    now = datetime.now().isoformat()

    for cache_id in cache_ids:
        cursor.execute(
            """
            UPDATE query_cache
            SET hit_count = hit_count + 1, last_used = ?
            WHERE id = ?
            """,
            (now, cache_id)
        )

    # Build result list
    results = []
    for row in rows:
        # Parse keywords JSON
        keywords_json = row[4]
        if keywords_json:
            keywords = json.loads(keywords_json)
        else:
            keywords = []

        results.append({
            "section_id": row[1],
            "title": row[2],
            "content": row[3] or "",
            "keywords": keywords,
            "source_url": row[5]
        })

    return results


def _search_metadata(
    conn: sqlite3.Connection,
    query_norm: str,
    doc_name: Optional[str],
    max_results: int
) -> List[Dict]:
    """Search in keywords, use_cases, tags JSON fields using LIKE.

    Args:
        conn: SQLite connection
        query_norm: Normalized query string
        doc_name: Optional documentation name filter (join with documentations table)
        max_results: Maximum number of results to return

    Returns:
        List of section dicts with keys: section_id, title, content, keywords, source_url
        Ordered by priority DESC
    """
    cursor = conn.cursor()

    # Build the LIKE pattern
    like_pattern = f"%{query_norm}%"

    # Build query with optional doc_name filter
    if doc_name:
        query = """
            SELECT s.id, s.title, s.content, s.keywords, s.url
            FROM sections s
            JOIN documentations d ON s.doc_id = d.id
            WHERE d.name = ?
              AND (s.keywords LIKE ? OR s.use_cases LIKE ? OR s.tags LIKE ?)
            ORDER BY s.priority DESC
            LIMIT ?
        """
        cursor.execute(query, (doc_name, like_pattern, like_pattern, like_pattern, max_results))
    else:
        query = """
            SELECT s.id, s.title, s.content, s.keywords, s.url
            FROM sections s
            WHERE s.keywords LIKE ? OR s.use_cases LIKE ? OR s.tags LIKE ?
            ORDER BY s.priority DESC
            LIMIT ?
        """
        cursor.execute(query, (like_pattern, like_pattern, like_pattern, max_results))

    rows = cursor.fetchall()

    results = []
    for row in rows:
        # Parse keywords JSON
        keywords_json = row[3]
        keywords = json.loads(keywords_json) if keywords_json else []

        results.append({
            "section_id": row[0],
            "title": row[1],
            "content": row[2] or "",
            "keywords": keywords,
            "source_url": row[4]
        })

    return results


def _search_fts(
    conn: sqlite3.Connection,
    query_norm: str,
    doc_name: Optional[str],
    max_results: int
) -> List[Dict]:
    """Search using FTS5 full-text search with BM25 ranking.

    Args:
        conn: SQLite connection
        query_norm: Normalized query string
        doc_name: Optional documentation name filter (join with documentations table)
        max_results: Maximum number of results to return

    Returns:
        List of section dicts with keys: section_id, title, content, keywords, source_url, rank
        Ordered by BM25 rank (best matches first)
    """
    cursor = conn.cursor()

    # Escape query for FTS5 to handle special characters like ? * " etc.
    fts_query = _escape_fts5_query(query_norm)

    # Build query with optional doc_name filter
    if doc_name:
        query = """
            SELECT s.id, s.title, s.content, s.keywords, s.url, bm25(sections_fts) as rank
            FROM sections_fts fts
            JOIN sections s ON fts.rowid = s.id
            JOIN documentations d ON s.doc_id = d.id
            WHERE sections_fts MATCH ?
              AND d.name = ?
            ORDER BY rank
            LIMIT ?
        """
        cursor.execute(query, (fts_query, doc_name, max_results))
    else:
        query = """
            SELECT s.id, s.title, s.content, s.keywords, s.url, bm25(sections_fts) as rank
            FROM sections_fts fts
            JOIN sections s ON fts.rowid = s.id
            WHERE sections_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        cursor.execute(query, (fts_query, max_results))

    rows = cursor.fetchall()

    results = []
    for row in rows:
        # Parse keywords JSON
        keywords_json = row[3]
        keywords = json.loads(keywords_json) if keywords_json else []

        results.append({
            "section_id": row[0],
            "title": row[1],
            "content": row[2] or "",
            "keywords": keywords,
            "source_url": row[4],
            "rank": float(row[5])
        })

    return results


def _update_cache(
    conn: sqlite3.Connection,
    query_norm: str,
    doc_name: Optional[str],
    section_id: int
) -> None:
    """Insert or replace a cache entry for a query result.

    Uses INSERT OR REPLACE to handle duplicates based on the
    UNIQUE(query_normalized, doc_name) constraint.

    Args:
        conn: SQLite connection (caller manages transaction/commit)
        query_norm: Normalized query string
        doc_name: Documentation name filter (can be None)
        section_id: ID of the section to cache
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO query_cache
            (query_normalized, doc_name, section_id, hit_count, last_used)
        VALUES (?, ?, ?, 1, ?)
        """,
        (query_norm, doc_name, section_id, datetime.now().isoformat())
    )


def insert_documentation(doc_data: Dict[str, Any]) -> int:
    """Insert documentation with its sections into the database.

    Inserts a documentation record into the documentations table,
    then inserts each section into the sections table with JSON-encoded
    keywords, use_cases, and tags. Updates the FTS5 index for full-text search.

    Args:
        doc_data: Dict containing documentation data with keys:
            - name: Unique documentation name
            - display_name: Human-readable display name
            - version: Version string (optional, can be None)
            - base_url: Base URL for the documentation
            - sections: List of section dicts with keys:
                - title, path, url, keywords, use_cases, tags, priority, content

    Returns:
        The doc_id of the inserted documentation.
    """
    conn = _get_connection()
    cursor = conn.cursor()

    try:
        # Get current timestamp in ISO format
        now = datetime.now().isoformat()

        # Insert documentation record
        cursor.execute("""
            INSERT INTO documentations (name, display_name, version, base_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            doc_data["name"],
            doc_data["display_name"],
            doc_data.get("version"),
            doc_data["base_url"],
            now,
            now
        ))
        doc_id = cursor.lastrowid

        # Insert sections
        sections = doc_data.get("sections", [])
        for section in sections:
            cursor.execute("""
                INSERT INTO sections (doc_id, title, path, url, keywords, use_cases, tags, priority, content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                doc_id,
                section["title"],
                section["path"],
                section["url"],
                json.dumps(section.get("keywords", [])),
                json.dumps(section.get("use_cases", [])),
                json.dumps(section.get("tags", [])),
                section.get("priority", 0),
                section.get("content", "")
            ))
            section_id = cursor.lastrowid

            # Insert into FTS5 index directly
            cursor.execute("""
                INSERT INTO sections_fts (rowid, title, content)
                VALUES (?, ?, ?)
            """, (
                section_id,
                section["title"],
                section.get("content", "")
            ))

            # Generate and save embedding for section
            _generate_and_save_embedding(section_id, section.get("content", ""))

        conn.commit()
        return doc_id

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_documentations() -> List[Dict[str, Any]]:
    """List all documentations with their section counts.

    Queries the documentations table and joins with sections to count
    the number of sections for each documentation.

    Returns:
        List of dicts with keys: name, display_name, version, section_count.
        Returns empty list if no documentations exist.
    """
    conn = _get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT d.name, d.display_name, d.version, COUNT(s.id) as section_count
            FROM documentations d
            LEFT JOIN sections s ON d.id = s.doc_id
            GROUP BY d.id, d.name, d.display_name, d.version
        """)

        rows = cursor.fetchall()

        results = []
        for row in rows:
            results.append({
                "name": row[0],
                "display_name": row[1],
                "version": row[2],
                "section_count": row[3]
            })

        return results

    finally:
        conn.close()


def _generate_and_save_embedding(section_id: int, content: str) -> None:
    """Generate embedding for section content and save to disk.

    Creates embedding using _embedding_model.encode(), appends to _embeddings array,
    updates _section_id_to_idx mapping, and persists to disk.

    Args:
        section_id: The database ID of the section
        content: The text content to generate embedding for

    Note:
        Does nothing if _embedding_model is None (graceful skip).
        Creates data directory if it doesn't exist.
    """
    global _embeddings, _section_id_to_idx

    # Skip if no embedding model is available
    if _embedding_model is None:
        return

    # Generate embedding
    embedding = _embedding_model.encode(content)

    # Update _embeddings array
    if _embeddings is None:
        # Create new array with this embedding
        _embeddings = np.array([embedding], dtype=np.float32)
    else:
        # Append to existing array
        _embeddings = np.vstack([_embeddings, embedding])

    # Update section_id_to_idx mapping
    idx = len(_section_id_to_idx)
    _section_id_to_idx[section_id] = idx

    # Ensure data directory exists
    EMBEDDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Save embeddings to disk
    np.save(EMBEDDINGS_PATH, _embeddings)

    # Save section mapping to disk
    # Convert int keys to strings for JSON serialization
    mapping_for_json = {str(k): v for k, v in _section_id_to_idx.items()}
    with open(SECTION_MAPPING_PATH, 'w') as f:
        json.dump(mapping_for_json, f)


def _rerank_with_embeddings(
    query_norm: str,
    fts_results: List[Dict],
    max_results: int
) -> Optional[List[Dict]]:
    """Rerank FTS results using cosine similarity with query embedding.

    Takes FTS5 candidate results and reranks them based on semantic similarity
    to the query using pre-computed embeddings.

    Args:
        query_norm: Normalized query string
        fts_results: List of FTS result dicts with section_id
        max_results: Maximum number of results to return

    Returns:
        List of reranked results with similarity_score added, or None if
        embeddings are unavailable (signals fallback to FTS-only).

    Note:
        - Returns None if _embedding_model or _embeddings is None
        - Filters results by similarity threshold of 0.5
        - Sorts by similarity descending
        - Skips sections not found in _section_id_to_idx
    """
    # Check if embeddings are available
    if _embedding_model is None or _embeddings is None:
        return None

    # Encode the query
    query_embedding = _embedding_model.encode(query_norm)

    # Normalize query embedding for cosine similarity
    query_norm_vec = query_embedding / np.linalg.norm(query_embedding)

    # Calculate similarity for each FTS result
    results_with_scores = []
    for chunk in fts_results:
        section_id = chunk["section_id"]

        # Skip if section not in mapping
        if section_id not in _section_id_to_idx:
            continue

        idx = _section_id_to_idx[section_id]
        section_embedding = _embeddings[idx]

        # Normalize section embedding
        section_norm_vec = section_embedding / np.linalg.norm(section_embedding)

        # Calculate cosine similarity (dot product of normalized vectors)
        similarity = float(np.dot(query_norm_vec, section_norm_vec))

        # Filter by threshold (0.3 allows moderately relevant results)
        if similarity >= 0.3:
            # Copy chunk and add similarity_score
            result = chunk.copy()
            result["similarity_score"] = similarity
            results_with_scores.append(result)

    # Sort by similarity descending
    results_with_scores.sort(key=lambda x: x["similarity_score"], reverse=True)

    # Return top max_results
    return results_with_scores[:max_results]


def _normalize_query(query: str) -> str:
    """Normaliza query para matching consistente."""
    return query.lower().strip()


def _escape_fts5_query(query: str) -> str:
    """Escape query string for FTS5 MATCH.

    FTS5 has special syntax characters that need escaping.
    Quotes each word individually to handle special characters
    while preserving multi-word search (implicit AND).

    Args:
        query: Raw query string

    Returns:
        FTS5-safe query string with each word quoted
    """
    # Split into words, quote each one to escape special characters
    words = query.split()
    if not words:
        return '""'
    # Quote each word and join with space (implicit AND in FTS5)
    quoted_words = [f'"{w.replace(chr(34), chr(34)+chr(34))}"' for w in words]
    return ' '.join(quoted_words)


def _get_connection() -> sqlite3.Connection:
    """Retorna conexão com o banco."""
    return sqlite3.connect(DB_PATH)
