from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.schemas import BasicProfile, ProfileData
from app.services.store import SQLiteStore


class StoreTests(unittest.TestCase):
    def test_profile_persists_across_store_instances_and_is_owner_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "persistent.db"
            first = SQLiteStore(path)
            record = first.save_profile(
                "client-aaaaaaaaaaaaaaaa",
                ProfileData(
                    basic_profile=BasicProfile(
                        full_name="Persistent Applicant",
                        target_field="Data Science",
                    )
                ),
            )

            second = SQLiteStore(path)
            loaded = second.get_profile(
                record.id,
                "client-aaaaaaaaaaaaaaaa",
            )
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.profile.basic_profile.full_name, "Persistent Applicant")
            self.assertIsNone(
                second.get_profile(record.id, "client-bbbbbbbbbbbbbbbb")
            )
