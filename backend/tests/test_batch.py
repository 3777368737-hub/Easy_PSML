from __future__ import annotations

import asyncio
import copy
import json
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.errors import AppError, ConflictError, UpstreamServiceError
from app.main import app
from app.schemas import (
    BasicProfile,
    BatchCreateRequest,
    EssayOutline,
    ExperienceItem,
    ProfileData,
    ProgramAnalysis,
)
from app.services import batch, workflow
from app.services.store import configure_store, get_store
from tests.test_workflow import FakeDeepSeekClient, OWNER_A, OWNER_B


PS = "Personal Statement"
ML = "Motivation Letter"


def batch_payload(profile_id: str = "profile-for-validation") -> dict:
    return {
        "profile_id": profile_id,
        "request_id": "request-batch-test-0001",
        "tone": "authentic",
        "directions": [
            {
                "school_name": "North University",
                "program_name": "MSc Robotics",
                "program_details": "Verified robotics course information.",
                "essays": [
                    {
                        "essay_type": PS,
                        "word_limit": 500,
                        "prompt_text": "ROBOTICS_PS: Explain your personal growth through engineering.",
                    },
                    {
                        "essay_type": ML,
                        "word_limit": 300,
                        "prompt_text": "ROBOTICS_ML: Explain why this robotics program fits your goals.",
                    },
                ],
            },
            {
                "school_name": "South University",
                "program_name": "MSc Public Policy",
                "program_details": "Verified public policy seminar information.",
                "essays": [
                    {
                        "essay_type": PS,
                        "word_limit": 600,
                        "prompt_text": "POLICY_PS: Explain your experiences and public service aspirations.",
                    },
                    {
                        "essay_type": ML,
                        "word_limit": 400,
                        "prompt_text": "POLICY_ML: Explain your preparation for this policy program.",
                    },
                ],
            },
        ],
    }


def program_context(messages) -> dict:
    content = "\n".join(message["content"] for message in messages)
    marker = "Program context:\n"
    return json.JSONDecoder().raw_decode(content.split(marker, 1)[1])[0]


class RecordingClient(FakeDeepSeekClient):
    """Exercise real workflow/storage while making every model call deterministic."""

    def __init__(self) -> None:
        self.calls = []
        self.fail_once = None
        self.cancel_once = None
        self.pause_stage = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def record(self, stage, messages):
        context = program_context(messages)
        key = (context["program_name"], context["essay_type"], stage)
        self.calls.append((key, context, messages))
        # Yield so simultaneous workers actually compete for a batch claim.
        await asyncio.sleep(0)
        if stage == self.pause_stage:
            self.entered.set()
            await self.release.wait()
        if key == self.cancel_once:
            self.cancel_once = None
            raise asyncio.CancelledError()
        if key == self.fail_once:
            self.fail_once = None
            raise UpstreamServiceError()
        return context

    async def chat_json(self, messages, response_model, **kwargs):
        if response_model is ProgramAnalysis:
            await self.record("analysis", messages)
        elif response_model is EssayOutline:
            await self.record("outline", messages)
        else:
            raise AssertionError("Batch generation must not invent an interview")
        return await super().chat_json(messages, response_model, **kwargs)

    async def chat_text(self, messages, **kwargs):
        context = await self.record("draft", messages)
        prefix = f"{context['school_name']} {context['program_name']} {context['essay_type']}"
        return prefix + " " + " ".join(["evidence"] * context["word_limit"])

    def call_counts(self):
        return Counter(key for key, _, _ in self.calls)


