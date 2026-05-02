"""Tests for ADR decision memory CLI support."""

import json
import sys
from pathlib import Path

import pytest

from context_cli import adr


def _patch_project(tmp_path, monkeypatch):
    import context_cli.cli as cli_mod

    monkeypatch.setattr(cli_mod, "PROJECT_ROOT", tmp_path)
    return tmp_path / ".king-context" / "adr", tmp_path / ".king-context" / "decisions" / "project"


def _write_adr(
    adr_dir,
    *,
    adr_id="ADR-0001",
    title="Use Postgres advisory locks",
    status="accepted",
    adr_date="2026-05-02",
    areas=None,
    supersedes=None,
    superseded_by=None,
    related=None,
    supersession_reason="",
    keywords=None,
    tags=None,
):
    areas = areas or ["jobs", "database"]
    supersedes = supersedes or []
    superseded_by = superseded_by or []
    related = related or []
    keywords = keywords or ["postgres", "locks"]
    tags = tags or ["architecture"]
    content = adr.render_adr_markdown(
        adr_id=adr_id,
        title=title,
        status=status,
        adr_date=adr_date,
        areas=areas,
        supersedes=supersedes,
        superseded_by=superseded_by,
        related=related,
        supersession_reason=supersession_reason,
        keywords=keywords,
        tags=tags,
        context="Workers need coordination.",
        decision="Use the selected coordination primitive.",
        alternatives="Redis locks were considered.",
        consequences="Deploy behavior is easier to reason about.",
    )
    adr_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{adr_id.split('-')[1]}-{title.lower().replace(' ', '-')}.md"
    path = adr_dir / filename
    path.write_text(content)
    return path


def _run_cli(args, monkeypatch):
    from context_cli.cli import main

    monkeypatch.setattr(sys, "argv", ["kctx"] + args)
    main()


def _new_adr_args(*, title="Use Postgres advisory locks", adr_date="2026-05-02", extra=None):
    args = [
        "adr",
        "new",
        "--title",
        title,
        "--status",
        "accepted",
        "--date",
        adr_date,
        "--areas",
        "jobs,database,concurrency",
        "--keywords",
        "postgres,advisory-locks,jobs",
        "--tags",
        "architecture,database",
        "--context",
        "Workers need one owner.",
        "--decision",
        "Use Postgres advisory locks.",
        "--alternatives",
        "Redis locks.",
        "--consequences",
        "Locks are scoped to database sessions.",
    ]
    if extra:
        args.extend(extra)
    return args


def test_parse_adr_markdown_frontmatter(tmp_path, monkeypatch):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    path = _write_adr(adr_dir)

    decision = adr.parse_adr(path)

    assert decision.id == "ADR-0001"
    assert decision.status == "accepted"
    assert decision.active is True
    assert decision.areas == ["jobs", "database"]
    assert "Find architectural decisions about jobs" in decision.use_cases


def test_rebuild_index_writes_decision_json(tmp_path, monkeypatch):
    adr_dir, decisions_dir = _patch_project(tmp_path, monkeypatch)
    _write_adr(adr_dir)

    indexed = adr.rebuild_index()

    section_path = decisions_dir / "sections" / "0001-use-postgres-advisory-locks.json"
    data = json.loads(section_path.read_text())
    assert len(indexed) == 1
    assert data["id"] == "ADR-0001"
    assert data["active"] is True
    assert data["content"].startswith("---")
    assert (decisions_dir / "graph.json").exists()
    assert (decisions_dir / "timeline.json").exists()


def test_cli_new_creates_adr_and_index(tmp_path, monkeypatch, capsys):
    adr_dir, decisions_dir = _patch_project(tmp_path, monkeypatch)

    _run_cli(_new_adr_args(), monkeypatch)

    out = capsys.readouterr().out
    assert "Created ADR-0001" in out
    assert (adr_dir / "0001-use-postgres-advisory-locks.md").exists()
    assert (decisions_dir / "sections" / "0001-use-postgres-advisory-locks.json").exists()


