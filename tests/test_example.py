import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]


class FictionalExampleTests(unittest.TestCase):
    def test_documented_example_preserves_six_robot_messages(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "demo"
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY / "scripts/parse_export.py"),
                    str(REPOSITORY / "examples/robot-garden"),
                    str(output),
                    "--chat-name", "Robot Garden",
                    "--copy-source",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["message_count"], 6)
            self.assertEqual(manifest["unique_authors"], 3)
            self.assertEqual(manifest["verification"]["status"], "PASS")
            self.assertEqual(manifest["first_timestamp"], "2031-04-07T09:00:00+00:00")
            self.assertEqual(manifest["last_timestamp"], "2031-04-08T08:00:00+00:00")
            records = [
                json.loads(line)
                for line in (output / "messages.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([row["message_id"] for row in records], ["101", "102", "103", "104", "105", "106"])
            self.assertEqual([row["author"] for row in records], ["Mossbot", "Mossbot", "Mossbot", "Pebblebot", "Orbitbot", "Orbitbot"])
            self.assertEqual(records[0]["text"], "The moonflower pots are ready.\nLet us give each pot a tiny umbrella.")
            self.assertIn("https://example.org/robot-garden/seed-map", records[1]["text"])
            self.assertIn("\n    water(pot, drops=3)", records[2]["text"])
            self.assertEqual(records[3]["reply_to_id"], "101")
            self.assertIn("芽", records[3]["text"])
            self.assertEqual(records[4]["timestamp"], "2031-04-07T09:04:00+00:00")
            self.assertEqual(records[4]["media_type"], "seed-map.txt Fictional garden diagram")
            self.assertEqual(
                (output / "raw-export/seed-map.txt").read_bytes(),
                (REPOSITORY / "examples/robot-garden/seed-map.txt").read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
