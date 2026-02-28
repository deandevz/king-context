from king_context.scraper.chunk import Chunk, chunk_page, chunk_pages, _estimate_tokens
from king_context.scraper.config import ScraperConfig


def make_config(**kwargs) -> ScraperConfig:
    return ScraperConfig(
        chunk_max_tokens=kwargs.get("chunk_max_tokens", 1000),
        chunk_min_tokens=kwargs.get("chunk_min_tokens", 100),
    )


def test_chunk_splits_by_headers():
    markdown = """\
## Authentication

This section covers authentication.

### API Keys

Use API keys to authenticate.

### OAuth

Use OAuth for user-level access.
"""
    config = make_config(chunk_min_tokens=2)
    chunks = chunk_page(markdown, "https://docs.example.com/api", config)

    assert len(chunks) == 3
    assert chunks[0].title == "Authentication"
    assert chunks[1].title == "API Keys"
    assert chunks[2].title == "OAuth"


def test_chunk_respects_code_blocks():
    markdown = """\
## Setup

Install the package.

```python
## Not a header
import something
### Also not a header
```

More setup text here.
"""
    config = make_config()
    chunks = chunk_page(markdown, "https://docs.example.com/setup", config)

    # Only the real ## Setup header should create a split
    assert len(chunks) == 1
    assert chunks[0].title == "Setup"
    # The code block header should be in the content
    assert "## Not a header" in chunks[0].content


def test_chunk_respects_tables():
    # Generate enough content to trigger subdivision
    long_intro = " ".join(["word"] * 300)
    long_outro = " ".join(["word"] * 300)
    table = """\
| Column A | Column B |
|----------|----------|
| row 1a   | row 1b   |
| row 2a   | row 2b   |
| row 3a   | row 3b   |"""

    markdown = f"""\
## Data Reference

{long_intro}

{table}

{long_outro}
"""
    # Set max_tokens low enough to force subdivision
    config = make_config(chunk_max_tokens=200, chunk_min_tokens=10)
    chunks = chunk_page(markdown, "https://docs.example.com/ref", config)

    # The table should never be split across chunks
    for chunk in chunks:
        lines = chunk.content.split("\n")
        table_lines = [l for l in lines if l.strip().startswith("|")]
        if table_lines:
            # All table lines should be contiguous — no partial table in this chunk
            assert len(table_lines) == 5 or len(table_lines) == 0


def test_chunk_merges_small():
    markdown = """\
## Overview

This section has a long enough introduction to not be merged.
It contains many words to make the token count high enough.
We need enough text here to exceed the minimum token threshold.
Adding more text to ensure this section stands on its own.

## Tiny

Hi.
"""
    config = make_config(chunk_min_tokens=50)
    chunks = chunk_page(markdown, "https://docs.example.com/page", config)

    # The tiny chunk (< min_tokens) should be merged into the previous chunk
    assert len(chunks) == 1
    assert "Hi." in chunks[0].content
    assert "Overview" in chunks[0].title


def test_chunk_splits_large():
    para1 = " ".join(["alpha"] * 300)
    para2 = " ".join(["beta"] * 300)
    para3 = " ".join(["gamma"] * 300)

    markdown = f"""\
## Big Section

{para1}

{para2}

{para3}
"""
    config = make_config(chunk_max_tokens=400, chunk_min_tokens=10)
    chunks = chunk_page(markdown, "https://docs.example.com/big", config)

    # Should be split into multiple sub-chunks
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= config.chunk_max_tokens or len(chunk.content.split("\n\n")) == 1


def test_chunk_breadcrumb():
    markdown = """\
## Parent Section

Parent content here.

### Child One

Child one content.

### Child Two

Child two content.
"""
    config = make_config(chunk_min_tokens=2)
    chunks = chunk_page(markdown, "https://docs.example.com/page", config)

    assert chunks[0].breadcrumb == "Parent Section"
    assert chunks[1].breadcrumb == "Parent Section > Child One"
    assert chunks[2].breadcrumb == "Parent Section > Child Two"


def test_chunk_token_count():
    words = ["token"] * 100
    content = " ".join(words)
    markdown = f"## Section\n\n{content}"

    config = make_config()
    chunks = chunk_page(markdown, "https://docs.example.com/page", config)

    assert len(chunks) == 1
    expected = int(100 * 1.33)
    assert chunks[0].token_count == expected
