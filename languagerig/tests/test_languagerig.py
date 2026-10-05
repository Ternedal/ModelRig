from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape
from zipfile import ZipFile

from languagerig.cli import main
from languagerig.core import LanguageRigError, books, digest, init_workspace, label_book, read_json, write_json, write_jsonl
from languagerig.corpus import build_dataset, chunks, grouped_sources, verify_dataset
from languagerig.evaluate import check_response, evaluate
from languagerig.ingest import extract_epub, extract_pdf, import_books
from languagerig.integrate import export_rag, merge_adapter, package_model, publish_rag, register_model, validate_url
from languagerig.train import encode_batch, run_training, training_plan


def epub(path: Path, title: str, *, texts=None, language="da", encrypted=None, reverse=False):
    texts = texts or [f"<h1>{title}</h1><p>" + (f"Dette er indhold fra værket {title}. " * 18) + "</p>"]
    container = '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>'
    manifest = '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
    manifest += "".join(f'<item id="c{i}" href="chapter{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(len(texts)))
    spine = '<itemref idref="nav"/>' + "".join(f'<itemref idref="c{i}"/>' for i in range(len(texts)))
    package = f'<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{escape(title)}</dc:title><dc:creator>Testforfatter</dc:creator><dc:language>{language}</dc:language></metadata><manifest>{manifest}</manifest><spine>{spine}</spine></package>'
    with ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/book.opf", package)
        z.writestr("OEBPS/nav.xhtml", "<html><nav>INDEKS SKAL IKKE MED</nav></html>")
        for i in reversed(range(len(texts))) if reverse else range(len(texts)):
            z.writestr(f"OEBPS/chapter{i}.xhtml", "<html><body>" + texts[i] + "</body></html>")
        if encrypted:
            z.writestr("META-INF/encryption.xml", f'<encryption><EncryptedData><CipherData><CipherReference URI="{encrypted}"/></CipherData></EncryptedData></encryption>')


def pdf(path: Path, lines: list[str]):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    for line in lines:
        page = writer.add_blank_page(width=500, height=500)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 20 450 Td (HEADER) Tj 0 -20 Td ({line}) Tj 0 -20 Td (FOOTER) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata({"/Title": "PDF-eksempel", "/Author": "Testforfatter"})
    with path.open("wb") as file:
        writer.write(file)


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.input = self.root / "input"
        self.input.mkdir()
        init_workspace(self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def corpus(self, count=6):
        for i in range(count):
            epub(self.input / f"book{i}.epub", f"Unikt værk {i}")
        result = import_books(self.workspace, self.input, training_allowed=True)
        self.assertEqual(len(result["imported"]), count)
        return build_dataset(self.workspace, "pilot")

    def config(self):
        self.corpus()
        path = self.workspace / "train.json"
        write_json(path, {"dataset": "datasets/pilot", "output_dir": "runs/pilot"})
        return path


class ImportTests(WorkspaceCase):
    def test_spine_order_is_independent_of_zip_order(self):
        path = self.input / "book.epub"
        epub(path, "Orden", texts=["<h1>Første</h1><p>Et</p>", "<h1>Andet</h1><p>To</p>"], reverse=True)
        row = extract_epub(path)
        self.assertEqual([s["title"] for s in row["sections"]], ["Første", "Andet"])
        self.assertNotIn("INDEKS", str(row["sections"]))

    def test_preserves_danish_and_omits_scripts_hidden_and_nav(self):
        path = self.input / "book.epub"
        epub(path, "Dansk", texts=['<h1>Æøå</h1><p>Blå &amp; grøn.</p><script>BAD</script><span hidden>HIDDEN</span><nav>NAV</nav>'])
        text = extract_epub(path)["sections"][0]["text"]
        self.assertIn("Æøå", text)
        self.assertIn("Blå & grøn.", text)
        for word in ("BAD", "HIDDEN", "NAV"):
            self.assertNotIn(word, text)

    def test_font_encryption_is_allowed_but_text_encryption_is_not(self):
        font = self.input / "font.epub"
        epub(font, "Font", encrypted="OEBPS/font.otf")
        self.assertTrue(extract_epub(font)["sections"])
        protected = self.input / "protected.epub"
        epub(protected, "DRM", encrypted="OEBPS/chapter0.xhtml")
        with self.assertRaises(LanguageRigError):
            extract_epub(protected)

    def test_archive_escape_is_rejected(self):
        path = self.input / "bad.epub"
        with ZipFile(path, "w") as z:
            z.writestr("META-INF/container.xml", '<container><rootfile full-path="../../book.opf"/></container>')
        with self.assertRaises(LanguageRigError):
            extract_epub(path)

    def test_dtd_is_rejected(self):
        path = self.input / "bad.epub"
        with ZipFile(path, "w") as z:
            z.writestr("META-INF/container.xml", '<!DOCTYPE x [<!ENTITY test "abc">]><container/>')
        with self.assertRaises(LanguageRigError):
            extract_epub(path)

    def test_metadata_entity_and_file_size_limits(self):
        path = self.input / "book.epub"
        epub(path, "En titel & et emne")
        self.assertEqual(extract_epub(path)["title"], "En titel & et emne")
        with patch("languagerig.ingest.MAX_FILE_BYTES", 1):
            result = import_books(self.workspace, path)
        self.assertEqual(len(result["errors"]), 1)

    def test_reimport_is_idempotent_and_new_copy_is_marked(self):
        path = self.input / "first.epub"
        epub(path, "Kopi")
        self.assertEqual(len(import_books(self.workspace, path)["imported"]), 1)
        self.assertEqual(len(import_books(self.workspace, path)["skipped"]), 1)
        other = self.input / "other.epub"
        epub(other, "Kopi", reverse=True)
        # Change bytes without changing the extracted book.
        with ZipFile(other, "a") as z:
            z.writestr("extra.txt", "not in the spine")
        result = import_books(self.workspace, other)
        self.assertIsNotNone(result["imported"][0]["duplicate_of"])

    def test_pdf_preserves_pages_and_removes_repeated_edges(self):
        path = self.input / "book.pdf"
        pdf(path, ["First page unique text", "Second page unique text", "Third page unique text"])
        row = extract_pdf(path)
        self.assertEqual(len(row["sections"]), 3)
        self.assertEqual(row["sections"][1]["location"], "page:2")
        self.assertNotIn("HEADER", str(row["sections"]))
        self.assertNotIn("FOOTER", str(row["sections"]))
        self.assertIn("Second page", row["sections"][1]["text"])

    def test_bad_pdf_does_not_stop_valid_epub_import(self):
        (self.input / "bad.pdf").write_bytes(b"not a pdf")
        epub(self.input / "good.epub", "God bog")
        result = import_books(self.workspace, self.input)
        self.assertEqual(len(result["imported"]), 1)
        self.assertEqual(len(result["errors"]), 1)

    def test_scan_only_pdf_is_not_reported_as_success(self):
        from pypdf import PdfWriter
        path = self.input / "scan.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=500, height=500)
        with path.open("wb") as stream:
            writer.write(stream)
        result = import_books(self.workspace, path)
        self.assertFalse(result["imported"])
        self.assertEqual(len(result["errors"]), 1)

    def test_inventory_does_not_dump_text_and_label_is_bounded(self):
        epub(self.input / "book.epub", "Katalog")
        import_books(self.workspace, self.input)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--workspace", str(self.workspace), "inventory"]), 0)
        rows = json.loads(output.getvalue())
        self.assertNotIn("sections", rows[0])
        row = label_book(self.workspace, rows[0]["source_id"], genre="nonfiction", topics=["arkitektur"])
        self.assertEqual(row["topics"], ["arkitektur"])
        with self.assertRaises(LanguageRigError):
            label_book(self.workspace, "../../escape", genre="fiction")


class CorpusTests(WorkspaceCase):
    def test_splits_are_book_bound_deterministic_and_verified(self):
        first = self.corpus()
        second = build_dataset(self.workspace, "second")
        self.assertEqual(first["split_by_source"], second["split_by_source"])
        self.assertEqual(first["dataset_sha256"], second["dataset_sha256"])
        self.assertEqual(verify_dataset(self.workspace / "datasets/pilot")["counts"], first["counts"])
        self.assertEqual(set(first["split_by_source"].values()), {"train", "validation", "test"})

    def test_snapshot_cannot_be_overwritten_and_tampering_is_detected(self):
        self.corpus()
        with self.assertRaises(LanguageRigError):
            build_dataset(self.workspace, "pilot")
        path = self.workspace / "datasets/pilot/train.jsonl"
        path.write_text(path.read_text(encoding="utf-8") + "\n{}\n", encoding="utf-8")
        with self.assertRaises(LanguageRigError):
            verify_dataset(path.parent)

    def test_editions_and_equal_content_are_transitively_grouped(self):
        rows = [
            {"source_id": "a", "work_id": "one", "content_sha256": "x"},
            {"source_id": "b", "work_id": "one", "content_sha256": "y"},
            {"source_id": "c", "work_id": "two", "content_sha256": "y"},
            {"source_id": "d", "work_id": "three", "content_sha256": "z"},
        ]
        groups = grouped_sources(rows)
        self.assertEqual(sorted(len(g) for g in groups), [1, 3])

    def test_unselected_non_danish_and_quality_review_material_is_excluded(self):
        self.corpus()
        epub(self.input / "english.epub", "English", language="en")
        english = import_books(self.workspace, self.input / "english.epub", training_allowed=True)["imported"][0]
        first = next(book for book in books(self.workspace) if book["language"] == "da")
        label_book(self.workspace, first["source_id"], training_allowed=False)
        manifest = build_dataset(self.workspace, "filtered")
        reasons = {e["source_id"]: e["reason"] for e in manifest["excluded"]}
        self.assertEqual(reasons[english["source_id"]], "language_not_danish")
        self.assertEqual(reasons[first["source_id"]], "training_not_selected")

    def test_fewer_than_three_works_cannot_claim_held_out_evaluation(self):
        for i in range(2):
            epub(self.input / f"{i}.epub", f"Værk {i}")
        import_books(self.workspace, self.input, training_allowed=True)
        with self.assertRaises(LanguageRigError):
            build_dataset(self.workspace, "too-small")

    def test_shared_passage_is_removed_from_all_splits(self):
        common = "Fælles indledning som skal fjernes fra alle datasæt. " * 8
        for i in range(6):
            epub(self.input / f"{i}.epub", f"Værk {i}", texts=[
                "<p>" + common + "</p>", "<p>" + (f"Unikt indhold {i}. " * 20) + "</p>"])
        import_books(self.workspace, self.input, training_allowed=True)
        manifest = build_dataset(self.workspace, "dedup")
        self.assertEqual(manifest["duplicate_passages_removed"], 6)
        verify_dataset(self.workspace / "datasets/dedup")
        for path in (self.workspace / "datasets/dedup").glob("*.jsonl"):
            self.assertNotIn("Fælles indledning", path.read_text(encoding="utf-8"))

    def test_instructions_require_review_and_cannot_cross_splits(self):
        manifest = self.corpus()
        samples = self.root / "instructions.jsonl"
        rows = [{"reviewed": True, "source_ids": [source],
                 "messages": [{"role": "user", "content": "Forklar " + source},
                              {"role": "assistant", "content": "Svar fra " + source}]}
                for source in manifest["split_by_source"]]
        write_jsonl(samples, rows)
        instruction = build_dataset(self.workspace, "instruction", instructions=samples)
        self.assertEqual(instruction["mode"], "instruction")
        verify_dataset(self.workspace / "datasets/instruction")
        rows[0]["reviewed"] = False
        write_jsonl(samples, rows)
        with self.assertRaises(LanguageRigError):
            build_dataset(self.workspace, "unreviewed", instructions=samples)
        rows[0]["reviewed"] = True
        rows[0]["source_ids"] = list(manifest["split_by_source"])
        write_jsonl(samples, rows)
        with self.assertRaises(LanguageRigError):
            build_dataset(self.workspace, "crossed", instructions=samples)

    def test_bad_names_fractions_and_chunk_size_are_rejected(self):
        self.corpus()
        for kwargs in ({"name": "../escape"}, {"name": "nan", "test_fraction": float("nan")},
                       {"name": "fractions", "validation_fraction": 0.7, "test_fraction": 0.6},
                       {"name": "size", "chunk_chars": 0}):
            with self.assertRaises(LanguageRigError):
                build_dataset(self.workspace, **kwargs)
        pieces = list(chunks(" ".join(["abcdef"] * 300), 200))
        self.assertTrue(all(len(piece) <= 200 for piece in pieces))
        self.assertEqual(" ".join(pieces), " ".join(["abcdef"] * 300))


class FakeTokenizer:
    eos_token_id = 999
    def __call__(self, text, **kwargs):
        return {"input_ids": [ord(char) for char in text]}
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        tokens = []
        for message in messages:
            tokens += [1 if message["role"] == "user" else 2]
            tokens += [ord(char) for char in message["content"]] + [3]
        return tokens + ([2] if add_generation_prompt else [])


class TrainingTests(WorkspaceCase):
    def test_plan_requires_no_gpu_or_download_and_resolves_paths(self):
        config = self.config()
        plan = run_training(config)
        self.assertEqual(plan["status"], "planned")
        self.assertFalse(plan["model_downloaded"])
        self.assertFalse(plan["training_executed"])
        self.assertEqual(Path(plan["config"]["dataset"]), (self.workspace / "datasets/pilot").resolve())
        self.assertFalse((self.workspace / "runs/pilot").exists())

    def test_training_rejects_unknown_configuration_and_changed_dataset(self):
        config = self.config()
        write_json(config, {"dataset": "datasets/pilot", "output_dir": "runs/pilot", "unsupported": True})
        with self.assertRaises(LanguageRigError):
            training_plan(config)
        config.write_text(json.dumps({"dataset": "datasets/pilot", "output_dir": "runs/pilot",
                                     "learning_rate": float("inf")}), encoding="utf-8")
        with self.assertRaises(LanguageRigError):
            training_plan(config)
        write_json(config, {"dataset": "datasets/pilot", "output_dir": "runs/pilot"})
        file = self.workspace / "datasets/pilot/validation.jsonl"
        file.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(LanguageRigError):
            training_plan(config)

    def test_text_windowing_does_not_truncate_long_books(self):
        text = "Dansk tekst som er længere end ét vindue."
        encoded = encode_batch({"text": [text]}, FakeTokenizer(), "text", 10)
        self.assertEqual([token for row in encoded["input_ids"] for token in row], [ord(c) for c in text] + [999])
        self.assertTrue(all(len(row) <= 10 for row in encoded["input_ids"]))

    def test_instruction_labels_mask_prompt_and_reject_truncation(self):
        messages = [{"role": "user", "content": "Hej"}, {"role": "assistant", "content": "Svar"}]
        tokenizer = FakeTokenizer()
        result = encode_batch({"messages": [messages]}, tokenizer, "instruction", 100)
        prefix = tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True)
        self.assertEqual(result["labels"][0][:len(prefix)], [-100] * len(prefix))
        self.assertTrue(any(token != -100 for token in result["labels"][0]))
        with self.assertRaises(LanguageRigError):
            encode_batch({"messages": [messages]}, tokenizer, "instruction", 4)


@contextlib.contextmanager
def service(*, fail_post=None, drift=False):
    calls = []
    state = {"tags": 0, "posts": 0}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def send(self, value, status=200):
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            state["tags"] += 1
            self.send({"models": [{"name": "baseline:test", "digest": "aaa"},
                                  {"name": "candidate:test", "digest": "changed" if drift and state["tags"] > 1 else "bbb"}]})
        def do_POST(self):
            state["posts"] += 1
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, body, self.headers.get("Authorization")))
            if fail_post == state["posts"]:
                self.send({"error": "fixture failure"}, 500)
            elif self.path == "/api/chat":
                self.send({"done": True, "message": {"content": "<script>test</script>" if "<script>" in body["messages"][-1]["content"] else "OK"}})
            else:
                self.send({"chunks": 1})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class IntegrationTests(WorkspaceCase):
    def test_rag_payload_matches_existing_modelrig_api_and_is_replayable(self):
        self.corpus(3)
        target = self.workspace / "exports/rag"
        exported = export_rag(self.workspace, target)
        self.assertEqual(len(exported["sources"]), 3)
        with service() as (url, calls):
            receipt = publish_rag(target, url=url, token="fixture-token")
            self.assertEqual(receipt["status"], "published")
            self.assertEqual(len(calls), 3)
            self.assertEqual(calls[0][0], "/api/v1/rag/ingest")
            self.assertEqual(calls[0][2], "Bearer fixture-token")
            payload = calls[0][1]
            self.assertEqual(set(payload), {"documents", "chunk_size", "overlap"})
            self.assertIn("OEBPS/chapter0.xhtml", payload["documents"][0]["source"])
            publish_rag(target, url=url, token="fixture-token")
            self.assertEqual(calls[3][1], payload)
        self.assertNotIn("fixture-token", (target / "publish.json").read_text())

    def test_rag_checksum_is_checked_before_any_request(self):
        self.corpus(3)
        target = self.workspace / "exports/rag"
        exported = export_rag(self.workspace, target)
        file = target / next(iter(exported["files"]))
        file.write_text("{}", encoding="utf-8")
        with service() as (url, calls):
            with self.assertRaises(LanguageRigError):
                publish_rag(target, url=url, token="fixture")
            self.assertFalse(calls)

    def test_partial_rag_publish_has_a_truthful_receipt(self):
        self.corpus(3)
        target = self.workspace / "exports/rag"
        export_rag(self.workspace, target)
        with service(fail_post=2) as (url, calls):
            with self.assertRaises(LanguageRigError):
                publish_rag(target, url=url, token="fixture")
        receipt = read_json(target / "publish.json")
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(len(receipt["completed_files"]), 1)

    def test_model_package_cannot_register_tampered_modelfile(self):
        run = self.workspace / "runs/test"
        write_json(run / "run.json", {"format": "languagerig-run/v1", "status": "trained",
                                     "config": {"model_id": "fixture/model"}, "resolved_revision": "abc",
                                     "dataset_sha256": "fixture"})
        gguf = self.root / "fixture.gguf"
        gguf.write_bytes(b"GGUF" + (3).to_bytes(4, "little"))
        packaged = package_model(self.workspace, run, gguf, "kaliv-dansk:v1")
        self.assertFalse(packaged["production_activation"])
        self.assertEqual(packaged["quality_improvement"], "not_measured")
        target = self.workspace / "exports/kaliv-dansk-v1"
        (target / "Modelfile").write_text("FROM an-unrelated-model")
        with patch("languagerig.integrate.subprocess.run") as command:
            with self.assertRaises(LanguageRigError):
                register_model(target, "http://127.0.0.1:11435")
            command.assert_not_called()
        plan = merge_adapter(run, self.root / "merged")
        self.assertFalse(plan["executed"])

    def test_loopback_evaluation_rejects_cloud_and_url_credentials(self):
        for url in ("https://ollama.com", "http://user:secret@localhost:11434", "file:///tmp/x", "http://localhost:11434/path"):
            with self.assertRaises(LanguageRigError):
                validate_url(url, loopback=True)
        self.assertEqual(validate_url("http://127.0.0.1:11435/", loopback=True), "http://127.0.0.1:11435")


