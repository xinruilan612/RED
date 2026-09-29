"""Check safe reproducible delivery and preallocated, still-empty study forms."""
import csv
import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from collections import Counter
from pathlib import Path

from scripts.package_windtunnel import PREFIX, REQUIRED_SOURCES, allowed_path, build


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "docs/windtunnel/templates"


def records(name):
    with (TEMPLATES / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class WindtunnelStudyTemplatesTests(unittest.TestCase):
    def test_holdout_assignment_has_no_reader_crossover_or_version_leak(self):
        mapping = {r["packet_id"]: r for r in records("assignment_key_RESEARCHER_ONLY.csv")}
        self.assertEqual(len(mapping), 14)
        self.assertEqual(Counter(r["sample_id"] for r in mapping.values()),
                         {f"S{i:02}": 2 for i in range(4, 11)})
        seen = Counter()
        for number in range(1, 7):
            reader = f"R{number:02}"
            filename = f"reader_{reader}.csv"
            rows = records(filename)
            self.assertEqual(len(rows), 7)
            self.assertEqual([int(r["reading_order"]) for r in rows], list(range(1, 8)))
            self.assertEqual({r["reader_id"] for r in rows}, {reader})
            self.assertEqual({mapping[r["packet_id"]]["sample_id"] for r in rows},
                             {f"S{i:02}" for i in range(4, 11)})
            self.assertNotRegex((TEMPLATES / filename).read_text(encoding='utf-8'),
                                r"baseline|windtunnel|variant|sample_id|S0[4-9]|S10")
            seen.update(r["packet_id"] for r in rows)
        self.assertEqual(set(seen), set(mapping))
        self.assertEqual(set(seen.values()), {3})
        self.assertEqual(sum(seen.values()), 42)

    def test_outcomes_and_consent_remain_empty(self):
        registry = records("sample_registry.csv")
        self.assertEqual(Counter(r["cohort"] for r in registry), {"exploratory": 3, "holdout": 7})
        forms = {
            "reader_evaluation_TEMPLATE.csv": {"reader_id", "reading_order", "packet_id"},
            "human_scoring_RESEARCHER_ONLY.csv": {"reader_id", "packet_id"},
            "source_authorization.csv": {"sample_id"},
            "reader_consent_RESEARCHER_ONLY.csv": {"reader_id"},
            "run_costs_RESEARCHER_ONLY.csv": {"sample_id", "variant"},
        }
        for filename, identifiers in forms.items():
            rows = records(filename)
            self.assertTrue(rows)
            for row in rows:
                self.assertTrue(all(value == "" for key, value in row.items() if key not in identifiers), filename)
        evaluations = records("reader_evaluation_TEMPLATE.csv")
        self.assertEqual(len(evaluations), 42)
        self.assertEqual(len({(r["reader_id"], r["packet_id"]) for r in evaluations}), 42)
        self.assertNotRegex((TEMPLATES / "reader_evaluation_TEMPLATE.csv").read_text(encoding='utf-8'), r"baseline|windtunnel|variant")
        run = json.loads((TEMPLATES / "study_run_TEMPLATE.json").read_text(encoding='utf-8'))
        self.assertEqual(run["status"], "not_started")
        self.assertIsNone(run["readings_completed"])
        self.assertIsNone(run["paid_model_authorization_ref"])


class WindtunnelPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        for relative in REQUIRED_SOURCES:
            self.write(relative, "example source\n")
        self.git("add", ".")
        self.git("-c", "user.name=Delivery test", "-c", "user.email=delivery@example.invalid",
                 "commit", "-qm", "fixture")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')
        return path

    def test_archive_excludes_private_paths_deleted_sources_and_unlisted_files(self):
        private = (".env", ".env.backup", "runtime/private.txt", "runtime/data.sqlite",
                   ".git/private-note", ".codex/history.json", "config/credentials.json", "key.pem",
                   "secrets/settings.txt", "sessions/saved.json", "logs/activity.txt")
        for relative in private:
            self.write(relative, "private-fixture-never-archive")
            if not relative.startswith(".git/"):
                self.git("add", "-f", relative)
        removed = self.write("xhs_multi_agent_starter/ui.py", "deleted fixture")
        self.git("add", "xhs_multi_agent_starter/ui.py")
        removed.unlink()
        self.write("unknown-untracked.txt", "do not implicitly include")
        self.write("backend/new_delivery.py", "explicit safe addition")
        self.write(".env.example", "DEEPSEEK_API_KEY=\n")
        self.git("add", ".env.example")
        try:
            self.root.joinpath("backend/link.py").symlink_to(self.root / "requirements.txt")
        except OSError as error:
            if getattr(error, 'winerror', None) == 1314:
                self.skipTest('Windows未启用符号链接权限')
            raise
        self.git("add", "backend/link.py")
        result = build(self.root / "bundle.zip", root=self.root, extra=["backend/new_delivery.py"])
        with zipfile.ZipFile(result["archive"]) as archive:
            names = archive.namelist()
            self.assertIsNone(archive.testzip())
            self.assertIn(PREFIX + "/.env.example", names)
            self.assertIn(PREFIX + "/backend/new_delivery.py", names)
            for relative in (*private, "xhs_multi_agent_starter/ui.py", "unknown-untracked.txt", "backend/link.py"):
                self.assertNotIn(PREFIX + "/" + relative, names)
            for name in names:
                self.assertNotIn(b"private-fixture-never-archive", archive.read(name))
                self.assertNotIn("..", Path(name).parts)

    def test_secret_content_blocks_archive_without_echoing_secret(self):
        marker = "sk-" + "fixtureNeverUseAsARealKey" * 2
        self.write("backend/leak.py", "api_key = '" + marker + "'\n")
        self.git("add", "backend/leak.py")
        with self.assertRaises(ValueError) as raised:
            build(self.root / "blocked.zip", root=self.root)
        self.assertIn("backend/leak.py", str(raised.exception))
        self.assertNotIn(marker, str(raised.exception))
        self.assertFalse((self.root / "blocked.zip").exists())

    def test_identical_inputs_produce_same_archive_and_valid_manifest(self):
        first = build(self.root / "first.zip", root=self.root)
        second = build(self.root / "second.zip", root=self.root)
        self.assertEqual(first["sha256"], second["sha256"])
        with zipfile.ZipFile(first["archive"]) as archive:
            manifest = json.loads(archive.read(PREFIX + "/DELIVERY_MANIFEST.json"))
            for relative, expected in manifest["files"].items():
                data = archive.read(PREFIX + "/" + relative)
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected["sha256"])
                self.assertEqual(len(data), expected["bytes"])
        self.assertEqual(json.loads((self.root / "first.zip.manifest.json").read_text(encoding='utf-8')), manifest)
        self.assertTrue((self.root / "first.zip.sha256").read_text(encoding='utf-8').startswith(first["sha256"]))

    def test_extra_inclusions_cannot_bypass_path_filter(self):
        for path in ("../outside.py", "/tmp/outside.py", "runtime/x.txt", ".env.local", "..\\outside.py"):
            self.assertFalse(allowed_path(path))
            with self.assertRaises(ValueError):
                build(self.root / "invalid.zip", root=self.root, extra=[path])

    def test_output_cannot_replace_tracked_source(self):
        original = (self.root / "requirements.txt").read_bytes()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            build(self.root / "requirements.txt", root=self.root)
        self.assertEqual((self.root / "requirements.txt").read_bytes(), original)

    def test_incomplete_windtunnel_source_cannot_be_packaged(self):
        (self.root / "backend/windtunnel_runtime.py").unlink()
        with self.assertRaisesRegex(ValueError, "Required source missing"):
            build(self.root / "incomplete.zip", root=self.root)
        self.assertFalse((self.root / "incomplete.zip").exists())


if __name__ == "__main__":
    unittest.main()
