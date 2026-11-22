from __future__ import annotations

import json
import hashlib
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.config import get_settings
from app.errors import ConflictError, InputError, NotFoundError
from app.schemas import (
    ApplicationProjectResponse,
    BackgroundInstanceResponse,
    DraftReview,
    EssayOutline,
    EssayProjectArtifactVersion,
    EssayProjectResponse,
    PersonResponse,
    ProfileData,
    ProfilePatchOperation,
    ProgramAnalysis,
    ProgramContext,
    StoryCards,
    StoryInstanceResponse,
    StoryMessage,
    WorkspaceSnapshotResponse,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(value: str) -> str:
    return "".join(character.casefold() for character in value if not character.isspace())


def _dump(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in value
        ]
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _ensure_item_ids(profile: ProfileData) -> ProfileData:
    normalized = profile.model_copy(deep=True)
    for items in (
        normalized.research_experiences,
        normalized.internships,
        normalized.projects,
    ):
        for item in items:
            if not item.id:
                item.id = str(uuid.uuid4())
    for item in normalized.activities_awards:
        if not item.id:
            item.id = str(uuid.uuid4())
    return normalized


class DomainStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS persons (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_persons_owner_updated
                ON persons(owner_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS person_aliases (
                    id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                    UNIQUE(person_id, normalized_alias),
                    FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_person_aliases_normalized
                ON person_aliases(normalized_alias);

                CREATE TABLE IF NOT EXISTS backgrounds (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    person_id TEXT NOT NULL,
                    resume_name TEXT NOT NULL,
                    normalized_resume_name TEXT NOT NULL,
                    source_filename TEXT NOT NULL DEFAULT '',
                    source_path TEXT NOT NULL DEFAULT '',
                    source_sha256 TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    current_version_no INTEGER NOT NULL,
                    legacy_profile_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(owner_id, person_id, normalized_resume_name),
                    UNIQUE(owner_id, legacy_profile_id),
                    FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_backgrounds_owner_person
                ON backgrounds(owner_id, person_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS background_versions (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    background_id TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    profile_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(background_id, version_no),
                    FOREIGN KEY(background_id) REFERENCES backgrounds(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_background_versions_owner_background
                ON background_versions(owner_id, background_id, version_no DESC);

                CREATE TABLE IF NOT EXISTS application_projects (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    person_id TEXT NOT NULL,
                    background_id TEXT NOT NULL,
                    school_name TEXT NOT NULL,
                    normalized_school_name TEXT NOT NULL,
                    program_name TEXT NOT NULL,
                    normalized_program_name TEXT NOT NULL,
                    program_details TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(
                        owner_id, background_id, normalized_school_name,
                        normalized_program_name
                    ),
                    FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE,
                    FOREIGN KEY(background_id) REFERENCES backgrounds(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_application_projects_owner_background
                ON application_projects(owner_id, background_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS stories (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    background_id TEXT NOT NULL,
                    application_project_id TEXT,
                    legacy_session_id TEXT,
                    title TEXT NOT NULL,
                    normalized_title TEXT NOT NULL,
                    focus TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    current_version_no INTEGER NOT NULL,
                    round_no INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(owner_id, background_id, normalized_title),
                    FOREIGN KEY(background_id) REFERENCES backgrounds(id) ON DELETE CASCADE,
                    FOREIGN KEY(application_project_id)
                        REFERENCES application_projects(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_stories_owner_background
                ON stories(owner_id, background_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS story_versions (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    story_id TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    messages_json TEXT NOT NULL,
                    cards_json TEXT NOT NULL,
                    round_no INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(story_id, version_no),
                    FOREIGN KEY(story_id) REFERENCES stories(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_story_versions_owner_story
                ON story_versions(owner_id, story_id, version_no DESC);

                CREATE TABLE IF NOT EXISTS essay_projects (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    person_id TEXT NOT NULL,
                    background_id TEXT NOT NULL,
                    application_project_id TEXT,
                    legacy_session_id TEXT,
                    story_ids_json TEXT NOT NULL,
                    program_json TEXT NOT NULL,
                    analysis_json TEXT,
                    outline_json TEXT,
                    draft TEXT,
                    review_json TEXT,
                    status TEXT NOT NULL,
                    current_step TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE,
                    FOREIGN KEY(background_id) REFERENCES backgrounds(id) ON DELETE CASCADE,
                    FOREIGN KEY(application_project_id)
                        REFERENCES application_projects(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_essay_projects_owner_updated
                ON essay_projects(owner_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS project_artifacts (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, artifact_type, version_no),
                    FOREIGN KEY(project_id) REFERENCES essay_projects(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_project_artifacts_owner_project
                ON project_artifacts(owner_id, project_id, created_at DESC);
                """
            )
            self._ensure_column(
                connection,
                "backgrounds",
                "source_path",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "backgrounds",
                "source_sha256",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "stories",
                "legacy_session_id",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "stories",
                "application_project_id",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "essay_projects",
                "legacy_session_id",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "essay_projects",
                "application_project_id",
                "TEXT",
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def healthcheck(self) -> None:
        with self._connection() as connection:
            connection.execute("SELECT 1").fetchone()

    def create_person(
        self,
        owner_id: str,
        display_name: str,
        aliases: Optional[Sequence[str]] = None,
    ) -> PersonResponse:
        cleaned_name = display_name.strip()
        if not cleaned_name:
            raise ConflictError("Person name is required")
        person_id = str(uuid.uuid4())
        now = _now()
        normalized_aliases = {
            _normalize(alias)
            for alias in [cleaned_name, *(aliases or [])]
            if alias.strip()
        }
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO persons(id, owner_id, display_name, normalized_name, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    person_id,
                    owner_id,
                    cleaned_name,
                    _normalize(cleaned_name),
                    now,
                    now,
                ),
            )
            for alias in normalized_aliases:
                display_alias = next(
                    (
                        item.strip()
                        for item in [cleaned_name, *(aliases or [])]
                        if _normalize(item) == alias
                    ),
                    alias,
                )
                connection.execute(
                    "INSERT INTO person_aliases(id, person_id, alias, normalized_alias) "
                    "VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), person_id, display_alias, alias),
                )
        return self.get_person(owner_id, person_id)

    def get_person(self, owner_id: str, person_id: str) -> PersonResponse:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM persons WHERE id = ? AND owner_id = ?",
                (person_id, owner_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Person not found")
            aliases = [
                item["alias"]
                for item in connection.execute(
                    "SELECT alias FROM person_aliases WHERE person_id = ? ORDER BY alias",
                    (person_id,),
                ).fetchall()
            ]
            background_count = connection.execute(
                "SELECT COUNT(*) AS count FROM backgrounds "
                "WHERE person_id = ? AND owner_id = ? AND status != 'archived'",
                (person_id, owner_id),
            ).fetchone()["count"]
            story_count = connection.execute(
                "SELECT COUNT(*) AS count FROM stories s "
                "JOIN backgrounds b ON b.id = s.background_id "
                "WHERE b.person_id = ? AND s.owner_id = ? AND s.status != 'archived'",
                (person_id, owner_id),
            ).fetchone()["count"]
        return PersonResponse(
            id=row["id"],
            display_name=row["display_name"],
            aliases=aliases,
            background_count=background_count,
            story_count=story_count,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_persons(self, owner_id: str) -> List[PersonResponse]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id FROM persons WHERE owner_id = ? ORDER BY updated_at DESC",
                (owner_id,),
            ).fetchall()
        return [self.get_person(owner_id, row["id"]) for row in rows]

    def resolve_persons(self, owner_id: str, query: str) -> List[PersonResponse]:
        normalized = _normalize(query)
        if not normalized:
            return []
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT p.id
                FROM persons p
                LEFT JOIN person_aliases a ON a.person_id = p.id
                WHERE p.owner_id = ?
                  AND (p.normalized_name = ? OR a.normalized_alias = ?)
                ORDER BY p.updated_at DESC
                """,
                (owner_id, normalized, normalized),
            ).fetchall()
            if not rows:
                rows = connection.execute(
                    """
                    SELECT DISTINCT p.id
                    FROM persons p
                    LEFT JOIN person_aliases a ON a.person_id = p.id
                    WHERE p.owner_id = ?
                      AND (p.normalized_name LIKE ? OR a.normalized_alias LIKE ?)
                    ORDER BY p.updated_at DESC
                    LIMIT 10
                    """,
                    (owner_id, f"%{normalized}%", f"%{normalized}%"),
                ).fetchall()
        return [self.get_person(owner_id, row["id"]) for row in rows]

    def create_background(
        self,
        owner_id: str,
        person_id: str,
        resume_name: str,
        profile: ProfileData,
        *,
        source_filename: str = "",
        legacy_profile_id: Optional[str] = None,
        status: str = "extracted",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BackgroundInstanceResponse:
        self.get_person(owner_id, person_id)
        cleaned_name = resume_name.strip() or "Default resume"
        normalized_name = _normalize(cleaned_name)
        profile = _ensure_item_ids(profile)
        background_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        now = _now()
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT id FROM backgrounds WHERE owner_id = ? AND person_id = ? "
                "AND normalized_resume_name = ?",
                (owner_id, person_id, normalized_name),
            ).fetchone()
            if existing is not None:
                raise ConflictError("This person already has a resume with that name")
            connection.execute(
                """
                INSERT INTO backgrounds(
                    id, owner_id, person_id, resume_name, normalized_resume_name,
                    source_filename, status, current_version_no, legacy_profile_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    background_id,
                    owner_id,
                    person_id,
                    cleaned_name,
                    normalized_name,
                    source_filename,
                    status,
                    legacy_profile_id,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO background_versions(
                    id, owner_id, background_id, version_no, profile_json,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    version_id,
                    owner_id,
                    background_id,
                    _dump(profile),
                    _dump(metadata or {}),
                    now,
                ),
            )
        return self.get_background(owner_id, background_id)

    def get_background(
        self, owner_id: str, background_id: str
    ) -> BackgroundInstanceResponse:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM backgrounds WHERE id = ? AND owner_id = ?",
                (background_id, owner_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Background instance not found")
            version = connection.execute(
                "SELECT profile_json FROM background_versions "
                "WHERE owner_id = ? AND background_id = ? AND version_no = ?",
                (owner_id, background_id, row["current_version_no"]),
            ).fetchone()
            if version is None:
                raise NotFoundError("Background version not found")
        return BackgroundInstanceResponse(
            id=row["id"],
            person_id=row["person_id"],
            resume_name=row["resume_name"],
            source_filename=row["source_filename"],
            source_sha256=row["source_sha256"],
            status=row["status"],
            version=row["current_version_no"],
            profile=ProfileData.model_validate_json(version["profile_json"]),
            legacy_profile_id=row["legacy_profile_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_backgrounds(
        self, owner_id: str, person_id: Optional[str] = None
    ) -> List[BackgroundInstanceResponse]:
        with self._connection() as connection:
            if person_id:
                rows = connection.execute(
                    "SELECT id FROM backgrounds WHERE owner_id = ? AND person_id = ? "
                    "AND status != 'archived' ORDER BY updated_at DESC",
                    (owner_id, person_id),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id FROM backgrounds WHERE owner_id = ? AND status != 'archived' "
                    "ORDER BY updated_at DESC",
                    (owner_id,),
                ).fetchall()
        return [self.get_background(owner_id, row["id"]) for row in rows]

    def resolve_backgrounds(
        self,
        owner_id: str,
        query: str,
        *,
        person_id: Optional[str] = None,
    ) -> List[BackgroundInstanceResponse]:
        normalized = _normalize(query)
        if not normalized:
            return self.list_backgrounds(owner_id, person_id)
        clauses = ["owner_id = ?", "status != 'archived'", "normalized_resume_name = ?"]
        params: List[Any] = [owner_id, normalized]
        if person_id:
            clauses.append("person_id = ?")
            params.append(person_id)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT id FROM backgrounds WHERE {' AND '.join(clauses)} "
                "ORDER BY updated_at DESC",
                tuple(params),
            ).fetchall()
            if not rows:
                clauses[-1] = "normalized_resume_name LIKE ?"
                params[-1] = f"%{normalized}%"
                rows = connection.execute(
                    f"SELECT id FROM backgrounds WHERE {' AND '.join(clauses)} "
                    "ORDER BY updated_at DESC LIMIT 10",
                    tuple(params),
                ).fetchall()
        return [self.get_background(owner_id, row["id"]) for row in rows]

    def ensure_background_for_profile(
        self,
        owner_id: str,
        profile_id: str,
        profile: ProfileData,
        *,
        person_id: Optional[str] = None,
        resume_name: Optional[str] = None,
        source_filename: str = "",
    ) -> BackgroundInstanceResponse:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id FROM backgrounds WHERE owner_id = ? AND legacy_profile_id = ?",
                (owner_id, profile_id),
            ).fetchone()
        if row is not None:
            return self.get_background(owner_id, row["id"])

        if not person_id:
            latest = self.list_backgrounds(owner_id)
            matching_person_ids = {
                item.person_id
                for item in latest
                if item.profile.basic_profile.full_name.strip()
                == profile.basic_profile.full_name.strip()
            }
            matching_person = (
                next(iter(matching_person_ids))
                if len(matching_person_ids) == 1
                else None
            )
            person_id = matching_person or self.create_person(
                owner_id,
                profile.basic_profile.full_name.strip() or "Unnamed applicant",
            ).id

        label = resume_name.strip() if resume_name and resume_name.strip() else "Default resume"
        try:
            return self.create_background(
                owner_id,
                person_id,
                label,
                profile,
                source_filename=source_filename,
                legacy_profile_id=profile_id,
            )
        except ConflictError:
            numbered_label = f"{label} {profile_id[:6]}"
            return self.create_background(
                owner_id,
                person_id,
                numbered_label,
                profile,
                source_filename=source_filename,
                legacy_profile_id=profile_id,
            )

    def rename_background(
        self, owner_id: str, background_id: str, resume_name: str
    ) -> BackgroundInstanceResponse:
        background = self.get_background(owner_id, background_id)
        cleaned = resume_name.strip()
        if not cleaned:
            raise ConflictError("Resume name is required")
        try:
            with self._connection() as connection:
                connection.execute(
                    "UPDATE backgrounds SET resume_name = ?, normalized_resume_name = ?, "
                    "updated_at = ? WHERE id = ? AND owner_id = ?",
                    (
                        cleaned,
                        _normalize(cleaned),
                        _now(),
                        background.id,
                        owner_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("This person already has a resume with that name") from exc
        return self.get_background(owner_id, background.id)

    def save_resume_file(
        self,
        owner_id: str,
        background_id: str,
        filename: str,
        content: bytes,
    ) -> BackgroundInstanceResponse:
        background = self.get_background(owner_id, background_id)
        if not content:
            raise InputError("A non-empty resume file is required")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".txt", ".md", ".pdf", ".docx"}:
            raise InputError("Unsupported resume file type")
        owner_key = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:24]
        resume_dir = (self.path.parent / "resumes" / owner_key).resolve()
        resume_root = (self.path.parent / "resumes").resolve()
        if resume_root not in resume_dir.parents:
            raise InputError("Invalid resume storage path")
        resume_dir.mkdir(parents=True, exist_ok=True)
        target = (resume_dir / f"{background.id}{suffix}").resolve()
        if target.parent != resume_dir:
            raise InputError("Invalid resume file path")
        target.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        with self._connection() as connection:
            connection.execute(
                "UPDATE backgrounds SET source_filename = ?, source_path = ?, "
                "source_sha256 = ?, updated_at = ? "
                "WHERE id = ? AND owner_id = ?",
                (
                    Path(filename).name,
                    str(target),
                    digest,
                    _now(),
                    background.id,
                    owner_id,
                ),
            )
        return self.get_background(owner_id, background.id)

    def get_resume_file(
        self,
        owner_id: str,
        background_id: str,
    ) -> tuple[Path, str]:
        background = self.get_background(owner_id, background_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT source_path, source_filename FROM backgrounds "
                "WHERE id = ? AND owner_id = ?",
                (background_id, owner_id),
            ).fetchone()
        if row is None or not row["source_path"]:
            raise NotFoundError("Resume file not found")
        path = Path(row["source_path"]).resolve()
        if not path.is_file():
            raise NotFoundError("Resume file not found")
        return path, row["source_filename"] or path.name

    def save_background_profile(
        self,
        owner_id: str,
        background_id: str,
        profile: ProfileData,
        *,
        status: str = "extracted",
        metadata: Optional[Dict[str, Any]] = None,
        legacy_profile_id: Optional[str] = None,
    ) -> BackgroundInstanceResponse:
        current = self.get_background(owner_id, background_id)
        profile = _ensure_item_ids(profile)
        now = _now()
        next_version = current.version + 1
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO background_versions(
                    id, owner_id, background_id, version_no, profile_json,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    owner_id,
                    background_id,
                    next_version,
                    _dump(profile),
                    _dump(metadata or {}),
                    now,
                ),
            )
            connection.execute(
                "UPDATE backgrounds SET status = ?, current_version_no = ?, "
                "legacy_profile_id = COALESCE(?, legacy_profile_id), updated_at = ? "
                "WHERE id = ? AND owner_id = ?",
                (
                    status,
                    next_version,
                    legacy_profile_id,
                    now,
                    background_id,
                    owner_id,
                ),
            )
            connection.execute(
                "UPDATE essay_projects SET status = 'stale', current_step = 'analysis', "
                "analysis_json = NULL, outline_json = NULL, draft = NULL, "
                "review_json = NULL, updated_at = ? "
                "WHERE owner_id = ? AND background_id = ?",
                (now, owner_id, background_id),
            )
        return self.get_background(owner_id, background_id)

    def patch_background(
        self,
        owner_id: str,
        background_id: str,
        operations: Sequence[ProfilePatchOperation],
        *,
        base_version: Optional[int] = None,
    ) -> BackgroundInstanceResponse:
        current = self.get_background(owner_id, background_id)
        if base_version is not None and base_version != current.version:
            raise ConflictError(
                "The background instance changed while this edit was being prepared"
            )
        payload = current.profile.model_dump(mode="json")
        collections = {
            "research_experiences",
            "internships",
            "projects",
            "activities_awards",
            "top_strengths",
            "suggested_focus_experiences",
        }

        for operation in operations:
            path = operation.path.strip()
            parts = [part for part in path.split(".") if part]
            if not parts:
                raise InputError("Profile patch path is empty")
            collection = parts[0]
            if collection in collections:
                self._apply_collection_operation(payload, collection, operation)
                continue
            if parts[0] == "basic_profile" and len(parts) == 2:
                target = payload["basic_profile"]
                field = parts[1]
                if field not in target:
                    raise InputError(f"Unknown profile field: {path}")
                target[field] = self._patched_value(
                    operation,
                    target[field],
                )
                continue
            if len(parts) == 1 and parts[0] in payload:
                payload[parts[0]] = self._patched_value(
                    operation,
                    payload[parts[0]],
                )
                continue
            raise InputError(f"Unknown or unsupported profile path: {path}")

        profile = _ensure_item_ids(ProfileData.model_validate(payload))
        return self.save_background_profile(
            owner_id,
            background_id,
            profile,
            status="extracted",
            metadata={"source": "voice_or_manual_patch"},
        )

    @staticmethod
    def _patched_value(operation: ProfilePatchOperation, current: Any) -> Any:
        if operation.op == "set":
            return operation.value
        if operation.op == "append":
            if not isinstance(current, list):
                raise InputError("Append is only supported for list fields")
            return [*current, operation.value]
        if operation.op == "remove":
            if not isinstance(current, list):
                raise InputError("Remove is only supported for list fields")
            if operation.item_id:
                return [
                    item
                    for item in current
                    if not (
                        isinstance(item, dict)
                        and item.get("id") == operation.item_id
                    )
                    and item != operation.value
                ]
            if operation.index is not None:
                if operation.index >= len(current):
                    raise InputError("List index is out of range")
                return [item for index, item in enumerate(current) if index != operation.index]
            if operation.value is not None:
                return [item for item in current if item != operation.value]
            raise InputError("Remove requires item_id, index, or value")
        if operation.op == "clear":
            return [] if isinstance(current, list) else ""
        raise InputError("Unsupported profile patch operation")

    def _apply_collection_operation(
        self,
        payload: Dict[str, Any],
        collection: str,
        operation: ProfilePatchOperation,
    ) -> None:
        current = payload.get(collection)
        if not isinstance(current, list):
            raise InputError(f"Profile collection is invalid: {collection}")
        parts = [part for part in operation.path.split(".") if part]
        if len(parts) == 1:
            payload[collection] = self._patched_value(operation, current)
            return
        item_id = operation.item_id
        field = parts[1]
        if not item_id:
            raise InputError(f"item_id is required for {operation.path}")
        for item in current:
            if isinstance(item, dict) and item.get("id") == item_id:
                if field not in item:
                    raise InputError(f"Unknown collection field: {operation.path}")
                item[field] = self._patched_value(operation, item[field])
                return
        raise InputError(f"Collection item not found: {item_id}")

    def create_application_project(
        self,
        owner_id: str,
        background_id: str,
        school_name: str,
        program_name: str,
        program_details: str = "",
    ) -> ApplicationProjectResponse:
        background = self.get_background(owner_id, background_id)
        project_id = str(uuid.uuid4())
        now = _now()
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO application_projects(
                        id, owner_id, person_id, background_id, school_name,
                        normalized_school_name, program_name, normalized_program_name,
                        program_details, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        project_id,
                        owner_id,
                        background.person_id,
                        background.id,
                        school_name.strip(),
                        _normalize(school_name),
                        program_name.strip(),
                        _normalize(program_name),
                        program_details.strip(),
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(
                "This background already has the same school and program project"
            ) from exc
        return self.get_application_project(owner_id, project_id)

    def get_application_project(
        self,
        owner_id: str,
        project_id: str,
    ) -> ApplicationProjectResponse:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM application_projects WHERE id = ? AND owner_id = ?",
                (project_id, owner_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Application project not found")
            story_count = connection.execute(
                "SELECT COUNT(*) AS count FROM stories WHERE owner_id = ? "
                "AND application_project_id = ? AND status != 'archived'",
                (owner_id, project_id),
            ).fetchone()["count"]
            essay_count = connection.execute(
                "SELECT COUNT(*) AS count FROM essay_projects WHERE owner_id = ? "
                "AND application_project_id = ? AND status != 'archived'",
                (owner_id, project_id),
            ).fetchone()["count"]
        return ApplicationProjectResponse(
            id=row["id"],
            background_instance_id=row["background_id"],
            person_id=row["person_id"],
            school_name=row["school_name"],
            program_name=row["program_name"],
            program_details=row["program_details"],
            status=row["status"],
            story_count=story_count,
            essay_count=essay_count,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_application_projects(
        self,
        owner_id: str,
        background_id: Optional[str] = None,
    ) -> List[ApplicationProjectResponse]:
        with self._connection() as connection:
            if background_id:
                rows = connection.execute(
                    "SELECT id FROM application_projects WHERE owner_id = ? "
                    "AND background_id = ? AND status != 'archived' "
                    "ORDER BY updated_at DESC",
                    (owner_id, background_id),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id FROM application_projects WHERE owner_id = ? "
                    "AND status != 'archived' ORDER BY updated_at DESC",
                    (owner_id,),
                ).fetchall()
        return [self.get_application_project(owner_id, row["id"]) for row in rows]

    def resolve_application_projects(
        self,
        owner_id: str,
        query: str = "",
        *,
        background_id: Optional[str] = None,
    ) -> List[ApplicationProjectResponse]:
        projects = self.list_application_projects(owner_id, background_id)
        normalized = _normalize(query)
        if not normalized:
            return projects
        return [
            project
            for project in projects
            if normalized
            in _normalize(f"{project.school_name} {project.program_name}")
        ][:10]

    def patch_application_project(
        self,
        owner_id: str,
        project_id: str,
        *,
        school_name: Optional[str] = None,
        program_name: Optional[str] = None,
        program_details: Optional[str] = None,
    ) -> ApplicationProjectResponse:
        current = self.get_application_project(owner_id, project_id)
        school = school_name.strip() if school_name is not None else current.school_name
        program = program_name.strip() if program_name is not None else current.program_name
        details = (
            program_details.strip()
            if program_details is not None
            else current.program_details
        )
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    UPDATE application_projects
                    SET school_name = ?, normalized_school_name = ?,
                        program_name = ?, normalized_program_name = ?,
                        program_details = ?, updated_at = ?
                    WHERE id = ? AND owner_id = ?
                    """,
                    (
                        school,
                        _normalize(school),
                        program,
                        _normalize(program),
                        details,
                        _now(),
                        project_id,
                        owner_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(
                "This background already has the same school and program project"
            ) from exc
        return self.get_application_project(owner_id, project_id)

    def create_story(
        self,
        owner_id: str,
        background_id: str,
        title: str,
        *,
        application_project_id: Optional[str] = None,
        focus: str = "",
        messages: Optional[List[StoryMessage]] = None,
        cards: Optional[StoryCards] = None,
        round_no: int = 1,
        status: str = "interviewing",
    ) -> StoryInstanceResponse:
        background = self.get_background(owner_id, background_id)
        if application_project_id:
            application_project = self.get_application_project(
                owner_id,
                application_project_id,
            )
            if application_project.background_instance_id != background.id:
                raise ConflictError(
                    "Application project does not belong to the selected background"
                )
        cleaned_title = title.strip() or "Story"
        normalized_title = _normalize(cleaned_title)
        if application_project_id:
            normalized_title = f"{application_project_id}:{normalized_title}"
        story_id = str(uuid.uuid4())
        now = _now()
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT id FROM stories WHERE owner_id = ? AND background_id = ? "
                "AND normalized_title = ?",
                (owner_id, background.id, normalized_title),
            ).fetchone()
            if existing is not None:
                raise ConflictError("This background already has a story with that name")
            connection.execute(
                """
                INSERT INTO stories(
                    id, owner_id, background_id, application_project_id, title,
                    normalized_title, focus,
                    status, current_version_no, round_no, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    story_id,
                    owner_id,
                    background.id,
                    application_project_id,
                    cleaned_title,
                    normalized_title,
                    focus.strip(),
                    status,
                    round_no,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO story_versions(
                    id, owner_id, story_id, version_no, messages_json, cards_json,
                    round_no, status, created_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    owner_id,
                    story_id,
                    _dump(messages or []),
                    _dump(cards or StoryCards()),
                    round_no,
                    status,
                    now,
                ),
            )
        return self.get_story(owner_id, story_id)

    def get_story(self, owner_id: str, story_id: str) -> StoryInstanceResponse:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM stories WHERE id = ? AND owner_id = ?",
                (story_id, owner_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Story instance not found")
            version = connection.execute(
                "SELECT * FROM story_versions WHERE owner_id = ? AND story_id = ? "
                "AND version_no = ?",
                (owner_id, story_id, row["current_version_no"]),
            ).fetchone()
            if version is None:
                raise NotFoundError("Story version not found")
        return StoryInstanceResponse(
            id=row["id"],
            background_instance_id=row["background_id"],
            application_project_id=row["application_project_id"],
            title=row["title"],
            focus=row["focus"],
            status=row["status"],
            round_no=row["round_no"],
            cards=StoryCards.model_validate_json(version["cards_json"]),
            messages=[
                StoryMessage.model_validate(item)
                for item in _load_json(version["messages_json"], [])
            ],
            version=row["current_version_no"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_stories(
        self,
        owner_id: str,
        background_id: Optional[str] = None,
        application_project_id: Optional[str] = None,
    ) -> List[StoryInstanceResponse]:
        with self._connection() as connection:
            if background_id and application_project_id:
                rows = connection.execute(
                    "SELECT id FROM stories WHERE owner_id = ? AND background_id = ? "
                    "AND application_project_id = ? AND status != 'archived' "
                    "ORDER BY updated_at DESC",
                    (owner_id, background_id, application_project_id),
                ).fetchall()
            elif background_id:
                rows = connection.execute(
                    "SELECT id FROM stories WHERE owner_id = ? AND background_id = ? "
                    "AND status != 'archived' ORDER BY updated_at DESC",
                    (owner_id, background_id),
                ).fetchall()
            elif application_project_id:
                rows = connection.execute(
                    "SELECT id FROM stories WHERE owner_id = ? "
                    "AND application_project_id = ? AND status != 'archived' "
                    "ORDER BY updated_at DESC",
                    (owner_id, application_project_id),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id FROM stories WHERE owner_id = ? AND status != 'archived' "
                    "ORDER BY updated_at DESC",
                    (owner_id,),
                ).fetchall()
        return [self.get_story(owner_id, row["id"]) for row in rows]

    def resolve_stories(
        self,
        owner_id: str,
        query: str,
        *,
        background_id: Optional[str] = None,
        application_project_id: Optional[str] = None,
    ) -> List[StoryInstanceResponse]:
        normalized = _normalize(query)
        if not normalized:
            return self.list_stories(
                owner_id,
                background_id,
                application_project_id,
            )
        clauses = ["owner_id = ?", "status != 'archived'", "normalized_title = ?"]
        params: List[Any] = [
            owner_id,
            (
                f"{application_project_id}:{normalized}"
                if application_project_id
                else normalized
            ),
        ]
        if background_id:
            clauses.append("background_id = ?")
            params.append(background_id)
        if application_project_id:
            clauses.append("application_project_id = ?")
            params.append(application_project_id)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT id FROM stories WHERE {' AND '.join(clauses)} "
                "ORDER BY updated_at DESC",
                tuple(params),
            ).fetchall()
            if not rows:
                clauses[-1] = "normalized_title LIKE ?"
                params[-1] = f"%{normalized}%"
                rows = connection.execute(
                    f"SELECT id FROM stories WHERE {' AND '.join(clauses)} "
                    "ORDER BY updated_at DESC LIMIT 10",
                    tuple(params),
                ).fetchall()
        return [self.get_story(owner_id, row["id"]) for row in rows]

    def save_story_state(
        self,
        owner_id: str,
        story_id: str,
        *,
        messages: List[StoryMessage],
        cards: StoryCards,
        round_no: int,
        status: str,
    ) -> StoryInstanceResponse:
        current = self.get_story(owner_id, story_id)
        next_version = current.version + 1
        now = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO story_versions(
                    id, owner_id, story_id, version_no, messages_json, cards_json,
                    round_no, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    owner_id,
                    story_id,
                    next_version,
                    _dump(messages),
                    _dump(cards),
                    round_no,
                    status,
                    now,
                ),
            )
            connection.execute(
                "UPDATE stories SET status = ?, current_version_no = ?, round_no = ?, "
                "updated_at = ? WHERE id = ? AND owner_id = ?",
                (status, next_version, round_no, now, story_id, owner_id),
            )
        return self.get_story(owner_id, story_id)

    def patch_story_cards(
        self,
        owner_id: str,
        story_id: str,
        cards: StoryCards,
        *,
        base_version: Optional[int] = None,
    ) -> StoryInstanceResponse:
        current = self.get_story(owner_id, story_id)
        if base_version is not None and base_version != current.version:
            raise ConflictError(
                "The story changed while this edit was being prepared"
            )
        updated = self.save_story_state(
            owner_id,
            story_id,
            messages=current.messages,
            cards=cards,
            round_no=current.round_no,
            status=current.status,
        )
        self._invalidate_projects_for_story(owner_id, story_id)
        return updated

    def _invalidate_projects_for_story(self, owner_id: str, story_id: str) -> None:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, story_ids_json FROM essay_projects WHERE owner_id = ? "
                "AND status != 'archived'",
                (owner_id,),
            ).fetchall()
            affected = [
                row["id"]
                for row in rows
                if story_id in _load_json(row["story_ids_json"], [])
            ]
            for project_id in affected:
                connection.execute(
                    """
                    UPDATE essay_projects
                    SET status = 'stale', current_step = 'analysis',
                        analysis_json = NULL, outline_json = NULL, draft = NULL,
                        review_json = NULL, updated_at = ?
                    WHERE id = ? AND owner_id = ?
                    """,
                    (_now(), project_id, owner_id),
                )

    def create_project(
        self,
        owner_id: str,
        background_id: str,
        story_ids: Sequence[str],
        program: ProgramContext,
        *,
        application_project_id: Optional[str] = None,
    ) -> EssayProjectResponse:
        background = self.get_background(owner_id, background_id)
        if application_project_id:
            application_project = self.get_application_project(
                owner_id,
                application_project_id,
            )
            if application_project.background_instance_id != background.id:
                raise ConflictError(
                    "Application project does not belong to the selected background"
                )
        unique_story_ids = list(dict.fromkeys(story_ids))
        for story_id in unique_story_ids:
            story = self.get_story(owner_id, story_id)
            if story.background_instance_id != background.id:
                raise ConflictError("Story does not belong to the selected background")
            if story.status != "ready":
                raise ConflictError("Only completed stories can be used in a project")
            if (
                application_project_id
                and story.application_project_id != application_project_id
            ):
                raise ConflictError(
                    "Selected story does not belong to the application project"
                )
        project_id = str(uuid.uuid4())
        now = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO essay_projects(
                    id, owner_id, person_id, background_id,
                    application_project_id, story_ids_json,
                    program_json, analysis_json, outline_json, draft, review_json,
                    status, current_step, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, 'created', 'created', ?, ?)
                """,
                (
                    project_id,
                    owner_id,
                    background.person_id,
                    background.id,
                    application_project_id,
                    _dump(unique_story_ids),
                    _dump(program),
                    now,
                    now,
                ),
            )
        return self.get_project(owner_id, project_id)

    def save_project(
        self,
        owner_id: str,
        project_id: str,
        *,
        analysis: Optional[ProgramAnalysis] = None,
        outline: Optional[EssayOutline] = None,
        draft: Optional[str] = None,
        review: Optional[DraftReview] = None,
        status: str,
        current_step: str,
    ) -> EssayProjectResponse:
        self.get_project(owner_id, project_id)
        with self._connection() as connection:
            updated = connection.execute(
                """
                UPDATE essay_projects
                SET analysis_json = ?, outline_json = ?, draft = ?, review_json = ?,
                    status = ?, current_step = ?, updated_at = ?
                WHERE id = ? AND owner_id = ?
                """,
                (
                    _dump(analysis) if analysis else None,
                    _dump(outline) if outline else None,
                    draft,
                    _dump(review) if review else None,
                    status,
                    current_step,
                    _now(),
                    project_id,
                    owner_id,
                ),
            ).rowcount
        if not updated:
            raise NotFoundError("Essay project not found")
        return self.get_project(owner_id, project_id)

    def patch_project(
        self,
        owner_id: str,
        project_id: str,
        *,
        changes: Dict[str, Any],
        story_instance_ids: Optional[List[str]] = None,
    ) -> EssayProjectResponse:
        current = self.get_project(owner_id, project_id)
        program_payload = current.program.model_dump(mode="json")
        applied_change = False
        for key, value in changes.items():
            if key in program_payload and value is not None:
                program_payload[key] = value
                applied_change = True
        if not applied_change and story_instance_ids is None:
            raise InputError("No supported essay project changes were supplied")
        program = ProgramContext.model_validate(program_payload)
        next_story_ids = current.story_instance_ids
        if story_instance_ids is not None:
            next_story_ids = list(dict.fromkeys(story_instance_ids))
            for story_id in next_story_ids:
                story = self.get_story(owner_id, story_id)
                if story.background_instance_id != current.background_instance_id:
                    raise ConflictError(
                        "Every selected story must belong to the project background"
                    )
                if story.status != "ready":
                    raise ConflictError(
                        "Only completed stories can be used in a project"
                    )
                if (
                    current.application_project_id
                    and story.application_project_id
                    != current.application_project_id
                ):
                    raise ConflictError(
                        "Selected story does not belong to the application project"
                    )
        with self._connection() as connection:
            updated = connection.execute(
                """
                UPDATE essay_projects
                SET story_ids_json = ?, program_json = ?, analysis_json = NULL,
                    outline_json = NULL, draft = NULL, review_json = NULL,
                    status = 'stale', current_step = 'analysis', updated_at = ?
                WHERE id = ? AND owner_id = ?
                """,
                (
                    _dump(next_story_ids),
                    _dump(program),
                    _now(),
                    project_id,
                    owner_id,
                ),
            ).rowcount
        if not updated:
            raise NotFoundError("Essay project not found")
        return self.get_project(owner_id, project_id)

    def get_project(self, owner_id: str, project_id: str) -> EssayProjectResponse:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM essay_projects WHERE id = ? AND owner_id = ?",
                (project_id, owner_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Essay project not found")
            artifact_rows = connection.execute(
                "SELECT * FROM project_artifacts WHERE owner_id = ? AND project_id = ? "
                "ORDER BY created_at DESC, version_no DESC",
                (owner_id, project_id),
            ).fetchall()
        artifacts: List[EssayProjectArtifactVersion] = []
        for artifact in artifact_rows:
            payload = _load_json(artifact["payload_json"], {})
            artifacts.append(
                EssayProjectArtifactVersion(
                    id=artifact["id"],
                    project_id=artifact["project_id"],
                    artifact_type=artifact["artifact_type"],
                    version_no=artifact["version_no"],
                    created_at=artifact["created_at"],
                    outline=(
                        EssayOutline.model_validate(payload["outline"])
                        if payload.get("outline")
                        else None
                    ),
                    draft=payload.get("draft"),
                    metadata=_load_json(artifact["metadata_json"], {}),
                )
            )
        return EssayProjectResponse(
            id=row["id"],
            person_id=row["person_id"],
            background_instance_id=row["background_id"],
            application_project_id=row["application_project_id"],
            story_instance_ids=_load_json(row["story_ids_json"], []),
            program=ProgramContext.model_validate_json(row["program_json"]),
            analysis=(
                ProgramAnalysis.model_validate_json(row["analysis_json"])
                if row["analysis_json"]
                else None
            ),
            outline=(
                EssayOutline.model_validate_json(row["outline_json"])
                if row["outline_json"]
                else None
            ),
            draft=row["draft"],
            review=(
                DraftReview.model_validate_json(row["review_json"])
                if row["review_json"]
                else None
            ),
            status=row["status"],
            current_step=row["current_step"],
            versions=artifacts,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_projects(
        self,
        owner_id: str,
        *,
        background_id: Optional[str] = None,
    ) -> List[EssayProjectResponse]:
        with self._connection() as connection:
            if background_id:
                rows = connection.execute(
                    "SELECT id FROM essay_projects WHERE owner_id = ? AND background_id = ? "
                    "AND status != 'archived' ORDER BY updated_at DESC",
                    (owner_id, background_id),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id FROM essay_projects WHERE owner_id = ? AND status != 'archived' "
                    "ORDER BY updated_at DESC",
                    (owner_id,),
                ).fetchall()
        return [self.get_project(owner_id, row["id"]) for row in rows]

    def resolve_projects(
        self,
        owner_id: str,
        query: str = "",
        *,
        background_id: Optional[str] = None,
    ) -> List[EssayProjectResponse]:
        normalized = _normalize(query)
        with self._connection() as connection:
            clauses = ["owner_id = ?", "status != 'archived'"]
            params: List[Any] = [owner_id]
            if background_id:
                clauses.append("background_id = ?")
                params.append(background_id)
            rows = connection.execute(
                f"SELECT id FROM essay_projects WHERE {' AND '.join(clauses)} "
                "ORDER BY updated_at DESC",
                tuple(params),
            ).fetchall()
        projects = [self.get_project(owner_id, row["id"]) for row in rows]
        if not normalized:
            return projects
        filtered: List[EssayProjectResponse] = []
        for project in projects:
            label = _normalize(
                f"{project.program.school_name} {project.program.program_name} "
                f"{project.program.essay_type}"
            )
            if normalized in label:
                filtered.append(project)
        return filtered[:10]

    def add_project_artifact(
        self,
        owner_id: str,
        project_id: str,
        artifact_type: str,
        *,
        outline: Optional[EssayOutline] = None,
        draft: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EssayProjectArtifactVersion:
        self.get_project(owner_id, project_id)
        artifact_id = str(uuid.uuid4())
        created_at = _now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT COALESCE(MAX(version_no), 0) + 1 AS next_version "
                "FROM project_artifacts WHERE project_id = ? AND artifact_type = ?",
                (project_id, artifact_type),
            ).fetchone()
            version_no = int(row["next_version"])
            connection.execute(
                """
                INSERT INTO project_artifacts(
                    id, owner_id, project_id, artifact_type, version_no,
                    payload_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    owner_id,
                    project_id,
                    artifact_type,
                    version_no,
                    _dump(
                        {
                            "outline": outline.model_dump(mode="json") if outline else None,
                            "draft": draft,
                        }
                    ),
                    _dump(metadata or {}),
                    created_at,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return EssayProjectArtifactVersion(
            id=artifact_id,
            project_id=project_id,
            artifact_type=artifact_type,
            version_no=version_no,
            created_at=created_at,
            outline=outline,
            draft=draft,
            metadata=metadata or {},
        )

    def workspace_snapshot(
        self,
        owner_id: str,
        *,
        sync_legacy: bool = True,
    ) -> WorkspaceSnapshotResponse:
        if sync_legacy:
            self.sync_legacy_profiles(owner_id)
        return WorkspaceSnapshotResponse(
            persons=self.list_persons(owner_id),
            backgrounds=self.list_backgrounds(owner_id),
            application_projects=self.list_application_projects(owner_id),
            stories=self.list_stories(owner_id),
            projects=self.list_projects(owner_id),
        )

    def sync_legacy_profiles(self, owner_id: str) -> None:
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT id, profile_json FROM profiles WHERE owner_id = ? "
                    "ORDER BY created_at",
                    (owner_id,),
                ).fetchall()
        except sqlite3.OperationalError:
            return
        for row in rows:
            try:
                profile = ProfileData.model_validate_json(row["profile_json"])
                self.ensure_background_for_profile(
                    owner_id,
                    row["id"],
                    profile,
                )
            except (ValueError, ConflictError):
                continue
        self.sync_legacy_sessions(owner_id)

    def sync_legacy_sessions(self, owner_id: str) -> None:
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT s.*, a.program_json, a.analysis_json
                    FROM sessions s
                    JOIN analyses a ON a.id = s.analysis_id AND a.owner_id = s.owner_id
                    WHERE s.owner_id = ?
                    ORDER BY s.created_at
                    """,
                    (owner_id,),
                ).fetchall()
        except sqlite3.OperationalError:
            return
        for row in rows:
            try:
                with self._connection() as connection:
                    background = connection.execute(
                        "SELECT id FROM backgrounds WHERE owner_id = ? "
                        "AND legacy_profile_id = ?",
                        (owner_id, row["profile_id"]),
                    ).fetchone()
                    story = connection.execute(
                        "SELECT id FROM stories WHERE owner_id = ? "
                        "AND legacy_session_id = ?",
                        (owner_id, row["id"]),
                    ).fetchone()
                if background is None:
                    continue
                if story is None:
                    program = ProgramContext.model_validate_json(
                        row["program_json"]
                    )
                    title = (
                        f"Legacy · {program.school_name} · "
                        f"{program.program_name} · {program.essay_type}"
                    )
                    try:
                        created_story = self.create_story(
                            owner_id,
                            background["id"],
                            title,
                            focus=program.prompt_text[:400],
                            messages=[
                                StoryMessage.model_validate(item)
                                for item in _load_json(row["messages_json"], [])
                            ],
                            cards=StoryCards.model_validate_json(row["cards_json"]),
                            round_no=max(1, min(3, int(row["round_no"]))),
                            status=row["status"],
                        )
                    except ConflictError:
                        continue
                    with self._connection() as connection:
                        connection.execute(
                            "UPDATE stories SET legacy_session_id = ? "
                            "WHERE id = ? AND owner_id = ?",
                            (row["id"], created_story.id, owner_id),
                        )
                    story_id = created_story.id
                else:
                    story_id = story["id"]

                if row["status"] != "ready":
                    continue
                with self._connection() as connection:
                    project = connection.execute(
                        "SELECT id FROM essay_projects WHERE owner_id = ? "
                        "AND legacy_session_id = ?",
                        (owner_id, row["id"]),
                    ).fetchone()
                if project is not None:
                    continue
                program = ProgramContext.model_validate_json(row["program_json"])
                analysis = ProgramAnalysis.model_validate_json(
                    row["analysis_json"]
                )
                created_project = self.create_project(
                    owner_id,
                    background["id"],
                    [story_id],
                    program,
                )
                outline = (
                    EssayOutline.model_validate_json(row["outline_json"])
                    if row["outline_json"]
                    else None
                )
                review = (
                    DraftReview.model_validate_json(row["review_json"])
                    if row["review_json"]
                    else None
                )
                draft = row["draft"]
                if review:
                    status, current_step = "reviewed", "review"
                elif draft:
                    status, current_step = "drafted", "draft"
                elif outline:
                    status, current_step = "outlined", "outline"
                else:
                    status, current_step = "analyzed", "analysis"
                self.save_project(
                    owner_id,
                    created_project.id,
                    analysis=analysis,
                    outline=outline,
                    draft=draft,
                    review=review,
                    status=status,
                    current_step=current_step,
                )
                with self._connection() as connection:
                    connection.execute(
                        "UPDATE essay_projects SET legacy_session_id = ? "
                        "WHERE id = ? AND owner_id = ?",
                        (row["id"], created_project.id, owner_id),
                    )
                    artifacts = connection.execute(
                        "SELECT * FROM artifacts WHERE owner_id = ? "
                        "AND session_id = ?",
                        (owner_id, row["id"]),
                    ).fetchall()
                    for artifact in artifacts:
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO project_artifacts(
                                id, owner_id, project_id, artifact_type,
                                version_no, payload_json, metadata_json, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                artifact["id"],
                                owner_id,
                                created_project.id,
                                artifact["artifact_type"],
                                artifact["version_no"],
                                artifact["payload_json"],
                                artifact["metadata_json"],
                                artifact["created_at"],
                            ),
                        )
            except (ValueError, ConflictError, NotFoundError):
                continue

    def delete_workspace_data(self, owner_id: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM persons WHERE owner_id = ?", (owner_id,))
        owner_key = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:24]
        resume_dir = (self.path.parent / "resumes" / owner_key).resolve()
        resume_root = (self.path.parent / "resumes").resolve()
        if resume_dir.parent == resume_root and resume_dir.exists():
            shutil.rmtree(resume_dir)


_domain_store: Optional[DomainStore] = None


def configure_domain_store(path: Path | str | None = None) -> DomainStore:
    global _domain_store
    target = Path(path) if path else get_settings().resolved_database_path
    _domain_store = DomainStore(target)
    return _domain_store


def get_domain_store() -> DomainStore:
    global _domain_store
    if _domain_store is None:
        _domain_store = DomainStore(get_settings().resolved_database_path)
    return _domain_store
