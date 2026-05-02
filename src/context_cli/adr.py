"""ADR decision memory support for the kctx CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from context_cli import DECISIONS_STORE_DIR, PROJECT_ROOT


ADR_DIR = PROJECT_ROOT / ".king-context" / "adr"
PROJECT_DECISIONS_DIR = DECISIONS_STORE_DIR / "project"

VALID_STATUSES = {"proposed", "accepted", "deprecated", "superseded", "rejected"}
REQUIRED_FRONTMATTER = [
    "id",
    "title",
    "status",
    "date",
    "areas",
    "supersedes",
    "superseded_by",
    "related",
    "keywords",
    "tags",
]
LIST_FIELDS = {"areas", "supersedes", "superseded_by", "related", "keywords", "tags"}
REQUIRED_SECTIONS = [
    "## Context",
    "## Decision",
    "## Alternatives Considered",
    "## Consequences",
    "## Links",
]


class AdrError(RuntimeError):
    """Raised for invalid ADR input or graph state."""


@dataclass
class Decision:
    id: str
    title: str
    status: str
    date: str
    areas: list[str]
    supersedes: list[str]
    superseded_by: list[str]
    related: list[str]
    keywords: list[str]
    tags: list[str]
    supersession_reason: str
    path: str
    source_path: str
    source_mtime: float
    source_hash: str
    active: bool
    priority: int
    content: str
    token_estimate: int
    use_cases: list[str]


@dataclass
class AdrSearchResult:
    id: str
    title: str
    status: str
    active: bool
    path: str
    score: float
    date: str
    areas: list[str]
    supersedes: list[str]
    superseded_by: list[str]
    related: list[str]


def _project_root() -> Path:
    import context_cli.cli as cli_mod

    return getattr(cli_mod, "PROJECT_ROOT", PROJECT_ROOT)


def _adr_dir() -> Path:
    return _project_root() / ".king-context" / "adr"


def _decisions_dir() -> Path:
    return _project_root() / ".king-context" / "decisions" / "project"


def _estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 1.33)


def _slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "decision"


def _normalize_id(value: str) -> str:
    text = value.strip().upper()
    if re.fullmatch(r"\d{4}", text):
        text = f"ADR-{text}"
    if not re.fullmatch(r"ADR-\d{4}", text):
        raise AdrError(f"Invalid ADR id '{value}'. Expected ADR-0001.")
    return text


def _dedupe_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        adr_id = _normalize_id(value)
        if adr_id not in seen:
            seen.add(adr_id)
            result.append(adr_id)
    return result


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_id_csv(value: str | None) -> list[str]:
    return _dedupe_ids(_split_csv(value))


def _source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_scalar(raw: str) -> str | list[str]:
    value = raw.strip()
    if value == "[]":
        return []
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [part.strip().strip('"').strip("'") for part in inner.split(",")]
    return value.strip('"').strip("'")


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise AdrError("ADR markdown must start with YAML frontmatter.")
    end = text.find("\n---", 4)
    if end == -1:
        raise AdrError("ADR frontmatter is not closed with ---.")

    raw_frontmatter = text[4:end].splitlines()
    body = text[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]

    meta: dict[str, Any] = {}
    current_key: str | None = None

    for line in raw_frontmatter:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            if current_key is None:
                raise AdrError(f"List item without key in frontmatter: {line}")
            meta.setdefault(current_key, []).append(stripped[2:].strip().strip('"').strip("'"))
            continue
        if ":" not in line:
            raise AdrError(f"Malformed frontmatter line: {line}")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        parsed = _parse_scalar(raw_value)
        meta[key] = parsed
        current_key = key if parsed == "" and key in LIST_FIELDS else None
        if key in LIST_FIELDS and parsed == "":
            meta[key] = []
            current_key = key

    return meta, body


def _format_yaml_value(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        if not value:
            return ["[]"]
        return [""] + [f"  - {item}" for item in value]
    return [str(value)]


def _render_frontmatter(meta: dict[str, Any]) -> str:
    order = [
        "id",
        "title",
        "status",
        "date",
        "areas",
        "supersedes",
        "superseded_by",
        "related",
        "supersession_reason",
        "keywords",
        "tags",
    ]
    lines = ["---"]
    for key in order:
        if key == "supersession_reason" and not meta.get(key):
            continue
        if key not in meta:
            continue
        rendered = _format_yaml_value(meta[key])
        if len(rendered) == 1 and rendered[0] != "":
            lines.append(f"{key}: {rendered[0]}")
        else:
            lines.append(f"{key}:")
            lines.extend(rendered[1:])
    for key in sorted(k for k in meta if k not in order):
        rendered = _format_yaml_value(meta[key])
        if len(rendered) == 1 and rendered[0] != "":
            lines.append(f"{key}: {rendered[0]}")
        else:
            lines.append(f"{key}:")
            lines.extend(rendered[1:])
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _ensure_list(meta: dict[str, Any], key: str) -> list[str]:
    value = meta.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise AdrError(f"Frontmatter field '{key}' must be a list.")
    return [str(item).strip() for item in value if str(item).strip()]


def _active(status: str, superseded_by: list[str]) -> bool:
    return status in {"accepted", "proposed"} and not superseded_by


def _parse_adr_content(content: str, path: Path, source_mtime: float) -> Decision:
    meta, body = _parse_frontmatter(content)

    for key in REQUIRED_FRONTMATTER:
        if key not in meta:
            raise AdrError(f"{path}: missing required frontmatter field '{key}'.")

    adr_id = _normalize_id(str(meta["id"]))
    status = str(meta["status"]).strip().lower()
    if status not in VALID_STATUSES:
        raise AdrError(f"{path}: invalid status '{status}'.")

    try:
        date.fromisoformat(str(meta["date"]))
    except ValueError as exc:
        raise AdrError(f"{path}: invalid date '{meta['date']}'. Expected YYYY-MM-DD.") from exc

    missing_sections = [section for section in REQUIRED_SECTIONS if section not in body]
    if missing_sections:
        raise AdrError(f"{path}: missing body section(s): {', '.join(missing_sections)}.")

    areas = _ensure_list(meta, "areas")
    supersedes = _dedupe_ids(_ensure_list(meta, "supersedes"))
    superseded_by = _dedupe_ids(_ensure_list(meta, "superseded_by"))
    related = _dedupe_ids(_ensure_list(meta, "related"))
    keywords = _ensure_list(meta, "keywords")
    tags = _ensure_list(meta, "tags")
    reason = str(meta.get("supersession_reason", "")).strip()

    use_cases = [
        f"Understand current decision: {meta['title']}",
        *[f"Find architectural decisions about {area}" for area in areas],
        f"Check superseded decision: {meta['title']}",
    ]

    return Decision(
        id=adr_id,
        title=str(meta["title"]).strip(),
        status=status,
        date=str(meta["date"]),
        areas=areas,
        supersedes=supersedes,
        superseded_by=superseded_by,
        related=related,
        keywords=keywords,
        tags=tags,
        supersession_reason=reason,
        path=path.stem,
        source_path=str(path),
        source_mtime=source_mtime,
        source_hash=_source_hash(content),
        active=_active(status, superseded_by),
        priority=10,
        content=content,
        token_estimate=_estimate_tokens(content),
        use_cases=use_cases,
    )


def parse_adr(path: Path) -> Decision:
    content = path.read_text()
    return _parse_adr_content(content, path, path.stat().st_mtime)


def _section_json(decision: Decision) -> dict[str, Any]:
    return asdict(decision)


def _load_decisions_from_source() -> list[Decision]:
    adr_dir = _adr_dir()
    if not adr_dir.exists():
        return []
    return [parse_adr(path) for path in sorted(adr_dir.glob("*.md"))]


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")


def rebuild_index() -> list[Decision]:
    decisions = _load_decisions_from_source()
    target = _decisions_dir()
    if target.exists():
        shutil.rmtree(target)
    sections_dir = target / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)

    keywords_index: dict[str, list[str]] = {}
    use_cases_index: dict[str, list[str]] = {}
    tags_index: dict[str, list[str]] = {}

    for decision in decisions:
        _write_json(sections_dir / f"{decision.path}.json", _section_json(decision))
        for value in decision.keywords + decision.areas + [decision.id.lower(), decision.status]:
            keywords_index.setdefault(value, []).append(decision.path)
        for value in decision.use_cases:
            use_cases_index.setdefault(value, []).append(decision.path)
        for value in decision.tags:
            tags_index.setdefault(value, []).append(decision.path)

    nodes = [
        {
            "id": d.id,
            "title": d.title,
            "status": d.status,
            "active": d.active,
            "path": d.path,
            "date": d.date,
        }
        for d in sorted(decisions, key=lambda item: (item.date, item.id))
    ]
    edges = []
    for d in decisions:
        edges.extend({"from": d.id, "to": old_id, "type": "supersedes"} for old_id in d.supersedes)
        edges.extend({"from": d.id, "to": rel_id, "type": "related"} for rel_id in d.related)

    timeline = [
        {
            "id": d.id,
            "title": d.title,
            "status": d.status,
            "date": d.date,
            "active": d.active,
            "supersedes": d.supersedes,
            "superseded_by": d.superseded_by,
            "related": d.related,
            "supersession_reason": d.supersession_reason,
        }
        for d in sorted(decisions, key=lambda item: (item.date, item.id))
    ]

    _write_json(
        target / "index.json",
        {
            "name": "project",
            "display_name": "Project Decisions",
            "version": "",
            "base_url": "",
            "section_count": len(decisions),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "source_dir": str(_adr_dir()),
        },
    )
    _write_json(target / "keywords.json", keywords_index)
    _write_json(target / "use_cases.json", use_cases_index)
    _write_json(target / "tags.json", tags_index)
    _write_json(target / "graph.json", {"nodes": nodes, "edges": edges})
    _write_json(target / "timeline.json", {"items": timeline})
    return decisions


def _load_indexed_decisions() -> list[dict[str, Any]]:
    sections_dir = _decisions_dir() / "sections"
    if not sections_dir.exists():
        return []
    decisions = []
    for path in sorted(sections_dir.glob("*.json")):
        try:
            decisions.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            continue
    return decisions


def _find_indexed_decision(target: str) -> dict[str, Any] | None:
    normalized_target = target.upper()
    path_target = target.removesuffix(".md").removesuffix(".json")
    for decision in _load_indexed_decisions():
        if decision.get("id", "").upper() == normalized_target or decision.get("path") == path_target:
            return decision
    return None


def _score_decision(query: str, decision: dict[str, Any]) -> float:
    terms = query.lower().strip().split()
    if not terms:
        return 0.0
    score = 0.0
    title = str(decision.get("title", "")).lower()
    adr_id = str(decision.get("id", "")).lower()
    path = str(decision.get("path", "")).lower()
    keywords = [str(item).lower() for item in decision.get("keywords", [])]
    areas = [str(item).lower() for item in decision.get("areas", [])]
    tags = [str(item).lower() for item in decision.get("tags", [])]
    use_cases = [str(item).lower() for item in decision.get("use_cases", [])]
    links = [str(item).lower() for key in ("supersedes", "superseded_by", "related") for item in decision.get(key, [])]

    for term in terms:
        if term == adr_id:
            score += 8.0
        if term in path:
            score += 4.0
        if term in title:
            score += 3.0
        if term in keywords:
            score += 3.0
        if term in areas:
            score += 2.5
        if term in tags:
            score += 1.0
        if any(term in use_case for use_case in use_cases):
            score += 2.0
        if term in links:
            score += 2.0

    return score + float(decision.get("priority", 0)) * 0.5 if score else 0.0


def search_decisions(query: str, *, active_only: bool = True, top: int = 5) -> list[AdrSearchResult]:
    results: list[AdrSearchResult] = []
    for decision in _load_indexed_decisions():
        if active_only and not decision.get("active", False):
            continue
        score = _score_decision(query, decision)
        if score <= 0:
            continue
        results.append(
            AdrSearchResult(
                id=decision.get("id", ""),
                title=decision.get("title", ""),
                status=decision.get("status", ""),
                active=bool(decision.get("active", False)),
                path=decision.get("path", ""),
                score=score,
                date=decision.get("date", ""),
                areas=decision.get("areas", []),
                supersedes=decision.get("supersedes", []),
                superseded_by=decision.get("superseded_by", []),
                related=decision.get("related", []),
            )
        )
    results.sort(key=lambda item: (-item.score, item.date, item.id))
    return results[:top]


def _format_adr_list(decisions: list[dict[str, Any]], as_json: bool) -> str:
    if as_json:
        return json.dumps(decisions, indent=2)
    if not decisions:
        return "No ADRs found."
    lines = []
    for decision in decisions:
        lines.append(
            f"{decision['id']} {decision['status']} {decision['date']} {decision['title']}"
        )
        if decision.get("areas"):
            lines.append(f"  areas: {', '.join(decision['areas'])}")
        if decision.get("supersedes"):
            lines.append(f"  supersedes: {', '.join(decision['supersedes'])}")
        if decision.get("superseded_by"):
            lines.append(f"  superseded_by: {', '.join(decision['superseded_by'])}")
    return "\n".join(lines)


def _format_adr_search(results: list[AdrSearchResult], as_json: bool) -> str:
    if as_json:
        return json.dumps([asdict(result) for result in results], indent=2)
    if not results:
        return "No ADRs found."
    lines = []
    for index, result in enumerate(results, 1):
        state = "active" if result.active else "inactive"
        lines.append(
            f"{index}. [decisions] {result.id} {result.status} {state} "
            f"{result.title} score={result.score:.2f}"
        )
        lines.append(f"   path: {result.path}")
        if result.supersedes:
            lines.append(f"   supersedes: {', '.join(result.supersedes)}")
        if result.superseded_by:
            lines.append(f"   superseded_by: {', '.join(result.superseded_by)}")
    return "\n".join(lines)


def _format_adr_read(decision: dict[str, Any], preview: bool, as_json: bool) -> str:
    payload = dict(decision)
    if preview:
        words = payload.get("content", "").split()
        payload["content"] = " ".join(words[:150])
        payload["is_preview"] = len(words) > 150
    if as_json:
        return json.dumps(payload, indent=2)

    lines = [
        f"# {payload['id']}: {payload['title']}",
        "",
        f"Status: {payload['status']}",
        f"Date: {payload['date']}",
        f"Areas: {', '.join(payload.get('areas', []))}",
        f"Supersedes: {', '.join(payload.get('supersedes', [])) or '-'}",
        f"Superseded by: {', '.join(payload.get('superseded_by', [])) or '-'}",
        f"Related: {', '.join(payload.get('related', [])) or '-'}",
        f"Tokens: {payload.get('token_estimate', 0)}",
        "",
        payload.get("content", ""),
    ]
    if preview and payload.get("is_preview"):
        lines.append("\n[PREVIEW]")
    return "\n".join(lines)


def _group_timeline(query: str) -> dict[str, list[dict[str, Any]]]:
    all_decisions = {d["id"]: d for d in _load_indexed_decisions()}
    matched = search_decisions(query, active_only=False, top=50)
    selected_ids = {item.id for item in matched}
    supersession_ids: set[str] = set()
    for item in matched:
        supersession_ids.update(item.supersedes)
        supersession_ids.update(item.superseded_by)
        selected_ids.update(item.related)
    selected_ids.update(supersession_ids)

    selected = [all_decisions[adr_id] for adr_id in selected_ids if adr_id in all_decisions]
    selected.sort(key=lambda item: (item.get("date", ""), item.get("id", "")))

    groups = {"Active": [], "Superseded": [], "Deprecated/Rejected": [], "Related": []}
    matched_ids = {item.id for item in matched}
    for decision in selected:
        decision_id = decision.get("id")
        if decision_id not in matched_ids and decision_id not in supersession_ids:
            groups["Related"].append(decision)
        elif decision.get("active"):
            groups["Active"].append(decision)
        elif decision.get("status") == "superseded" or decision.get("superseded_by"):
            groups["Superseded"].append(decision)
        elif decision.get("status") in {"deprecated", "rejected"}:
            groups["Deprecated/Rejected"].append(decision)
        else:
            groups["Related"].append(decision)
    return groups


def _format_timeline(query: str, as_json: bool) -> str:
    groups = _group_timeline(query)
    if as_json:
        return json.dumps({"topic": query, "groups": groups}, indent=2)
    lines = [f"Topic: {query}"]
    for heading, decisions in groups.items():
        lines.append("")
        lines.append(f"{heading}:")
        if not decisions:
            lines.append("- none")
            continue
        for decision in decisions:
            suffix = ""
            if decision.get("superseded_by"):
                suffix = f", superseded by {', '.join(decision['superseded_by'])}"
            lines.append(f"- {decision['id']} {decision['status']} {decision['date']}{suffix}")
            lines.append(f"  {decision['title']}.")
            if decision.get("supersedes"):
                lines.append(f"  Supersedes: {', '.join(decision['supersedes'])}")
            if decision.get("supersession_reason"):
                lines.append(f"  Replaced because: {decision['supersession_reason']}")
    return "\n".join(lines)


def _load_source_meta(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text()
    meta, body = _parse_frontmatter(text)
    return meta, body


def _write_source_meta(path: Path, meta: dict[str, Any], body: str) -> None:
    path.write_text(_render_frontmatter(meta) + body.rstrip() + "\n")


def _source_path_by_id(adr_id: str) -> Path | None:
    for path in sorted(_adr_dir().glob("*.md")):
        try:
            decision = parse_adr(path)
        except AdrError:
            continue
        if decision.id == adr_id:
            return path
    return None


def _existing_ids() -> dict[str, Path]:
    ids: dict[str, Path] = {}
    for path in sorted(_adr_dir().glob("*.md")):
        decision = parse_adr(path)
        ids[decision.id] = path
    return ids


def _next_adr_id() -> str:
    max_id = 0
    for adr_id in _existing_ids():
        max_id = max(max_id, int(adr_id.split("-")[1]))
    return f"ADR-{max_id + 1:04d}"


def _filename_for(adr_id: str, title: str) -> str:
    number = adr_id.split("-")[1]
    return f"{number}-{_slugify(title)}.md"


def render_adr_markdown(
    *,
    adr_id: str,
    title: str,
    status: str,
    adr_date: str,
    areas: list[str],
    supersedes: list[str],
    superseded_by: list[str],
    related: list[str],
    supersession_reason: str,
    keywords: list[str],
    tags: list[str],
    context: str,
    decision: str,
    alternatives: str,
    consequences: str,
    links: str = "",
) -> str:
    meta: dict[str, Any] = {
        "id": adr_id,
        "title": title,
        "status": status,
        "date": adr_date,
        "areas": areas,
        "supersedes": supersedes,
        "superseded_by": superseded_by,
        "related": related,
        "keywords": keywords,
        "tags": tags,
    }
    if supersession_reason:
        meta["supersession_reason"] = supersession_reason
    body = "\n".join(
        [
            f"# {adr_id}: {title}",
            "",
            "## Context",
            "",
            context.strip(),
            "",
            "## Decision",
            "",
            decision.strip(),
            "",
            "## Alternatives Considered",
            "",
            alternatives.strip(),
            "",
            "## Consequences",
            "",
            consequences.strip(),
            "",
            "## Links",
            "",
            links.strip(),
            "",
        ]
    )
    return _render_frontmatter(meta) + body


def _create_adr_from_flags(args: argparse.Namespace) -> Decision:
    required = ["title", "status", "areas", "keywords", "tags", "context", "decision", "alternatives", "consequences"]
    missing = [name for name in required if not getattr(args, name)]
    if missing:
        raise AdrError(f"Missing required option(s): {', '.join('--' + name.replace('_', '-') for name in missing)}")

    status = args.status.lower()
    if status not in VALID_STATUSES:
        raise AdrError(f"Invalid status '{args.status}'.")

    supersedes = _split_id_csv(args.supersedes)
    if supersedes and not args.supersession_reason:
        raise AdrError("--supersession-reason is required when --supersedes is present.")

    related = _split_id_csv(args.related)
    existing = _existing_ids()
    missing_ids = [adr_id for adr_id in supersedes + related if adr_id not in existing]
    if missing_ids:
        raise AdrError(f"Linked ADR(s) do not exist: {', '.join(missing_ids)}")

    adr_id = _next_adr_id()
    adr_date = args.date or date.today().isoformat()
    content = render_adr_markdown(
        adr_id=adr_id,
        title=args.title,
        status=status,
        adr_date=adr_date,
        areas=_split_csv(args.areas),
        supersedes=supersedes,
        superseded_by=[],
        related=related,
        supersession_reason=args.supersession_reason or "",
        keywords=_split_csv(args.keywords),
        tags=_split_csv(args.tags),
        context=args.context,
        decision=args.decision,
        alternatives=args.alternatives,
        consequences=args.consequences,
        links=args.links or "",
    )
    path = _adr_dir() / _filename_for(adr_id, args.title)
    _parse_adr_content(content, path, 0.0)

    _adr_dir().mkdir(parents=True, exist_ok=True)
    path.write_text(content)

    for old_id in supersedes:
        old_path = existing[old_id]
        meta, body = _load_source_meta(old_path)
        meta["status"] = "superseded"
        meta["superseded_by"] = _dedupe_ids(_ensure_list(meta, "superseded_by") + [adr_id])
        _write_source_meta(old_path, meta, body)
    for related_id in related:
        _add_related(adr_id, related_id)

    return parse_adr(path)


def _create_adr_from_file(args: argparse.Namespace) -> Decision:
    source = Path(args.from_file)
    if not source.exists():
        raise AdrError(f"File not found: {source}")
    content = source.read_text()
    meta, _ = _parse_frontmatter(content)
    if not meta.get("id"):
        meta["id"] = _next_adr_id()
        content = _render_frontmatter(meta) + _parse_frontmatter(content)[1]
    adr_id = _normalize_id(str(meta["id"]))
    existing = _existing_ids()
    if adr_id in existing:
        raise AdrError(f"ADR ID already exists: {adr_id} in {existing[adr_id]}")
    linked_ids = _dedupe_ids(_ensure_list(meta, "supersedes") + _ensure_list(meta, "related"))
    missing_ids = [linked_id for linked_id in linked_ids if linked_id not in existing]
    if missing_ids:
        raise AdrError(f"Linked ADR(s) do not exist: {', '.join(missing_ids)}")
    path = _adr_dir() / _filename_for(adr_id, str(meta.get("title", adr_id)))
    decision = _parse_adr_content(content, path, 0.0)

    _adr_dir().mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    for old_id in decision.supersedes:
        if old_id not in existing:
            raise AdrError(f"Linked ADR does not exist: {old_id}")
        old_path = existing[old_id]
        if old_path == path:
            continue
        old_meta, old_body = _load_source_meta(old_path)
        old_meta["status"] = "superseded"
        old_meta["superseded_by"] = _dedupe_ids(_ensure_list(old_meta, "superseded_by") + [adr_id])
        _write_source_meta(old_path, old_meta, old_body)
    for related_id in decision.related:
        if related_id not in existing:
            raise AdrError(f"Linked ADR does not exist: {related_id}")
        _add_related(adr_id, related_id)
    return parse_adr(path)


def _add_related(from_id: str, to_id: str) -> None:
    for adr_id, related_id in ((from_id, to_id), (to_id, from_id)):
        path = _source_path_by_id(adr_id)
        if path is None:
            raise AdrError(f"ADR not found: {adr_id}")
        meta, body = _load_source_meta(path)
        meta["related"] = _dedupe_ids(_ensure_list(meta, "related") + [related_id])
        _write_source_meta(path, meta, body)


def _supersede(old_id: str, new_id: str, reason: str) -> None:
    if not reason.strip():
        raise AdrError("--reason is required.")
    old_id = _normalize_id(old_id)
    new_id = _normalize_id(new_id)
    old_path = _source_path_by_id(old_id)
    new_path = _source_path_by_id(new_id)
    if old_path is None:
        raise AdrError(f"ADR not found: {old_id}")
    if new_path is None:
        raise AdrError(f"ADR not found: {new_id}")

    old_meta, old_body = _load_source_meta(old_path)
    old_meta["status"] = "superseded"
    old_meta["superseded_by"] = _dedupe_ids(_ensure_list(old_meta, "superseded_by") + [new_id])
    _write_source_meta(old_path, old_meta, old_body)

    new_meta, new_body = _load_source_meta(new_path)
    new_meta["supersedes"] = _dedupe_ids(_ensure_list(new_meta, "supersedes") + [old_id])
    new_meta["supersession_reason"] = reason.strip()
    _write_source_meta(new_path, new_meta, new_body)


def status_issues() -> list[str]:
    issues: list[str] = []
    source_by_id: dict[str, Decision] = {}
    try:
        for decision in _load_decisions_from_source():
            source_by_id[decision.id] = decision
    except AdrError as exc:
        return [str(exc)]

    indexed = _load_indexed_decisions()
    indexed_by_id = {item.get("id"): item for item in indexed}

    if source_by_id and not (_decisions_dir() / "index.json").exists():
        issues.append("decision index is missing")

    for adr_id, decision in source_by_id.items():
        indexed_decision = indexed_by_id.get(adr_id)
        if not indexed_decision:
            issues.append(f"{adr_id} exists in markdown but not in decisions index")
            continue
        if indexed_decision.get("source_hash") != decision.source_hash:
            issues.append(f"{adr_id} markdown changed after indexed JSON")
        elif float(indexed_decision.get("source_mtime", 0)) + 0.001 < decision.source_mtime:
            issues.append(f"{adr_id} markdown changed after indexed JSON")

    for adr_id in indexed_by_id:
        if adr_id not in source_by_id:
            issues.append(f"{adr_id} exists in decisions index but not markdown")

    return issues


def validation_errors() -> list[str]:
    errors: list[str] = []
    decisions: list[Decision] = []
    seen: dict[str, Path] = {}

    for path in sorted(_adr_dir().glob("*.md")) if _adr_dir().exists() else []:
        try:
            decision = parse_adr(path)
        except AdrError as exc:
            errors.append(str(exc))
            continue
        expected_prefix = decision.id.split("-")[1]
        if not path.name.startswith(f"{expected_prefix}-"):
            errors.append(f"{decision.id}: filename must start with {expected_prefix}-")
        if decision.id in seen:
            errors.append(f"{decision.id}: duplicate ID in {path} and {seen[decision.id]}")
        seen[decision.id] = path
        decisions.append(decision)

    by_id = {decision.id: decision for decision in decisions}

    for decision in decisions:
        linked = decision.supersedes + decision.superseded_by + decision.related
        for linked_id in linked:
            if linked_id not in by_id:
                errors.append(f"{decision.id}: linked ADR does not exist: {linked_id}")

        if decision.supersedes and not decision.supersession_reason:
            errors.append(f"{decision.id}: supersession_reason is required when supersedes is set")
        if decision.active and decision.superseded_by:
            errors.append(f"{decision.id}: active ADR cannot have superseded_by")
        if decision.superseded_by and decision.status != "superseded":
            errors.append(f"{decision.id}: ADR with superseded_by must have status superseded")
        if decision.status == "superseded" and not decision.superseded_by:
            errors.append(f"{decision.id}: superseded ADR must have superseded_by")
        if decision.status in {"deprecated", "superseded", "rejected"} and decision.active:
            errors.append(f"{decision.id}: inactive status cannot be active")

        for old_id in decision.supersedes:
            old = by_id.get(old_id)
            if old and decision.id not in old.superseded_by:
                errors.append(f"{decision.id}: supersedes {old_id}, but {old_id} does not list superseded_by {decision.id}")
            if old and decision.id in old.supersedes:
                errors.append(f"{decision.id}: direct supersession cycle with {old_id}")
        for new_id in decision.superseded_by:
            new = by_id.get(new_id)
            if new and decision.id not in new.supersedes:
                errors.append(f"{decision.id}: superseded_by {new_id}, but {new_id} does not supersede {decision.id}")
        for related_id in decision.related:
            related = by_id.get(related_id)
            if related and decision.id not in related.related:
                errors.append(f"{decision.id}: related link to {related_id} is not reciprocal")

    errors.extend(status_issues())
    return errors


def cmd_list(args: argparse.Namespace) -> None:
    decisions = _load_indexed_decisions()
    if not args.all:
        decisions = [decision for decision in decisions if decision.get("active", False)]
    decisions.sort(key=lambda item: (item.get("date", ""), item.get("id", "")))
    print(_format_adr_list(decisions, args.json))


def cmd_search(args: argparse.Namespace) -> None:
    print(_format_adr_search(search_decisions(args.query, active_only=not args.all, top=args.top), args.json))


def cmd_read(args: argparse.Namespace) -> None:
    decision = _find_indexed_decision(args.target)
    if decision is None:
        print(f"ADR not found: {args.target}", file=sys.stderr)
        sys.exit(1)
    print(_format_adr_read(decision, args.preview, args.json))


def cmd_timeline(args: argparse.Namespace) -> None:
    print(_format_timeline(args.query, args.json))


def cmd_new(args: argparse.Namespace) -> None:
    try:
        decision = _create_adr_from_file(args) if args.from_file else _create_adr_from_flags(args)
        rebuild_index()
    except AdrError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"Created {decision.id}: {decision.source_path}")


def cmd_supersede(args: argparse.Namespace) -> None:
    try:
        _supersede(args.old_id, args.new_id, args.reason)
        rebuild_index()
    except AdrError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"{_normalize_id(args.new_id)} supersedes {_normalize_id(args.old_id)}")


def cmd_link(args: argparse.Namespace) -> None:
    if args.type != "related":
        print("Only --type related is supported for now.", file=sys.stderr)
        sys.exit(1)
    try:
        _add_related(_normalize_id(args.from_id), _normalize_id(args.to_id))
        rebuild_index()
    except AdrError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"Linked {_normalize_id(args.from_id)} <-> {_normalize_id(args.to_id)}")


def cmd_index(args: argparse.Namespace) -> None:
    try:
        decisions = rebuild_index()
    except AdrError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"Indexed {len(decisions)} ADRs into decisions/project")


def cmd_status(args: argparse.Namespace) -> None:
    issues = status_issues()
    if not issues:
        print("ADR index is up to date.")
        return
    print("ADR index is stale.")
    for issue in issues:
        print(f"- {issue}")
    print("Run: .king-context/bin/kctx adr index")
    sys.exit(1)


def cmd_validate(args: argparse.Namespace) -> None:
    errors = validation_errors()
    if errors:
        print("ADR validation failed.")
        for error in errors:
            print(f"- {error}")
        sys.exit(1)
    print("ADR validation passed.")


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p_adr = subparsers.add_parser("adr", help="Manage architectural decision records")
    adr_sub = p_adr.add_subparsers(dest="adr_command")

    p_list = adr_sub.add_parser("list", help="List ADRs")
    p_list.add_argument("--active", action="store_true", help="Only active decisions (default)")
    p_list.add_argument("--all", action="store_true", help="Include inactive decisions")
    p_list.add_argument("--json", action="store_true", help="JSON output")
    p_list.set_defaults(func=cmd_list)

    p_search = adr_sub.add_parser("search", help="Search ADR metadata")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--active", action="store_true", help="Only active decisions (default)")
    p_search.add_argument("--all", action="store_true", help="Include inactive decisions")
    p_search.add_argument("--top", type=int, default=5, help="Max results (default: 5)")
    p_search.add_argument("--json", action="store_true", help="JSON output")
    p_search.set_defaults(func=cmd_search)

    p_read = adr_sub.add_parser("read", help="Read an ADR by ID or path")
    p_read.add_argument("target", help="ADR ID or indexed path")
    p_read.add_argument("--preview", action="store_true", help="Show first ~150 words only")
    p_read.add_argument("--json", action="store_true", help="JSON output")
    p_read.set_defaults(func=cmd_read)

    p_timeline = adr_sub.add_parser("timeline", help="Show ADR timeline for a topic")
    p_timeline.add_argument("query", help="Topic query")
    p_timeline.add_argument("--compact", action="store_true", help="Compact output (default)")
    p_timeline.add_argument("--json", action="store_true", help="JSON output")
    p_timeline.set_defaults(func=cmd_timeline)

    p_new = adr_sub.add_parser("new", help="Create a new ADR")
    p_new.add_argument("--from-file", default=None, help="Create from complete ADR markdown file")
    p_new.add_argument("--title", default=None)
    p_new.add_argument("--status", default="accepted")
    p_new.add_argument("--date", default=None)
    p_new.add_argument("--areas", default=None, help="Comma-separated areas")
    p_new.add_argument("--keywords", default=None, help="Comma-separated keywords")
    p_new.add_argument("--tags", default=None, help="Comma-separated tags")
    p_new.add_argument("--supersedes", default=None, help="Comma-separated ADR IDs")
    p_new.add_argument("--supersession-reason", default=None)
    p_new.add_argument("--related", default=None, help="Comma-separated ADR IDs")
    p_new.add_argument("--context", default=None)
    p_new.add_argument("--decision", default=None)
    p_new.add_argument("--alternatives", default=None)
    p_new.add_argument("--consequences", default=None)
    p_new.add_argument("--links", default="")
    p_new.set_defaults(func=cmd_new)

    p_supersede = adr_sub.add_parser("supersede", help="Mark one ADR as superseded by another")
    p_supersede.add_argument("old_id")
    p_supersede.add_argument("new_id")
    p_supersede.add_argument("--reason", required=True)
    p_supersede.set_defaults(func=cmd_supersede)

    p_link = adr_sub.add_parser("link", help="Link related ADRs")
    p_link.add_argument("from_id")
    p_link.add_argument("to_id")
    p_link.add_argument("--type", default="related", choices=["related"])
    p_link.set_defaults(func=cmd_link)

    p_index = adr_sub.add_parser("index", help="Rebuild decision index from ADR markdown")
    p_index.set_defaults(func=cmd_index)

    p_status = adr_sub.add_parser("status", help="Check ADR index sync state")
    p_status.set_defaults(func=cmd_status)

    p_validate = adr_sub.add_parser("validate", help="Validate ADR markdown and graph state")
    p_validate.set_defaults(func=cmd_validate)

    p_adr.set_defaults(func=lambda args: p_adr.print_help())
