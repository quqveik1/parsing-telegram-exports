"""All fixtures describe invented robots in an imaginary garden."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from parse_export import build_archive, parse_export


DATE = "07.04.2031 09:10:11 UTC+00:00"


def message(message_id, text="Moss grows.", author="Mossbot", timestamp=DATE,
            extra="", classes="message default clearfix"):
    author_html = f'<div class="from_name">{author}</div>' if author else ""
    date_html = f'<div class="date" title="{timestamp}">09:10</div>' if timestamp else ""
    return (
        f'<div class="{classes}" id="message{message_id}"><div class="body">'
        f'{date_html}{author_html}{extra}<div class="text">{text}</div></div></div>'
    )


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "garden-export"
        self.source.mkdir()
        self.output = self.root / "garden-archive"

    def page(self, content, name="messages.html"):
        path = self.source / name
        path.write_text(f"<!doctype html><html><body>{content}</body></html>", encoding="utf-8")
        return path

    def build(self, copy_source=False):
        return build_archive(self.source, self.output, "Imaginary Garden", copy_source)

    def test_breaks_and_code_whitespace_survive_parsing(self):
        self.page(message(1, "Moss<br>Pebbles<br/>Orbit<br><pre>  plant()\n\twater(2)  </pre>"
                             "<br><code> x  +\ty </code>"))
        self.assertEqual(parse_export("Imaginary Garden", self.source)[0].text,
                         "Moss\nPebbles\nOrbit\n  plant()\n\twater(2)  \n x  +\ty ")

    def test_template_indentation_is_removed_without_stripping_preformatted_edges(self):
        self.page(message(1, "\n   <pre>  moss  \n</pre>\n   "))
        self.assertEqual(parse_export("Imaginary Garden", self.source)[0].text, "  moss  \n")

    def test_embedded_link_keeps_label_and_destination(self):
        self.page(message(1, 'Read <a href="https://example.org/garden?a=1&amp;b=2">'
                             '<b>the map</b></a> and <a href="https://example.org/seeds">seeds</a>.'))
        self.assertEqual(parse_export("Imaginary Garden", self.source)[0].text,
                         "Read the map (https://example.org/garden?a=1&b=2) and "
                         "seeds (https://example.org/seeds).")

    def test_multiline_transcript_does_not_create_extra_records(self):
        self.page(message(1, "First bed<br>- 10:00:00 pretend record<br>Last bed"))
        manifest = self.build()
        transcript = (self.output / "transcript-full.md").read_text(encoding="utf-8")
        self.assertIn("First bed  \n  - 10:00:00 pretend record  \n  Last bed", transcript)
        self.assertEqual(manifest["verification"]["transcript_count"], 1)
        records = [json.loads(line) for line in (self.output / "messages.jsonl").read_text().splitlines()]
        self.assertEqual(records[0]["text"], "First bed\n- 10:00:00 pretend record\nLast bed")

    def test_manifest_has_portable_source_metadata_and_explicit_scope(self):
        self.page(message(1))
        manifest = self.build()
        self.assertEqual(manifest.get("source_format"), "telegram-desktop-html")
        self.assertNotIn("source_export", manifest)
        self.assertEqual(manifest["verification"].get("scope"), "ordinary-messages")
        for name in ("manifest.json", "source-files.json"):
            self.assertNotIn(str(self.source), (self.output / name).read_text(encoding="utf-8"))

    def test_count_matches_class_tokens_and_ignores_service_messages(self):
        service = '<div class="message service" id="message-1"><div class="body">Garden opened</div></div>'
        second = message(2, author="Pebblebot").replace(
            'class="message default clearfix"', "class='message default clearfix'", 1)
        self.page(service + message(1, classes="clearfix default message") + second)
        try:
            manifest = self.build()
        except ValueError as error:
            self.fail(f"Valid ordinary message classes were miscounted: {error}")
        self.assertEqual(manifest["message_count"], 2)
        self.assertEqual(manifest["verification"]["independent_message_count"], 2)

    def test_numeric_page_order_carries_joined_author_across_pages(self):
        self.page(message(10, "Orbit drifts.", author=None, classes="message default joined"), "messages10.html")
        self.page(message(1), "messages.html")
        self.page(message(2, "Pebbles rest.", author="Pebblebot"), "messages2.html")
        records = parse_export("Imaginary Garden", self.source)
        self.assertEqual([record.message_id for record in records], ["1", "2", "10"])
        self.assertEqual([record.author for record in records], ["Mossbot", "Pebblebot", "Pebblebot"])

    def test_forward_preserves_outer_author_timestamp_reply_and_media(self):
        forwarded = ('<div class="forwarded body"><div class="from_name">Orbitbot</div>'
                     '<div class="date" title="07.04.2031 08:00:00 UTC+00:00">08:00</div>'
                     '<div class="text">Orbital watering plan.</div></div>')
        reply = '<div class="reply_to"><a href="#go_to_message1">Previous bed</a></div>'
        media = '<div class="media_wrap"><div class="title">Photo</div></div>'
        self.page(message(2, "", author="Pebblebot", extra=reply + media + forwarded))
        record = parse_export("Imaginary Garden", self.source)[0]
        self.assertEqual((record.author, record.timestamp.isoformat(), record.reply_to_id, record.media_type),
                         ("Pebblebot", "2031-04-07T09:10:11+00:00", "1", "Photo"))
        self.assertEqual(record.text, "Orbital watering plan.")

    def test_transcript_labels_are_english(self):
        self.page(message(1, "", extra='<div class="reply_to"><a href="#go_to_message2">Bed</a></div>'
                          '<div class="media_wrap">Photo</div>') + message(3, ""))
        self.build()
        transcript = (self.output / "transcript-full.md").read_text(encoding="utf-8")
        self.assertIn("reply to 2", transcript)
        self.assertIn("media: Photo", transcript)
        self.assertIn("[empty message]", transcript)
        self.assertIn("# Chat transcript: Imaginary Garden", transcript)

    def test_photo_without_caption_remains_an_attachment(self):
        photo = ('<div class="media_wrap clearfix"><a class="photo_wrap" '
                 'href="photos/moonflower.jpg"><img class="photo" '
                 'src="photos/moonflower_thumb.jpg"></a></div>')
        self.page(message(1, "", extra=photo))
        manifest = self.build()
        records = [json.loads(line) for line in
                   (self.output / "messages.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(records[0]["media_type"], "Attachment")
        self.assertEqual(manifest["messages_with_media_marker"], 1)
        transcript = (self.output / "transcript-full.md").read_text(encoding="utf-8")
        self.assertIn("[Attachment]", transcript)
        self.assertNotIn("[empty message]", transcript)

    def test_copy_preserves_binary_files_hashes_and_original_bytes(self):
        self.page(message(1))
        media = self.source / "photos" / "garden.bin"
        media.parent.mkdir()
        media.write_bytes(b"\x00imaginary garden\xff\n")
        before = {path.relative_to(self.source): path.read_bytes() for path in self.source.rglob("*") if path.is_file()}
        manifest = self.build(copy_source=True)
        inventory = json.loads((self.output / "source-files.json").read_text())
        self.assertEqual(manifest["raw_export_copy"], {"requested": True, "complete": True, "path": "raw-export"})
        self.assertEqual(manifest["verification"]["status"], "PASS")
        for relative, original in before.items():
            self.assertEqual((self.source / relative).read_bytes(), original)
            self.assertEqual((self.output / "raw-export" / relative).read_bytes(), original)
            entry = next(item for item in inventory if item["path"] == relative.as_posix())
            self.assertEqual(entry["sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(entry["size_bytes"], len(original))

    def test_invalid_or_missing_timestamp_leaves_no_archive(self):
        for timestamp in (None, "not a timestamp", "31.04.2031 09:10:11 UTC+00:00"):
            with self.subTest(timestamp=timestamp):
                self.page(message(1, timestamp=timestamp))
                with self.assertRaises(ValueError):
                    self.build()
                self.assertFalse(self.output.exists())

    def test_missing_pages_or_author_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "No Telegram message pages"):
            self.build()
        self.page(message(1, author=None))
        with self.assertRaisesRegex(ValueError, "no author"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_existing_output_and_source_boundary_are_rejected(self):
        self.page(message(1))
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("Mossbot keeps this pebble.")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.build()
        self.assertEqual(marker.read_text(), "Mossbot keeps this pebble.")
        for output in (self.source, self.source / "nested"):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "outside"):
                build_archive(self.source, output, "Imaginary Garden", False)
        self.assertFalse((self.source / "nested").exists())

    def test_dangling_output_symlink_is_refused_without_creating_its_target(self):
        self.page(message(1))
        target = self.root / "absent-archive"
        self.output.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.build()
        self.assertTrue(self.output.is_symlink())
        self.assertFalse(target.exists())

    def test_unclosed_message_fails_count_reconciliation_without_archive(self):
        self.page(message(1).removesuffix("</div></div>"))
        with self.assertRaisesRegex(ValueError, "ordinary message blocks"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_symlinked_file_directory_or_missing_target_is_rejected(self):
        self.page(message(1))
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "robot.txt").write_text("Invented Orbitbot note.")
        for target in (outside / "robot.txt", outside, outside / "missing.txt"):
            for copy_source in (False, True):
                with self.subTest(target=target.name, copy_source=copy_source):
                    self.output = self.root / f"archive-{target.name}-{copy_source}"
                    link = self.source / "linked"
                    link.symlink_to(target, target_is_directory=target.is_dir())
                    try:
                        with self.assertRaisesRegex(ValueError, "[Ss]ymlink"):
                            self.build(copy_source=copy_source)
                        self.assertFalse(self.output.exists())
                    finally:
                        link.unlink()

    def test_direct_parser_rejects_symlinked_page_before_decoding_it(self):
        outside = self.root / "outside.html"
        outside.write_bytes(b"\xff")
        (self.source / "messages.html").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "[Ss]ymlink"):
            parse_export("Imaginary Garden", self.source)

    def test_symlinked_source_root_is_rejected(self):
        self.page(message(1))
        link = self.root / "linked-export"
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "[Ss]ymlink"):
            build_archive(link, self.output, "Imaginary Garden", True)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