def test_cli_new_rejects_invalid_date_before_writing(tmp_path, monkeypatch, capsys):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)

    with pytest.raises(SystemExit):
        _run_cli(_new_adr_args(adr_date="2026-99-99"), monkeypatch)

    err = capsys.readouterr().err
    assert "invalid date '2026-99-99'" in err
    assert not list(adr_dir.glob("*.md"))


def test_cli_new_rejects_invalid_superseding_adr_before_updating_old_adr(tmp_path, monkeypatch, capsys):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(adr_dir, adr_id="ADR-0001", title="Use Redis locks")

    with pytest.raises(SystemExit):
        _run_cli(
            _new_adr_args(
                title="Use Postgres advisory locks",
                adr_date="2026-99-99",
                extra=[
                    "--supersedes",
                    "ADR-0001",
                    "--supersession-reason",
                    "Redis locks were unreliable during deploys.",
                ],
            ),
            monkeypatch,
        )

    err = capsys.readouterr().err
    old = adr.parse_adr(adr_dir / "0001-use-redis-locks.md")
    assert "invalid date '2026-99-99'" in err
    assert old.status == "accepted"
    assert old.superseded_by == []
    assert not (adr_dir / "0002-use-postgres-advisory-locks.md").exists()


def test_search_excludes_superseded_by_default(tmp_path, monkeypatch, capsys):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(
        adr_dir,
        adr_id="ADR-0001",
        title="Use Redis locks",
        status="superseded",
        superseded_by=["ADR-0002"],
        keywords=["redis", "locks"],
    )
    _write_adr(
        adr_dir,
        adr_id="ADR-0002",
        title="Use Postgres advisory locks",
        supersedes=["ADR-0001"],
        supersession_reason="Redis locks created unsafe ownership behavior during deploys.",
    )
    adr.rebuild_index()

    _run_cli(["adr", "search", "locks"], monkeypatch)
    out = capsys.readouterr().out
    assert "ADR-0002" in out
    assert "1. [decisions] ADR-0001" not in out

    _run_cli(["adr", "search", "locks", "--all"], monkeypatch)
    out = capsys.readouterr().out
    assert "ADR-0001" in out


def test_read_by_id_and_path(tmp_path, monkeypatch, capsys):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(adr_dir)
    adr.rebuild_index()

    _run_cli(["adr", "read", "ADR-0001", "--preview"], monkeypatch)
    out = capsys.readouterr().out
    assert "# ADR-0001: Use Postgres advisory locks" in out

    _run_cli(["adr", "read", "0001-use-postgres-advisory-locks", "--json"], monkeypatch)
    data = json.loads(capsys.readouterr().out)
    assert data["id"] == "ADR-0001"


def test_timeline_shows_supersession_reason(tmp_path, monkeypatch, capsys):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(
        adr_dir,
        adr_id="ADR-0001",
        title="Use Redis locks",
        status="superseded",
        superseded_by=["ADR-0002"],
        keywords=["redis", "locks"],
    )
    _write_adr(
        adr_dir,
        adr_id="ADR-0002",
        title="Use Postgres advisory locks",
        supersedes=["ADR-0001"],
        supersession_reason="Redis locks created unsafe ownership behavior during deploys.",
    )
    adr.rebuild_index()

    _run_cli(["adr", "timeline", "locks"], monkeypatch)
    out = capsys.readouterr().out
    assert "Active:" in out
    assert "Superseded:" in out
    assert "Replaced because: Redis locks created unsafe ownership behavior during deploys." in out


