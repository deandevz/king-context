---
name: process-docs
description: Use when processing documentation files (md, txt, json) into MCP docs server format. Triggers on "processe documentacao", "adicione doc ao MCP", "gere JSON para input/", "/process-docs". Handles manual doc processing from local files, URLs, or pasted text.
---

# Process Documentation

Process local documentation sources into JSON for MCP docs server.

## Quick Reference

| Input Type | Example |
|------------|---------|
| Folder | `input/<api>/` |
| Single file | `input/openrouter/api.md` |
| URL | `https://docs.example.com/api` |
| Pasted text | Direct paste in chat |

**Output:** `data/<api>.json` or MCP `add_doc` tool

## JSON Schema

```json
{
  "name": "api-name",
  "display_name": "Display Name",
  "version": "v1",
  "base_url": "https://docs.example.com",
  "sections": [{
    "title": "Section Title",
    "path": "section-slug",
    "url": "https://docs.example.com/section",
    "keywords": ["6-10 terms"],
    "use_cases": ["how to X", "when to Y"],
    "tags": ["getting-started", "api-reference"],
    "priority": 10,
    "content": "# Markdown content..."
  }]
}
```

**Priority scale:** 10=essential (auth, quickstart), 8-9=core features, 5-7=secondary, 1-4=edge cases

---

## Workflow

1. **Identify source:** `input/<api>/` folder, specific file, URL, or pasted text
2. **Extract sections:** Split by headers/separators, keep code blocks intact, target 500-2000 chars/section
3. **Generate metadata:** keywords (6-10), use_cases (3-5), tags (2-4), priority (1-10)
4. **Confirm destination:** JSON file or MCP `add_doc` tool
5. **Save:** Write to `data/<api>.json` or call MCP

---

## Directory Structure

```
mcp-docs/
  input/
    <api>/              # Source files
  data/
    <api>.json          # Final processed JSON
```

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Missing metadata generation | Every section needs keywords, use_cases, tags, priority |
| Sections too large | Target 500-2000 chars per section |
| Generic keywords | Use specific terms users would actually search |
| Skipping use_cases | Add practical questions ("how to...", "when to...") |

---

## Validation Checklist

Before saving final JSON:

- [ ] All required fields present (name, display_name, version, base_url, sections)
- [ ] Each section has: title, path, url, keywords (6-10), use_cases (3-5), tags (2-4), priority (1-10), content
- [ ] Keywords are searchable terms users would query
- [ ] Use cases are practical questions ("how to...", "when to...")
- [ ] Priority reflects actual importance
