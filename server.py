"""
King Context - Local-first, token-efficient documentation server.
"""

import json
from pathlib import Path
from fastmcp import FastMCP
from typing import Optional, Dict, Any

import numpy as np
from sentence_transformers import SentenceTransformer

import db
from db import init_db, search_cascade, list_documentations, insert_documentation

# Paths for embedding files
EMBEDDINGS_PATH = Path(__file__).parent / "data" / "embeddings.npy"
SECTION_MAPPING_PATH = Path(__file__).parent / "data" / "_internal" / "section_mapping.json"


def _load_embeddings() -> None:
    """Load embedding model and files into db module state.

    Loads SentenceTransformer model and embedding data files.
    Has try/except for graceful fallback if files are missing or corrupt.
    """
    # Load the SentenceTransformer model
    db._embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

    # Try to load embeddings.npy
    try:
        if EMBEDDINGS_PATH.exists():
            db._embeddings = np.load(EMBEDDINGS_PATH)
    except Exception:
        # Graceful fallback - embeddings remain None
        pass

    # Try to load section_mapping.json
    try:
        if SECTION_MAPPING_PATH.exists():
            with open(SECTION_MAPPING_PATH) as f:
                raw_mapping = json.load(f)
                # Convert string keys to int keys
                db._section_id_to_idx = {int(k): v for k, v in raw_mapping.items()}
    except Exception:
        # Graceful fallback - mapping remains empty
        pass


mcp = FastMCP("king-context")


@mcp.tool()
def search_docs(
    query: str,
    doc_name: Optional[str] = None,
    max_results: int = 5
) -> Dict[str, Any]:
    """
    Busca documentação com transparência total.

    Args:
        query: Termo ou pergunta de busca
        doc_name: Nome da documentação específica (ex: "openrouter")
        max_results: Número máximo de resultados

    Returns:
        Resultados com chunks e metadata de transparência
    """
    return search_cascade(query=query, doc_name=doc_name, max_results=max_results)


@mcp.tool()
def list_docs() -> Dict[str, Any]:
    """
    Lista todas as documentações disponíveis no banco.

    Returns:
        Lista de docs com nome, versão e count de sections
    """
    docs = list_documentations()
    return {
        "docs": docs,
        "count": len(docs)
    }


@mcp.tool()
def show_context(
    query: str,
    doc_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Mostra exatamente o que seria injetado no contexto.

    Args:
        query: Query usada
        doc_name: Documentação consultada

    Returns:
        Contexto completo com metadados e estimativa de tokens
    """
    # Call search_cascade internally
    result = search_cascade(query=query, doc_name=doc_name, max_results=5)

    chunks = result.get("chunks", [])

    # Format context_preview as markdown with section titles
    if chunks:
        context_parts = []
        for chunk in chunks:
            title = chunk.get("title", "Untitled")
            content = chunk.get("content", "")
            context_parts.append(f"## {title}\n\n{content}")
        context_preview = "\n\n".join(context_parts)
    else:
        context_preview = ""

    # Token estimate: rough estimate as len(content) / 4
    token_estimate = len(context_preview) // 4

    return {
        "query": query,
        "doc_name": doc_name,
        "context_preview": context_preview,
        "token_estimate": token_estimate,
        "chunks_count": len(chunks),
        "transparency": result.get("transparency", {})
    }


@mcp.tool()
def add_doc(doc_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Insere documentação diretamente via MCP.

    Args:
        doc_json: Objeto JSON completo no schema esperado

    Returns:
        Estatísticas da inserção (sections_indexed, etc)
    """
    # Validate required doc-level fields
    required_doc_fields = ["name", "display_name", "version", "base_url", "sections"]
    for field in required_doc_fields:
        if field not in doc_json:
            return {
                "success": False,
                "doc_id": None,
                "sections_indexed": 0,
                "message": f"Missing required field: {field}"
            }

    # Validate required section fields
    required_section_fields = [
        "title", "path", "url", "keywords", "use_cases", "tags", "priority", "content"
    ]
    for i, section in enumerate(doc_json["sections"]):
        for field in required_section_fields:
            if field not in section:
                return {
                    "success": False,
                    "doc_id": None,
                    "sections_indexed": 0,
                    "message": f"Missing required section field: {field} in section {i}"
                }

    # Call insert_documentation from db module
    try:
        doc_id = insert_documentation(doc_json)
        sections_count = len(doc_json["sections"])
        return {
            "success": True,
            "doc_id": doc_id,
            "sections_indexed": sections_count,
            "message": f"Successfully indexed {sections_count} sections for '{doc_json['name']}'"
        }
    except Exception as e:
        return {
            "success": False,
            "doc_id": None,
            "sections_indexed": 0,
            "message": str(e)
        }


if __name__ == "__main__":
    init_db()
    _load_embeddings()
    mcp.run()