def test_timeline_includes_superseded_history_when_only_new_adr_matches(tmp_path, monkeypatch, capsys):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(
        adr_dir,
        adr_id="ADR-0001",
        title="Use Redis locks",
        status="superseded",
        superseded_by=["ADR-0002"],
        keywords=["redis", "locks"],
    )
    _write_adr(
        adr_dir,
        adr_id="ADR-0002",
        title="Use Postgres advisory locks",
        supersedes=["ADR-0001"],
        supersession_reason="Redis locks created unsafe ownership behavior during deploys.",
        keywords=["postgres", "advisory-locks"],
    )
    adr.rebuild_index()

    _run_cli(["adr", "timeline", "postgres"], monkeypatch)
    out = capsys.readouterr().out
    assert "- ADR-0002 accepted" in out
    assert "- ADR-0001 superseded" in out
    assert "superseded by ADR-0002" in out


def test_supersede_updates_both_adrs(tmp_path, monkeypatch, capsys):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(adr_dir, adr_id="ADR-0001", title="Use Redis locks", keywords=["redis", "locks"])
    _write_adr(adr_dir, adr_id="ADR-0002", title="Use Postgres advisory locks")
    adr.rebuild_index()

    _run_cli(
        [
            "adr",
            "supersede",
            "ADR-0001",
            "ADR-0002",
            "--reason",
            "Redis locks created unsafe ownership behavior during deploys.",
        ],
        monkeypatch,
    )

    assert "ADR-0002 supersedes ADR-0001" in capsys.readouterr().out
    old = adr.parse_adr(adr_dir / "0001-use-redis-locks.md")
    new = adr.parse_adr(adr_dir / "0002-use-postgres-advisory-locks.md")
    assert old.status == "superseded"
    assert old.superseded_by == ["ADR-0002"]
    assert new.supersedes == ["ADR-0001"]
    assert new.supersession_reason


def test_supersede_rejects_self_supersession_before_writing(tmp_path, monkeypatch, capsys):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(adr_dir, adr_id="ADR-0001", title="Use Redis locks", keywords=["redis", "locks"])
    adr.rebuild_index()

    with pytest.raises(SystemExit):
        _run_cli(
            [
                "adr",
                "supersede",
                "ADR-0001",
                "ADR-0001",
                "--reason",
                "Redis locks created unsafe ownership behavior during deploys.",
            ],
            monkeypatch,
        )

    err = capsys.readouterr().err
    assert "ADR cannot supersede itself: ADR-0001" in err
    decision = adr.parse_adr(adr_dir / "0001-use-redis-locks.md")
    assert decision.status == "accepted"
    assert decision.superseded_by == []
    assert decision.supersedes == []
    assert decision.supersession_reason == ""


def test_link_adds_reciprocal_related_links(tmp_path, monkeypatch):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(adr_dir, adr_id="ADR-0001", title="Use Postgres advisory locks")
    _write_adr(adr_dir, adr_id="ADR-0002", title="Use job queue")
    adr.rebuild_index()

    _run_cli(["adr", "link", "ADR-0001", "ADR-0002"], monkeypatch)

    first = adr.parse_adr(adr_dir / "0001-use-postgres-advisory-locks.md")
    second = adr.parse_adr(adr_dir / "0002-use-job-queue.md")
    assert first.related == ["ADR-0002"]
    assert second.related == ["ADR-0001"]


def test_link_rejects_missing_adr_before_writing(tmp_path, monkeypatch, capsys):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(adr_dir, adr_id="ADR-0001", title="Use Postgres advisory locks")
    adr.rebuild_index()

    with pytest.raises(SystemExit):
        _run_cli(["adr", "link", "ADR-0001", "ADR-9999"], monkeypatch)

    err = capsys.readouterr().err
    assert "ADR not found: ADR-9999" in err
    decision = adr.parse_adr(adr_dir / "0001-use-postgres-advisory-locks.md")
    assert decision.related == []


def test_link_rejects_self_link_before_writing(tmp_path, monkeypatch, capsys):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(adr_dir, adr_id="ADR-0001", title="Use Postgres advisory locks")
    adr.rebuild_index()

    with pytest.raises(SystemExit):
        _run_cli(["adr", "link", "ADR-0001", "ADR-0001"], monkeypatch)

    err = capsys.readouterr().err
    assert "ADR cannot link to itself: ADR-0001" in err
    decision = adr.parse_adr(adr_dir / "0001-use-postgres-advisory-locks.md")
    assert decision.related == []