class EvaluationTests(WorkspaceCase):
    def cases(self):
        path = self.root / "cases.jsonl"
        write_jsonl(path, [{"id": "format", "prompt": "Svar OK", "checks": [{"kind": "exact", "value": "OK"}]},
                          {"id": "escape", "prompt": "<script>tekst</script>", "checks": []}])
        return path

    def test_local_comparison_records_digests_checks_and_escaped_html(self):
        with service() as (url, calls):
            result = evaluate(self.cases(), self.root / "comparison", url=url,
                              baseline="baseline:test", candidate="candidate:test")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["automatic_checks"]["candidate:test"], {"passed": 1, "total": 1})
        self.assertEqual(result["quality_improvement"], "not_determined")
        self.assertFalse(result["tool_calling_qualified"])
        self.assertEqual(len(calls), 4)
        page = (self.root / "comparison/comparison.html").read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertTrue(all(call[1]["keep_alive"] == 0 for call in calls))

    def test_model_drift_and_partial_failures_are_not_green(self):
        for index, kwargs in enumerate(({"drift": True}, {"fail_post": 2})):
            target = self.root / f"comparison{index}"
            with service(**kwargs) as (url, calls):
                with self.assertRaises(LanguageRigError):
                    evaluate(self.cases(), target, url=url, baseline="baseline:test", candidate="candidate:test")
            self.assertEqual(read_json(target / "comparison.json")["status"], "failed")

    def test_book_questions_cannot_use_training_sources(self):
        manifest = self.corpus()
        train_source = next(source for source, split in manifest["split_by_source"].items() if split == "train")
        path = self.root / "leak.jsonl"
        write_jsonl(path, [{"id": "leak", "prompt": "Forklar bogen", "source_ids": [train_source]}])
        with service() as (url, calls):
            with self.assertRaises(LanguageRigError):
                evaluate(path, self.root / "comparison", url=url, baseline="baseline:test",
                         candidate="candidate:test", dataset=self.workspace / "datasets/pilot")
            self.assertFalse(calls)

    def test_response_checks_reject_invalid_json_and_unknown_types(self):
        self.assertFalse(check_response("not json", [{"kind": "json_keys", "value": ["svar"]}])[0]["passed"])
        self.assertTrue(check_response('{"svar":"hej"}', [{"kind": "json_keys", "value": ["svar"]}])[0]["passed"])
        with self.assertRaises(LanguageRigError):
            check_response("OK", [{"kind": "unsupported", "value": "OK"}])

    def test_invalid_duplicate_cases_fail_before_inference(self):
        path = self.cases()
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows.append(rows[0])
        write_jsonl(path, rows)
        with service() as (url, calls):
            with self.assertRaises(LanguageRigError):
                evaluate(path, self.root / "comparison", url=url, baseline="baseline:test", candidate="candidate:test")
            self.assertFalse(calls)


if __name__ == "__main__":
    unittest.main()