class BatchValidationTests(unittest.TestCase):
    def test_request_normalizes_text_before_validation(self) -> None:
        payload = batch_payload()
        direction = payload["directions"][0]
        direction["school_name"] = "  North University  "
        direction["program_name"] = "  MSc Robotics  "
        direction["program_details"] = "  verified details  "
        direction["essays"][0]["prompt_text"] = "  Describe your engineering experience.  "
        request = BatchCreateRequest.model_validate(payload)
        self.assertEqual(request.directions[0].school_name, "North University")
        self.assertEqual(request.directions[0].program_name, "MSc Robotics")
        self.assertEqual(request.directions[0].program_details, "verified details")
        self.assertEqual(
            request.directions[0].essays[0].prompt_text,
            "Describe your engineering experience.",
        )

    def test_invalid_or_unbounded_requests_are_rejected(self) -> None:
        cases = []
        payload = batch_payload()
        payload["directions"] = []
        cases.append(("no directions", payload))
        for field in ("school_name", "program_name"):
            payload = batch_payload()
            payload["directions"][0][field] = "   "
            cases.append((f"blank {field}", payload))
        for prompt in ("", "         ", "  short  "):
            payload = batch_payload()
            payload["directions"][0]["essays"][0]["prompt_text"] = prompt
            cases.append((f"short prompt {prompt!r}", payload))
        for word_limit in (99, 5001):
            payload = batch_payload()
            payload["directions"][0]["essays"][0]["word_limit"] = word_limit
            cases.append((f"word limit {word_limit}", payload))
        for essays in ([], [batch_payload()["directions"][0]["essays"][0]] * 3):
            payload = batch_payload()
            payload["directions"][0]["essays"] = essays
            cases.append((f"essay count {len(essays)}", payload))
        payload = batch_payload()
        payload["directions"][0]["essays"][1]["essay_type"] = PS
        cases.append(("duplicate essay type", payload))
        payload = batch_payload()
        payload["directions"][0]["essays"][0]["essay_type"] = "Unknown Essay"
        cases.append(("unsupported essay type", payload))
        for label, candidate in cases:
            with self.subTest(label=label), self.assertRaises(ValidationError):
                BatchCreateRequest.model_validate(candidate)

    def test_one_essay_and_variable_direction_counts_are_supported(self) -> None:
        payload = batch_payload()
        payload["directions"] = [payload["directions"][0]]
        payload["directions"][0]["essays"] = [payload["directions"][0]["essays"][1]]
        self.assertEqual(len(BatchCreateRequest.model_validate(payload).directions), 1)
        payload = batch_payload()
        payload["directions"] = [
            copy.deepcopy(payload["directions"][0]) for _ in range(8)
        ]
        request = BatchCreateRequest.model_validate(payload)
        self.assertEqual(
            sum(len(direction.essays) for direction in request.directions),
            16,
        )


class BatchWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "batch.db"
        self.store = configure_store(self.database_path)
        self.profile = self.store.save_profile(
            OWNER_A,
            ProfileData(
                basic_profile=BasicProfile(
                    full_name="Batch Applicant",
                    current_university="Current University",
                    major="Engineering",
                    target_field="Interdisciplinary study",
                ),
                motivation_summary="Use engineering to improve public services.",
                career_goal="Develop accessible public technology.",
                projects=[
                    ExperienceItem(
                        title="Campus accessibility map",
                        summary="Mapped accessible routes across campus.",
                        impact="Used by the student services team.",
                    )
                ],
                top_strengths=["Engineering", "Public service"],
            ),
        )
        self.request = BatchCreateRequest.model_validate(batch_payload(self.profile.id))
        self.fake = RecordingClient()
        self.client_patch = patch.object(workflow, "client", self.fake)
        self.client_patch.start()
        self.limiter_patch = patch.object(batch.model_rate_limiter, "check")
        self.limiter = self.limiter_patch.start()

    def test_batch_supports_more_than_five_directions(self) -> None:
        payload = batch_payload(self.profile.id)
        payload["directions"] = [
            copy.deepcopy(payload["directions"][0]) for _ in range(7)
        ]
        request = BatchCreateRequest.model_validate(payload)
        response = self.store.create_batch(OWNER_A, request)
        self.assertEqual(len(response.items), 14)
        self.assertEqual(response.items[-1].direction_index, 6)

    def tearDown(self) -> None:
        self.limiter_patch.stop()
        self.client_patch.stop()
        self.temp_dir.cleanup()

    async def test_each_direction_and_type_gets_independent_context_and_artifacts(self) -> None:
        created = batch.create_batch(OWNER_A, self.request)
        self.assertEqual(created.status, "pending")
        self.assertEqual(len(created.items), 4)
        await batch.process_batch(OWNER_A, created.id)
        completed = self.store.batch_snapshot(created.id, OWNER_A)
        self.assertEqual(completed.status, "completed")
        self.assertEqual({item.status for item in completed.items}, {"completed"})
        self.assertEqual({item.stage for item in completed.items}, {"completed"})
        self.assertEqual(len({item.session_id for item in completed.items}), 4)
        self.assertEqual(len(self.store.list_history(OWNER_A)), 4)
        self.assertEqual(self.store.list_history(OWNER_B), [])
        self.assertEqual(self.limiter.call_count, 12)
        for item in completed.items:
            snapshot = self.store.session_snapshot(item.session_id, OWNER_A)
            self.assertEqual(snapshot.profile_id, self.profile.id)
            self.assertEqual(snapshot.program, item.program)
            self.assertEqual(snapshot.status, "ready")
            self.assertEqual(snapshot.draft, item.draft)
            self.assertEqual(len(snapshot.versions), 2)
            self.assertEqual({v.artifact_type for v in snapshot.versions}, {"outline", "draft"})
            self.assertTrue(all(v.version_no == 1 for v in snapshot.versions))
            self.assertFalse(any(message.role == "user" for message in snapshot.messages))
            draft_version = next(v for v in snapshot.versions if v.artifact_type == "draft")
            self.assertEqual(draft_version.metadata["tone"], "authentic")
            self.assertEqual(draft_version.metadata["target_length"], item.program.word_limit)
        for (name, essay_type, stage), context, messages in self.fake.calls:
            expected = next(
                item.program
                for item in completed.items
                if item.program.program_name == name and item.program.essay_type == essay_type
            )
            self.assertEqual(context, expected.model_dump())
            content = "\n".join(message["content"] for message in messages)
            self.assertIn(expected.prompt_text, content)
            other_program = "MSc Public Policy" if name == "MSc Robotics" else "MSc Robotics"
            self.assertNotIn(other_program, content)
            if stage == "draft":
                self.assertIn(f"approximately {expected.word_limit} words", content)

    async def test_retry_resumes_failed_draft_and_preserves_successful_outputs(self) -> None:
        self.fake.fail_once = ("MSc Robotics", PS, "draft")
        created = batch.create_batch(OWNER_A, self.request)
        await batch.process_batch(OWNER_A, created.id)
        failed = self.store.batch_snapshot(created.id, OWNER_A)
        self.assertEqual(failed.status, "partial_failed")
        failed_item = next(item for item in failed.items if item.status == "failed")
        self.assertEqual(failed_item.error_code, "model_service_unavailable")
        session_id = failed_item.session_id
        self.assertIsNotNone(session_id)
        self.assertEqual(len(self.store.session_snapshot(session_id, OWNER_A).versions), 1)
        successful = {
            item.id: (item.session_id, item.draft)
            for item in failed.items
            if item.status == "completed"
        }
        before = self.fake.call_counts()
        retried = batch.retry_batch(OWNER_A, created.id)
        self.assertEqual(retried.status, "pending")
        await batch.process_batch(OWNER_A, created.id)
        completed = self.store.batch_snapshot(created.id, OWNER_A)
        self.assertEqual(completed.status, "completed")
        for item in completed.items:
            self.assertIsNone(item.error_code)
            self.assertIsNone(item.error_message)
            if item.id in successful:
                self.assertEqual((item.session_id, item.draft), successful[item.id])
            else:
                self.assertEqual(item.session_id, session_id)
        self.assertEqual(
            self.fake.call_counts() - before,
            Counter({("MSc Robotics", PS, "draft"): 1}),
        )
        self.assertEqual(len(self.store.session_snapshot(session_id, OWNER_A).versions), 2)

    async def test_duplicate_processors_claim_the_batch_once(self) -> None:
        created = batch.create_batch(OWNER_A, self.request)
        await asyncio.gather(
            batch.process_batch(OWNER_A, created.id),
            batch.process_batch(OWNER_A, created.id),
        )
        self.assertEqual(self.store.batch_snapshot(created.id, OWNER_A).status, "completed")
        self.assertEqual(len(self.fake.calls), 12)
        self.assertEqual(len(self.store.list_history(OWNER_A)), 4)

    async def test_rate_limit_failure_is_saved_without_calling_the_model(self) -> None:
        created = batch.create_batch(OWNER_A, self.request)
        self.limiter.side_effect = AppError(
            "Too many model requests. Retry later.", status_code=429, code="rate_limited"
        )
        await batch.process_batch(OWNER_A, created.id)
        failed = self.store.batch_snapshot(created.id, OWNER_A)
        self.assertEqual(failed.status, "failed")
        self.assertTrue(all(item.error_code == "rate_limited" for item in failed.items))
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.store.list_history(OWNER_A), [])
        self.limiter.side_effect = None
        batch.retry_batch(OWNER_A, created.id)
        await batch.process_batch(OWNER_A, created.id)
        self.assertEqual(self.store.batch_snapshot(created.id, OWNER_A).status, "completed")

    async def test_retry_cannot_create_a_second_active_batch_for_the_owner(self) -> None:
        first = batch.create_batch(OWNER_A, self.request)
        with self.assertRaises(ConflictError):
            batch.retry_batch(OWNER_A, first.id)
        self.limiter.side_effect = AppError("Limited", status_code=429, code="rate_limited")
        await batch.process_batch(OWNER_A, first.id)
        self.limiter.side_effect = None
        second_request = self.request.model_copy(update={"request_id": "request-batch-test-0002"})
        second = batch.create_batch(OWNER_A, second_request)
        with self.assertRaises(ConflictError):
            batch.retry_batch(OWNER_A, first.id)
        self.assertEqual(self.store.batch_snapshot(first.id, OWNER_A).status, "failed")
        self.assertEqual(self.store.batch_snapshot(second.id, OWNER_A).status, "pending")

    async def test_background_worker_processes_persisted_work_without_a_browser(self) -> None:
        created = batch.create_batch(OWNER_A, self.request)
        self.store = configure_store(self.database_path)

        async def wait_for_completion():
            while self.store.batch_snapshot(created.id, OWNER_A).status != "completed":
                await asyncio.sleep(0.01)

        try:
            await batch.start_worker()
            await asyncio.wait_for(wait_for_completion(), timeout=5)
        finally:
            await batch.stop_worker()
        self.assertEqual(len(self.store.list_history(OWNER_A)), 4)

    async def test_interrupted_work_resumes_from_persisted_outline_after_restart(self) -> None:
        self.fake.cancel_once = ("MSc Robotics", PS, "draft")
        created = batch.create_batch(OWNER_A, self.request)
        with self.assertRaises(asyncio.CancelledError):
            await batch.process_batch(OWNER_A, created.id)
        interrupted = self.store.batch_snapshot(created.id, OWNER_A)
        first_session = interrupted.items[0].session_id
        self.assertIsNotNone(first_session)
        before = self.fake.call_counts()
        self.store = configure_store(self.database_path)
        self.store.recover_batches()
        restored = self.store.batch_snapshot(created.id, OWNER_A)
        self.assertEqual(restored.status, "pending")
        await batch.process_batch(OWNER_A, created.id)
        completed = self.store.batch_snapshot(created.id, OWNER_A)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.items[0].session_id, first_session)
        self.assertEqual(self.fake.call_counts()[("MSc Robotics", PS, "analysis")], 1)
        self.assertEqual(self.fake.call_counts()[("MSc Robotics", PS, "outline")], 1)
        self.assertEqual(self.fake.call_counts()[("MSc Robotics", PS, "draft")], 2)
        self.assertGreater(len(self.fake.calls), sum(before.values()))
        self.assertEqual(len(self.store.session_snapshot(first_session, OWNER_A).versions), 2)

    async def test_retry_recovers_artifact_saved_before_its_session_update(self) -> None:
        for stage in ("outline", "draft"):
            with self.subTest(stage=stage):
                payload = batch_payload(self.profile.id)
                payload["request_id"] = f"artifact-before-session-{stage}"
                payload["directions"] = [payload["directions"][0]]
                payload["directions"][0]["essays"] = [payload["directions"][0]["essays"][0]]
                created = batch.create_batch(OWNER_A, BatchCreateRequest.model_validate(payload))
                original_save = self.store.save_session
                failed_once = False

                def fail_after_artifact(session):
                    nonlocal failed_once
                    reached_stage = bool(session.draft) if stage == "draft" else bool(session.outline)
                    if reached_stage and not failed_once:
                        failed_once = True
                        raise RuntimeError("Simulated interruption after the artifact was saved")
                    return original_save(session)

                with self.assertLogs("app.services.batch", level="ERROR"), patch.object(
                    self.store, "save_session", side_effect=fail_after_artifact
                ):
                    await batch.process_batch(OWNER_A, created.id)
                failed = self.store.batch_snapshot(created.id, OWNER_A)
                self.assertEqual(failed.status, "failed")
                session_id = failed.items[0].session_id
                interrupted = self.store.session_snapshot(session_id, OWNER_A)
                self.assertIsNone(getattr(interrupted, stage))
                self.assertTrue(any(version.artifact_type == stage for version in interrupted.versions))
                before = self.fake.call_counts()
                batch.retry_batch(OWNER_A, created.id)
                await batch.process_batch(OWNER_A, created.id)
                self.assertEqual(self.store.batch_snapshot(created.id, OWNER_A).status, "completed")
                restored = self.store.session_snapshot(session_id, OWNER_A)
                self.assertIsNotNone(restored.outline)
                self.assertTrue(restored.draft)
                self.assertEqual(len(restored.versions), 2)
                self.assertTrue(all(version.version_no == 1 for version in restored.versions))
                key = ("MSc Robotics", PS, stage)
                self.assertEqual(self.fake.call_counts()[key], before[key])

    async def test_deleted_history_is_not_recreated_by_inflight_generation(self) -> None:
        self.fake.pause_stage = "analysis"
        created = batch.create_batch(OWNER_A, self.request)
        task = asyncio.create_task(batch.process_batch(OWNER_A, created.id))
        await asyncio.wait_for(self.fake.entered.wait(), timeout=2)
        self.store.delete_history(OWNER_A)
        self.fake.release.set()
        await asyncio.wait_for(task, timeout=2)
        self.assertEqual(self.store.list_batches(OWNER_A), [])
        self.assertEqual(self.store.list_history(OWNER_A), [])
        self.assertIsNone(self.store.get_profile(self.profile.id, OWNER_A))

    async def test_unexpected_errors_are_sanitized_per_item_and_other_items_continue(self) -> None:
        created = batch.create_batch(OWNER_A, self.request)
        original = workflow.analyze_program
        calls = 0

        async def fail_first(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("private applicant data and secret implementation details")
            return await original(*args, **kwargs)

        with self.assertLogs("app.services.batch", level="ERROR"), patch.object(
            workflow, "analyze_program", fail_first
        ):
            await batch.process_batch(OWNER_A, created.id)
        result = self.store.batch_snapshot(created.id, OWNER_A)
        self.assertEqual(result.status, "partial_failed")
        self.assertEqual(sum(item.status == "completed" for item in result.items), 3)
        self.assertNotIn("private applicant", result.model_dump_json())
        self.assertNotIn("secret implementation", result.model_dump_json())


class BatchApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = configure_store(Path(self.temp_dir.name) / "api-batch.db")
        self.profile = self.store.save_profile(
            OWNER_A,
            ProfileData(basic_profile=BasicProfile(full_name="API Batch Applicant")),
        )
        # No lifespan: API contract tests persist queued work without launching a model worker.
        self.client = TestClient(app)
        self.headers = {"X-Client-Id": OWNER_A}
        self.other_headers = {"X-Client-Id": OWNER_B}

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_create_is_idempotent_and_conflicting_reuse_is_rejected(self) -> None:
        payload = batch_payload(self.profile.id)
        first = self.client.post("/api/batches", headers=self.headers, json=payload)
        self.assertEqual(first.status_code, 202, first.text)
        duplicate = self.client.post("/api/batches", headers=self.headers, json=payload)
        self.assertEqual(duplicate.status_code, 202, duplicate.text)
        self.assertEqual(duplicate.json()["id"], first.json()["id"])
        self.assertEqual(len(self.store.list_batches(OWNER_A)), 1)
        payload["directions"][0]["essays"][0]["word_limit"] = 700
        conflict = self.client.post("/api/batches", headers=self.headers, json=payload)
        self.assertEqual(conflict.status_code, 409, conflict.text)

    def test_owner_checks_apply_to_create_get_list_and_retry(self) -> None:
        payload = batch_payload(self.profile.id)
        created = self.client.post("/api/batches", headers=self.headers, json=payload)
        self.assertEqual(created.status_code, 202, created.text)
        batch_id = created.json()["id"]
        self.assertEqual(
            self.client.post("/api/batches", headers=self.other_headers, json=payload).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/api/batches/{batch_id}", headers=self.other_headers).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(f"/api/batches/{batch_id}/retry", headers=self.other_headers).status_code,
            404,
        )
        self.assertEqual(self.client.get("/api/batches", headers=self.other_headers).json(), [])
        listed = self.client.get("/api/batches", headers=self.headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["id"] for item in listed.json()], [batch_id])

    def test_validation_and_history_deletion_include_batches(self) -> None:
        response = self.client.post("/api/batches", json=batch_payload(self.profile.id))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "client_id_required")
        payload = batch_payload(self.profile.id)
        payload["directions"][0]["school_name"] = "   "
        response = self.client.post("/api/batches", headers=self.headers, json=payload)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "request_validation_failed")
        created = self.client.post(
            "/api/batches", headers=self.headers, json=batch_payload(self.profile.id)
        )
        self.assertEqual(created.status_code, 202, created.text)
        response = self.client.delete("/api/history", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/api/batches", headers=self.headers).json(), [])
        self.assertEqual(
            self.client.get(f"/api/batches/{created.json()['id']}", headers=self.headers).status_code,
            404,
        )

    def test_api_lifespan_starts_worker_and_returns_pollable_results(self) -> None:
        payload = batch_payload(self.profile.id)
        payload["directions"] = [payload["directions"][0]]
        payload["directions"][0]["essays"] = [payload["directions"][0]["essays"][0]]
        with patch.object(workflow, "client", RecordingClient()), patch.object(
            batch.model_rate_limiter, "check"
        ), TestClient(app) as running_client:
            created = running_client.post("/api/batches", headers=self.headers, json=payload)
            self.assertEqual(created.status_code, 202, created.text)
            batch_id = created.json()["id"]
            deadline = time.monotonic() + 5
            while True:
                response = running_client.get(f"/api/batches/{batch_id}", headers=self.headers)
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                if result["status"] not in {"pending", "running"}:
                    break
                if time.monotonic() >= deadline:
                    self.fail("The app lifespan did not process its queued batch")
                time.sleep(0.01)
            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["items"][0]["draft"])
            self.assertTrue(result["items"][0]["session_id"])


if __name__ == "__main__":
    unittest.main()