def test_new_with_related_adds_reciprocal_link(tmp_path, monkeypatch):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(adr_dir, adr_id="ADR-0001", title="Use Postgres advisory locks")

    _run_cli(
        [
            "adr",
            "new",
            "--title",
            "Use job queue",
            "--status",
            "accepted",
            "--date",
            "2026-05-02",
            "--areas",
            "jobs",
            "--keywords",
            "jobs,queue",
            "--tags",
            "architecture",
            "--related",
            "ADR-0001",
            "--context",
            "Workers need durable handoff.",
            "--decision",
            "Use a job queue.",
            "--alternatives",
            "Direct execution.",
            "--consequences",
            "Jobs can be retried.",
        ],
        monkeypatch,
    )

    first = adr.parse_adr(adr_dir / "0001-use-postgres-advisory-locks.md")
    second = adr.parse_adr(adr_dir / "0002-use-job-queue.md")
    assert first.related == ["ADR-0002"]
    assert second.related == ["ADR-0001"]
    assert adr.validation_errors() == []


def test_new_from_file_rejects_duplicate_id_before_writing(tmp_path, monkeypatch, capsys):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(adr_dir, adr_id="ADR-0001", title="Use Postgres advisory locks")
    draft = tmp_path / "draft.md"
    draft.write_text(
        adr.render_adr_markdown(
            adr_id="ADR-0001",
            title="Use Redis locks",
            status="accepted",
            adr_date="2026-05-02",
            areas=["jobs"],
            supersedes=[],
            superseded_by=[],
            related=[],
            supersession_reason="",
            keywords=["redis"],
            tags=["architecture"],
            context="Workers need coordination.",
            decision="Use Redis locks.",
            alternatives="Postgres advisory locks.",
            consequences="Requires Redis availability.",
        )
    )

    with pytest.raises(SystemExit):
        _run_cli(["adr", "new", "--from-file", str(draft)], monkeypatch)

    err = capsys.readouterr().err
    assert "ADR ID already exists: ADR-0001" in err
    assert (adr_dir / "0001-use-postgres-advisory-locks.md").exists()
    assert not (adr_dir / "0001-use-redis-locks.md").exists()
    assert len(list(adr_dir.glob("*.md"))) == 1


def test_new_from_file_rejects_invalid_draft_before_writing(tmp_path, monkeypatch, capsys):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    draft = tmp_path / "draft.md"
    draft.write_text(
        adr.render_adr_markdown(
            adr_id="ADR-0001",
            title="Use Redis locks",
            status="accepted",
            adr_date="2026-99-99",
            areas=["jobs"],
            supersedes=[],
            superseded_by=[],
            related=[],
            supersession_reason="",
            keywords=["redis"],
            tags=["architecture"],
            context="Workers need coordination.",
            decision="Use Redis locks.",
            alternatives="Postgres advisory locks.",
            consequences="Requires Redis availability.",
        )
    )

    with pytest.raises(SystemExit):
        _run_cli(["adr", "new", "--from-file", str(draft)], monkeypatch)

    err = capsys.readouterr().err
    assert "invalid date '2026-99-99'" in err
    assert not list(adr_dir.glob("*.md"))


def test_new_from_file_rejects_supersedes_without_reason_before_writing(tmp_path, monkeypatch, capsys):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    old_path = _write_adr(adr_dir, adr_id="ADR-0001", title="Use Postgres advisory locks")
    draft = tmp_path / "draft.md"
    draft.write_text(
        adr.render_adr_markdown(
            adr_id="ADR-0002",
            title="Use Redis locks",
            status="accepted",
            adr_date="2026-05-02",
            areas=["jobs"],
            supersedes=["ADR-0001"],
            superseded_by=[],
            related=[],
            supersession_reason="",
            keywords=["redis"],
            tags=["architecture"],
            context="Workers need coordination.",
            decision="Use Redis locks.",
            alternatives="Postgres advisory locks.",
            consequences="Requires Redis availability.",
        )
    )

    with pytest.raises(SystemExit):
        _run_cli(["adr", "new", "--from-file", str(draft)], monkeypatch)

    err = capsys.readouterr().err
    assert "supersession_reason is required when supersedes is set" in err
    assert not (adr_dir / "0002-use-redis-locks.md").exists()
    old_decision = adr.parse_adr(old_path)
    assert old_decision.status == "accepted"
    assert old_decision.superseded_by == []


