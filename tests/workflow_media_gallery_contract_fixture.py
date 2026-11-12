"""The shared kaliv-media-gallery/v1 fixture against the Python catalog (#2275 backlog item 19).

contracts/kaliv-media-gallery-v1-fixtures.json is shared with the Android parser
(MediaGalleryContractFixtureTest) and with any server catalog (Go, #2365). Its `page` is what
list_gallery returns for its `index`; this test keeps that true, so the file can serve as the
other implementations' oracle.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.media_gallery_catalog import GalleryUnavailable, list_gallery

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "contracts" / "kaliv-media-gallery-v1-fixtures.json").read_text(encoding="utf-8"))


class GalleryContractFixtureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def page(self, entries, **kwargs):
        (self.root / "gallery-index.json").write_text(json.dumps(entries), encoding="utf-8")
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            return list_gallery(self.root, **kwargs)

    def test_the_fixture_header(self):
        self.assertEqual(FIXTURE["schema"], "kaliv-media-gallery-fixtures/v1")
        self.assertEqual(FIXTURE["contract"], "kaliv-media-gallery/v1")
        self.assertEqual(FIXTURE["page"]["schema"], FIXTURE["contract"])

    def test_the_catalog_emits_exactly_the_fixture_page(self):
        self.assertEqual(self.page(FIXTURE["index"], limit=100), FIXTURE["page"])

    def test_pagination_splits_the_same_items_by_id_cursor(self):
        items, cursor, pages = [], None, 0
        while True:
            page = self.page(FIXTURE["index"], limit=2, **({"cursor": cursor} if cursor else {}))
            items += page["items"]
            pages += 1
            cursor = page["next_cursor"]
            if cursor is None:
                break
            self.assertEqual(cursor, page["items"][-1]["id"])
        self.assertEqual(pages, 3)
        self.assertEqual(items, FIXTURE["page"]["items"])

    def test_every_item_carries_the_fields_android_requires(self):
        # MediaGalleryContract.parseItem skips an item without any of these (6808439108 P1-1).
        required = {"id", "kind", "mime_type", "created_at", "size_bytes", "width", "height",
                    "duration_seconds", "projection", "stereo", "thumbnail_id", "thumbnail_url",
                    "url", "playback"}
        for item in FIXTURE["page"]["items"]:
            with self.subTest(item=item["id"]):
                self.assertEqual(set(item), required)
                self.assertEqual(item["url"], f"/api/v1/media/{item['id']}")
                self.assertIsInstance(item["playback"]["supports_range"], bool)

    def test_every_invalid_index_entry_is_refused_with_its_code(self):
        self.assertTrue(FIXTURE["invalid_index"])
        for case in FIXTURE["invalid_index"]:
            with self.subTest(case=case["name"]):
                with self.assertRaises(GalleryUnavailable) as raised:
                    self.page([case["entry"]])
                self.assertEqual(str(raised.exception), case["python_error"])

    def test_no_invalid_item_is_something_the_catalog_emits(self):
        emitted = FIXTURE["page"]["items"]
        for case in FIXTURE["invalid_items"]:
            with self.subTest(case=case["name"]):
                self.assertNotIn(case["item"], emitted)


if __name__ == "__main__":
    unittest.main()
