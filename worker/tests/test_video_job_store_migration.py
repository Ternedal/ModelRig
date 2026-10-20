"""Regression for SQLite prompt_id migration and job creation."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.video_contract import VideoRequest
from app.video_job_store import VideoJobStore


class VideoJobStoreMigrationTests(unittest.TestCase):
    def test_new_database_accepts_job_after_prompt_id_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            store = VideoJobStore(Path(directory) / "jobs.sqlite")
            job_id = store.create(VideoRequest(kind="text_to_video", prompt="Clouds"))
            self.assertEqual(store.get(job_id)["state"], "queued")
            self.assertIsNone(store.get(job_id)["prompt_id"])

    def test_existing_seven_column_database_is_upgraded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.sqlite"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE video_jobs (job_id TEXT PRIMARY KEY, state TEXT NOT NULL, request_json TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, artifact_id TEXT, error_code TEXT)")
            store = VideoJobStore(path)
            job_id = store.create(VideoRequest(kind="text_to_video", prompt="Clouds"))
            self.assertTrue(store.transition(job_id, "queued", "running"))
            self.assertTrue(store.record_prompt(job_id, "prompt_1"))
            self.assertEqual(store.get(job_id)["prompt_id"], "prompt_1")


if __name__ == "__main__":
    unittest.main()