def test_new_from_file_with_related_adds_reciprocal_link(tmp_path, monkeypatch):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(adr_dir, adr_id="ADR-0001", title="Use Postgres advisory locks")
    draft = tmp_path / "draft.md"
    draft.write_text(
        adr.render_adr_markdown(
            adr_id="ADR-0002",
            title="Use job queue",
            status="accepted",
            adr_date="2026-05-02",
            areas=["jobs"],
            supersedes=[],
            superseded_by=[],
            related=["ADR-0001"],
            supersession_reason="",
            keywords=["jobs", "queue"],
            tags=["architecture"],
            context="Workers need durable handoff.",
            decision="Use a job queue.",
            alternatives="Direct execution.",
            consequences="Jobs can be retried.",
        )
    )

    _run_cli(["adr", "new", "--from-file", str(draft)], monkeypatch)

    first = adr.parse_adr(adr_dir / "0001-use-postgres-advisory-locks.md")
    second = adr.parse_adr(adr_dir / "0002-use-job-queue.md")
    assert first.related == ["ADR-0002"]
    assert second.related == ["ADR-0001"]
    assert adr.validation_errors() == []


def test_status_detects_stale_index(tmp_path, monkeypatch):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    path = _write_adr(adr_dir)
    adr.rebuild_index()

    path.write_text(path.read_text().replace("Workers need coordination.", "Workers need strict coordination."))

    issues = adr.status_issues()
    assert any("markdown changed after indexed JSON" in issue for issue in issues)


def test_validate_reports_broken_link_and_missing_reason(tmp_path, monkeypatch):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(
        adr_dir,
        adr_id="ADR-0001",
        title="Use Postgres advisory locks",
        supersedes=["ADR-9999"],
        supersession_reason="",
    )

    errors = adr.validation_errors()

    assert any("linked ADR does not exist: ADR-9999" in error for error in errors)
    assert any("supersession_reason is required" in error for error in errors)


def test_validate_reports_stale_superseded_status(tmp_path, monkeypatch):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(
        adr_dir,
        adr_id="ADR-0001",
        title="Use Redis locks",
        status="accepted",
        superseded_by=["ADR-0002"],
    )
    _write_adr(
        adr_dir,
        adr_id="ADR-0002",
        title="Use Postgres advisory locks",
        supersedes=["ADR-0001"],
        supersession_reason="Redis locks created unsafe ownership behavior during deploys.",
    )

    errors = adr.validation_errors()

    assert any("ADR with superseded_by must have status superseded" in error for error in errors)


def test_validate_reports_self_related_link(tmp_path, monkeypatch):
    adr_dir, _ = _patch_project(tmp_path, monkeypatch)
    _write_adr(
        adr_dir,
        adr_id="ADR-0001",
        title="Use Postgres advisory locks",
        related=["ADR-0001"],
    )

    errors = adr.validation_errors()

    assert any("ADR cannot be related to itself" in error for error in errors)


def test_installer_scaffolding_includes_adr_dirs_and_skill_templates():
    scaffold = Path("installer/lib/scaffold.js").read_text()
    doctor = Path("installer/lib/doctor.js").read_text()

    assert "'adr'" in scaffold
    assert "'decisions'" in scaffold
    assert "expectedDirPaths" in doctor
    assert Path("installer/templates/skills/king-decisions/skill.md").exists()
    assert Path("installer/templates/skills/king-record-decision/skill.md").exists()
