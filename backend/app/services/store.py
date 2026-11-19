from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.errors import ConflictError, NotFoundError
from app.schemas import (
    ArtifactVersion,
    BatchCreateRequest,
    BatchItemResponse,
    BatchResponse,
    DraftReview,
    EssayOutline,
    HistoryItem,
    ProgramAnalysis,
    ProgramContext,
    ProfileData,
    SessionSnapshotResponse,
    StoryCards,
    StoryMessage,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in value
        ]
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@dataclass
class ProfileRecord:
    id: str
    owner_id: str
    profile: ProfileData
    created_at: str


@dataclass
class AnalysisRecord:
    id: str
    owner_id: str
    profile_id: str
    program: ProgramContext
    analysis: ProgramAnalysis
    created_at: str


@dataclass
class SessionRecord:
    id: str
    owner_id: str
    profile_id: str
    analysis_id: str
    messages: List[StoryMessage]
    cards: StoryCards
    outline: Optional[EssayOutline]
    draft: Optional[str]
    review: Optional[DraftReview]
    round_no: int
    status: str
    created_at: str
    updated_at: str


class SQLiteStore:
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
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_profiles_owner
                ON profiles(owner_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS analyses (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    program_json TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_analyses_owner_profile
                ON analyses(owner_id, profile_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    analysis_id TEXT NOT NULL,
                    messages_json TEXT NOT NULL,
                    cards_json TEXT NOT NULL,
                    outline_json TEXT,
                    draft TEXT,
                    review_json TEXT,
                    round_no INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
                    FOREIGN KEY(analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_owner_updated
                ON sessions(owner_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id, artifact_type, version_no),
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_artifacts_owner_session
                ON artifacts(owner_id, session_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    tone TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(owner_id, request_id),
                    FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_batches_owner_updated
                ON batches(owner_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS batch_items (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    direction_index INTEGER NOT NULL,
                    item_index INTEGER NOT NULL,
                    program_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    analysis_id TEXT,
                    session_id TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    FOREIGN KEY(batch_id) REFERENCES batches(id) ON DELETE CASCADE,
                    FOREIGN KEY(analysis_id) REFERENCES analyses(id) ON DELETE SET NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_batch_items_batch
                ON batch_items(batch_id, item_index);
                """
            )

    def healthcheck(self) -> None:
        with self._connection() as connection:
            connection.execute("SELECT 1").fetchone()

    def create_batch(self, owner_id: str, request: BatchCreateRequest) -> BatchResponse:
        self.require_profile(request.profile_id, owner_id)
        batch_id = str(uuid.uuid4())
        now = _now()
        request_json = _dump(request)
        with self._connection() as connection:
            # Claim the idempotency key and insert every item in one transaction.
            # INSERT OR IGNORE also handles two simultaneous submissions safely.
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO batches(
                    id, owner_id, profile_id, request_id, request_json,
                    tone, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (batch_id, owner_id, request.profile_id, request.request_id,
                 request_json, request.tone, now, now),
            ).rowcount
            if not inserted:
                existing = connection.execute(
                    "SELECT id, request_json FROM batches WHERE owner_id = ? AND request_id = ?",
                    (owner_id, request.request_id),
                ).fetchone()
                if existing["request_json"] != request_json:
                    raise ConflictError("This request_id already belongs to a different batch request")
                batch_id = existing["id"]
            else:
                active_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM batches WHERE owner_id = ? "
                    "AND status IN ('pending', 'running')",
                    (owner_id,),
                ).fetchone()["count"]
                if active_count > 1:
                    raise ConflictError("Wait for your active batch to finish before starting another")
                item_index = 0
                for direction_index, direction in enumerate(request.directions):
                    for essay in direction.essays:
                        program = ProgramContext(
                            school_name=direction.school_name,
                            program_name=direction.program_name,
                            program_details=direction.program_details,
                            essay_type=essay.essay_type,
                            word_limit=essay.word_limit,
                            prompt_text=essay.prompt_text,
                        )
                        connection.execute(
                            """
                            INSERT INTO batch_items(
                                id, batch_id, direction_index, item_index,
                                program_json, status, stage
                            ) VALUES (?, ?, ?, ?, ?, 'pending', 'pending')
                            """,
                            (str(uuid.uuid4()), batch_id, direction_index,
                             item_index, _dump(program)),
                        )
                        item_index += 1
        return self.batch_snapshot(batch_id, owner_id)

    def get_batch(self, batch_id: str, owner_id: str) -> Optional[BatchResponse]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM batches WHERE id = ? AND owner_id = ?",
                (batch_id, owner_id),
            ).fetchone()
            if row is None:
                return None
            items = connection.execute(
                """
                SELECT i.*, s.draft FROM batch_items i
                LEFT JOIN sessions s ON s.id = i.session_id AND s.owner_id = ?
                WHERE i.batch_id = ? ORDER BY i.item_index
                """,
                (owner_id, batch_id),
            ).fetchall()
        return BatchResponse(
            id=row["id"], profile_id=row["profile_id"], tone=row["tone"],
            status=row["status"], created_at=row["created_at"], updated_at=row["updated_at"],
            items=[BatchItemResponse(
                id=item["id"], direction_index=item["direction_index"],
                program=ProgramContext.model_validate_json(item["program_json"]),
                status=item["status"], stage=item["stage"],
                session_id=item["session_id"], draft=item["draft"],
                error_code=item["error_code"], error_message=item["error_message"],
            ) for item in items],
        )

    def require_batch(self, batch_id: str, owner_id: str) -> BatchResponse:
        batch = self.get_batch(batch_id, owner_id)
        if batch is None:
            raise NotFoundError("Batch not found")
        return batch

    def batch_snapshot(self, batch_id: str, owner_id: str) -> BatchResponse:
        return self.require_batch(batch_id, owner_id)

    def list_batches(self, owner_id: str) -> List[BatchResponse]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id FROM batches WHERE owner_id = ? ORDER BY created_at DESC LIMIT 100",
                (owner_id,),
            ).fetchall()
        return [batch for row in rows if (batch := self.get_batch(row["id"], owner_id))]

    def claim_batch(self, batch_id: str, owner_id: str) -> bool:
        with self._connection() as connection:
            return bool(connection.execute(
                "UPDATE batches SET status = 'running', updated_at = ? "
                "WHERE id = ? AND owner_id = ? AND status = 'pending'",
                (_now(), batch_id, owner_id),
            ).rowcount)

    def pending_batches(self) -> List[tuple[str, str]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, owner_id FROM batches WHERE status = 'pending' ORDER BY created_at LIMIT 100"
            ).fetchall()
        return [(row["id"], row["owner_id"]) for row in rows]

    def batch_item_state(self, batch_id: str, item_id: str, owner_id: str) -> Dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT i.* FROM batch_items i JOIN batches b ON b.id = i.batch_id "
                "WHERE i.batch_id = ? AND i.id = ? AND b.owner_id = ?",
                (batch_id, item_id, owner_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("Batch item not found")
        return dict(row)

    def update_batch_item(
        self, batch_id: str, item_id: str, owner_id: str, **changes: Any
    ) -> None:
        allowed = {"status", "stage", "analysis_id", "session_id", "error_code", "error_message"}
        if not changes or not set(changes) <= allowed:
            raise ValueError("Invalid batch item update")
        with self._connection() as connection:
            assignments = ", ".join(f"{key} = ?" for key in changes)
            updated = connection.execute(
                f"UPDATE batch_items SET {assignments} WHERE id = ? AND batch_id = ? "
                "AND EXISTS(SELECT 1 FROM batches WHERE id = ? AND owner_id = ?)",
                (*changes.values(), item_id, batch_id, batch_id, owner_id),
            ).rowcount
            if not updated:
                raise NotFoundError("Batch item not found")
            connection.execute(
                "UPDATE batches SET updated_at = ? WHERE id = ? AND owner_id = ?",
                (_now(), batch_id, owner_id),
            )

    def finish_batch(self, batch_id: str, owner_id: str) -> None:
        with self._connection() as connection:
            counts = connection.execute(
                "SELECT i.status, COUNT(*) AS count FROM batch_items i "
                "JOIN batches b ON b.id = i.batch_id "
                "WHERE b.id = ? AND b.owner_id = ? GROUP BY i.status",
                (batch_id, owner_id),
            ).fetchall()
            statuses = {row["status"]: row["count"] for row in counts}
            if not statuses:
                return
            if statuses.get("pending") or statuses.get("running"):
                status = "pending"
            elif statuses.get("failed"):
                status = "partial_failed" if statuses.get("completed") else "failed"
            else:
                status = "completed"
            connection.execute(
                "UPDATE batches SET status = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
                (status, _now(), batch_id, owner_id),
            )

    def retry_batch(self, batch_id: str, owner_id: str) -> BatchResponse:
        with self._connection() as connection:
            # Serialize the active-batch check with create/retry submissions.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM batches WHERE id = ? AND owner_id = ?",
                (batch_id, owner_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Batch not found")
            if row["status"] not in {"partial_failed", "failed"}:
                raise ConflictError("Only a batch with failed items can be retried")
            active = connection.execute(
                "SELECT 1 FROM batches WHERE owner_id = ? AND status IN ('pending', 'running') LIMIT 1",
                (owner_id,),
            ).fetchone()
            if active is not None:
                raise ConflictError("Wait for your active batch to finish before retrying another")
            connection.execute(
                "UPDATE batch_items SET status = 'pending', stage = 'pending', "
                "error_code = NULL, error_message = NULL WHERE batch_id = ? AND status = 'failed'",
                (batch_id,),
            )
            connection.execute(
                "UPDATE batches SET status = 'pending', updated_at = ? WHERE id = ? AND owner_id = ?",
                (_now(), batch_id, owner_id),
            )
        return self.batch_snapshot(batch_id, owner_id)

    def recover_batches(self) -> None:
        # This MVP has one backend process and one worker. Persisted checkpoints
        # make an interrupted model stage safe to resume on the next startup.
        with self._connection() as connection:
            connection.execute(
                "UPDATE batch_items SET status = 'pending' WHERE status = 'running' "
                "AND batch_id IN (SELECT id FROM batches WHERE status = 'running')"
            )
            connection.execute(
                "UPDATE batches SET status = 'pending', updated_at = ? WHERE status = 'running'",
                (_now(),),
            )

    def save_profile(self, owner_id: str, profile: ProfileData) -> ProfileRecord:
        profile_id = str(uuid.uuid4())
        created_at = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO profiles(id, owner_id, profile_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (profile_id, owner_id, _dump(profile), created_at),
            )
        return ProfileRecord(profile_id, owner_id, profile, created_at)

    def get_profile(self, profile_id: str, owner_id: str) -> Optional[ProfileRecord]:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT id, owner_id, profile_json, created_at
                FROM profiles
                WHERE id = ? AND owner_id = ?
                """,
                (profile_id, owner_id),
            ).fetchone()
        if not row:
            return None
        return ProfileRecord(
            id=row["id"],
            owner_id=row["owner_id"],
            profile=ProfileData.model_validate_json(row["profile_json"]),
            created_at=row["created_at"],
        )

    def require_profile(self, profile_id: str, owner_id: str) -> ProfileRecord:
        profile = self.get_profile(profile_id, owner_id)
        if not profile:
            raise NotFoundError("Profile not found")
        return profile

    def save_analysis(
        self,
        owner_id: str,
        profile_id: str,
        program: ProgramContext,
        analysis: ProgramAnalysis,
    ) -> AnalysisRecord:
        self.require_profile(profile_id, owner_id)
        analysis_id = str(uuid.uuid4())
        created_at = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO analyses(
                    id, owner_id, profile_id, program_json, analysis_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    owner_id,
                    profile_id,
                    _dump(program),
                    _dump(analysis),
                    created_at,
                ),
            )
        return AnalysisRecord(
            id=analysis_id,
            owner_id=owner_id,
            profile_id=profile_id,
            program=program,
            analysis=analysis,
            created_at=created_at,
        )

    def get_analysis(self, analysis_id: str, owner_id: str) -> Optional[AnalysisRecord]:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT id, owner_id, profile_id, program_json, analysis_json, created_at
                FROM analyses
                WHERE id = ? AND owner_id = ?
                """,
                (analysis_id, owner_id),
            ).fetchone()
        if not row:
            return None
        return AnalysisRecord(
            id=row["id"],
            owner_id=row["owner_id"],
            profile_id=row["profile_id"],
            program=ProgramContext.model_validate_json(row["program_json"]),
            analysis=ProgramAnalysis.model_validate_json(row["analysis_json"]),
            created_at=row["created_at"],
        )

    def require_analysis(self, analysis_id: str, owner_id: str) -> AnalysisRecord:
        analysis = self.get_analysis(analysis_id, owner_id)
        if not analysis:
            raise NotFoundError("Analysis not found")
        return analysis

    def create_session(
        self,
        owner_id: str,
        profile_id: str,
        analysis_id: str,
        messages: List[StoryMessage],
        cards: StoryCards,
        round_no: int = 1,
        status: str = "interviewing",
    ) -> SessionRecord:
        profile = self.require_profile(profile_id, owner_id)
        analysis = self.require_analysis(analysis_id, owner_id)
        if analysis.profile_id != profile.id:
            raise ConflictError("Analysis does not belong to the selected profile")

        session_id = str(uuid.uuid4())
        created_at = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO sessions(
                    id, owner_id, profile_id, analysis_id, messages_json, cards_json,
                    outline_json, draft, review_json, round_no, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    owner_id,
                    profile_id,
                    analysis_id,
                    _dump(messages),
                    _dump(cards),
                    round_no,
                    status,
                    created_at,
                    created_at,
                ),
            )
        return SessionRecord(
            id=session_id,
            owner_id=owner_id,
            profile_id=profile_id,
            analysis_id=analysis_id,
            messages=messages,
            cards=cards,
            outline=None,
            draft=None,
            review=None,
            round_no=round_no,
            status=status,
            created_at=created_at,
            updated_at=created_at,
        )

    def get_session(self, session_id: str, owner_id: str) -> Optional[SessionRecord]:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM sessions
                WHERE id = ? AND owner_id = ?
                """,
                (session_id, owner_id),
            ).fetchone()
        if not row:
            return None
        return self._session_from_row(row)

    def require_session(self, session_id: str, owner_id: str) -> SessionRecord:
        session = self.get_session(session_id, owner_id)
        if not session:
            raise NotFoundError("Session not found")
        return session

    def save_session(self, session: SessionRecord) -> SessionRecord:
        session.updated_at = _now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE sessions
                SET messages_json = ?, cards_json = ?, outline_json = ?, draft = ?,
                    review_json = ?, round_no = ?, status = ?, updated_at = ?
                WHERE id = ? AND owner_id = ?
                """,
                (
                    _dump(session.messages),
                    _dump(session.cards),
                    _dump(session.outline) if session.outline else None,
                    session.draft,
                    _dump(session.review) if session.review else None,
                    session.round_no,
                    session.status,
                    session.updated_at,
                    session.id,
                    session.owner_id,
                ),
            )
        if cursor.rowcount != 1:
            raise NotFoundError("Session not found")
        return session

    def add_artifact(
        self,
        owner_id: str,
        session_id: str,
        artifact_type: str,
        *,
        outline: Optional[EssayOutline] = None,
        draft: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactVersion:
        self.require_session(session_id, owner_id)
        artifact_id = str(uuid.uuid4())
        created_at = _now()
        payload = {
            "outline": outline.model_dump(mode="json") if outline else None,
            "draft": draft,
        }
        metadata_json = metadata or {}

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT COALESCE(MAX(version_no), 0) + 1 AS next_version
                FROM artifacts
                WHERE session_id = ? AND artifact_type = ?
                """,
                (session_id, artifact_type),
            ).fetchone()
            version_no = int(row["next_version"])
            connection.execute(
                """
                INSERT INTO artifacts(
                    id, owner_id, session_id, artifact_type, version_no,
                    payload_json, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    owner_id,
                    session_id,
                    artifact_type,
                    version_no,
                    _dump(payload),
                    _dump(metadata_json),
                    created_at,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return ArtifactVersion(
            id=artifact_id,
            session_id=session_id,
            artifact_type=artifact_type,
            version_no=version_no,
            created_at=created_at,
            outline=outline,
            draft=draft,
            metadata=metadata_json,
        )

    def list_artifacts(self, session_id: str, owner_id: str) -> List[ArtifactVersion]:
        self.require_session(session_id, owner_id)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM artifacts
                WHERE session_id = ? AND owner_id = ?
                ORDER BY created_at DESC
                """,
                (session_id, owner_id),
            ).fetchall()
        versions: List[ArtifactVersion] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            versions.append(
                ArtifactVersion(
                    id=row["id"],
                    session_id=row["session_id"],
                    artifact_type=row["artifact_type"],
                    version_no=row["version_no"],
                    created_at=row["created_at"],
                    outline=(
                        EssayOutline.model_validate(payload["outline"])
                        if payload.get("outline")
                        else None
                    ),
                    draft=payload.get("draft"),
                    metadata=json.loads(row["metadata_json"]),
                )
            )
        return versions

    def session_snapshot(
        self, session_id: str, owner_id: str
    ) -> SessionSnapshotResponse:
        session = self.require_session(session_id, owner_id)
        profile = self.require_profile(session.profile_id, owner_id)
        analysis = self.require_analysis(session.analysis_id, owner_id)
        return SessionSnapshotResponse(
            session_id=session.id,
            profile_id=session.profile_id,
            analysis_id=session.analysis_id,
            program=analysis.program,
            profile=profile.profile,
            analysis=analysis.analysis,
            cards=session.cards,
            messages=session.messages,
            outline=session.outline,
            draft=session.draft,
            review=session.review,
            round_no=session.round_no,
            status=session.status,
            versions=self.list_artifacts(session.id, owner_id),
        )

    def list_history(self, owner_id: str) -> List[HistoryItem]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    s.id,
                    s.profile_id,
                    s.outline_json,
                    s.draft,
                    s.round_no,
                    s.status,
                    s.created_at,
                    s.updated_at,
                    p.profile_json,
                    a.program_json
                FROM sessions s
                JOIN profiles p ON p.id = s.profile_id
                JOIN analyses a ON a.id = s.analysis_id
                WHERE s.owner_id = ? AND p.owner_id = ? AND a.owner_id = ?
                ORDER BY s.updated_at DESC
                LIMIT 100
                """,
                (owner_id, owner_id, owner_id),
            ).fetchall()

        items: List[HistoryItem] = []
        for row in rows:
            profile = ProfileData.model_validate_json(row["profile_json"])
            program = ProgramContext.model_validate_json(row["program_json"])
            label = " - ".join(
                part for part in (program.school_name, program.program_name, program.essay_type) if part
            )
            draft = row["draft"]
            preview = " ".join((draft or "").split())[:180]
            items.append(
                HistoryItem(
                    session_id=row["id"],
                    profile_id=row["profile_id"],
                    applicant=profile.basic_profile.full_name or "Unnamed applicant",
                    program_label=label or "Untitled program",
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    round_no=row["round_no"],
                    status=row["status"],
                    has_outline=bool(row["outline_json"]),
                    has_draft=bool(draft),
                    draft_preview=preview,
                )
            )
        return items

    def delete_history(self, owner_id: str) -> int:
        with self._connection() as connection:
            count_row = connection.execute(
                "SELECT COUNT(*) AS count FROM sessions WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()
            deleted = int(count_row["count"])
            connection.execute(
                "DELETE FROM sessions WHERE owner_id = ?",
                (owner_id,),
            )
            connection.execute(
                "DELETE FROM profiles WHERE owner_id = ?",
                (owner_id,),
            )
        return deleted

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            id=row["id"],
            owner_id=row["owner_id"],
            profile_id=row["profile_id"],
            analysis_id=row["analysis_id"],
            messages=[
                StoryMessage.model_validate(item)
                for item in json.loads(row["messages_json"])
            ],
            cards=StoryCards.model_validate_json(row["cards_json"]),
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
            round_no=row["round_no"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


_store: Optional[SQLiteStore] = None


def configure_store(path: Path | str | None = None) -> SQLiteStore:
    global _store
    target = Path(path) if path else get_settings().resolved_database_path
    _store = SQLiteStore(target)
    return _store


def get_store() -> SQLiteStore:
    if _store is None:
        return configure_store()
    return _store
