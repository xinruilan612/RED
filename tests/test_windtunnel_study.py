"""Synthetic study readiness and blinded export checks; no participant results."""
import csv
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.windtunnel_study import build_reader_packets, inspect_study, initialize_study


TEMPLATES = Path(__file__).resolve().parents[1] / "docs/windtunnel/templates"
FROZEN_AT = "2026-10-07T09:00:00+08:00"


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WindtunnelStudyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.study = self.base / "study"
        shutil.copytree(TEMPLATES, self.study)
        self.output = self.base / "reader_packets"

    def complete_fixture(self):
        """Fill locally generated fixtures, never the real study templates."""
        (self.study / "records").mkdir()
        for name in ("reader-consent.txt", "paid-model.txt", "source-consent.txt"):
            (self.study / "records" / name).write_text("SYNTHETIC TEST RECORD", encoding="utf-8")
        (self.study / "prompts").mkdir()
        for variant in ("baseline", "windtunnel"):
            (self.study / "prompts" / f"{variant}.txt").write_text(
                f"Synthetic {variant} prompt", encoding="utf-8")
        run = json.loads((self.study / "study_run_TEMPLATE.json").read_text())
        run.update(mechanism_frozen_at=FROZEN_AT, code_commit="a" * 40,
                   model="synthetic-test-model", baseline_prompt_sha256=digest(self.study / "prompts/baseline.txt"),
                   windtunnel_prompt_sha256=digest(self.study / "prompts/windtunnel.txt"), task_rubric_version="synthetic-v1",
                   sources_authorized=True, reader_consent_record_ref="records/reader-consent.txt",
                   paid_model_authorization_ref="records/paid-model.txt", maximum_budget_usd=1.0)
        (self.study / "study_run.json").write_text(json.dumps(run), encoding="utf-8")
        (self.study / "materials").mkdir()
        registry = read_rows(self.study / "sample_registry.csv")
        authorization = []
        for row in registry:
            sample = row["sample_id"]
            draft = self.study / "materials" / f"{sample}-draft.txt"
            support = self.study / "materials" / f"{sample}-support.txt"
            draft.write_text(f"Synthetic draft for {sample}", encoding="utf-8")
            support.write_text(f"Synthetic support for {sample}", encoding="utf-8")
            row.update(content_scenario="synthetic scenario", draft_path=f"materials/{draft.name}",
                       draft_sha256=digest(draft), support_material_path=f"materials/{support.name}",
                       author_alias="TEST_AUTHOR", frozen_at=FROZEN_AT)
            for kind, source in (("draft", draft), ("support", support)):
                authorization.append(dict(sample_id=sample, source_id=f"{sample}-{kind}",
                    source_kind=kind, rights_holder_alias="TEST_OWNER",
                    source_location=f"materials/{source.name}", collected_at=FROZEN_AT,
                    permission_scope="synthetic study use", consent_record_ref="records/source-consent.txt",
                    personal_data_removed="yes", verified_by="TEST_RESEARCHER", verified_at=FROZEN_AT))
        write_rows(self.study / "sample_registry.csv", registry)
        write_rows(self.study / "source_authorization.csv", authorization)
        consent = read_rows(self.study / "reader_consent_RESEARCHER_ONLY.csv")
        for row in consent:
            row.update(eligibility="yes", consent_record_ref="records/reader-consent.txt", consented_at=FROZEN_AT)
        write_rows(self.study / "reader_consent_RESEARCHER_ONLY.csv", consent)
        (self.study / "packets").mkdir()
        assignments = read_rows(self.study / "assignment_key_RESEARCHER_ONLY.csv")
        prompts = {f"S{i:02}": f"Find synthetic fact number {i}." for i in range(4, 11)}
        for row in assignments:
            path = self.study / "packets" / f"{row['packet_id']}.txt"
            path.write_text("Synthetic blinded text; fact number 7.", encoding="utf-8")
            row.update(rendered_text_sha256=digest(path), frozen_at=FROZEN_AT)
        write_rows(self.study / "assignment_key_RESEARCHER_ONLY.csv", assignments)
        costs = read_rows(self.study / "run_costs_RESEARCHER_ONLY.csv")
        for row in costs:
            record_name = f"{row['sample_id']}-{row['variant']}-run.txt"
            (self.study / "records" / record_name).write_text("SYNTHETIC MODEL RECORD", encoding="utf-8")
            row.update(model=run["model"], prompt_sha256=run[row["variant"] + "_prompt_sha256"],
                       call_count="1", input_tokens="10", output_tokens="20", cost_usd="0.01",
                       wall_seconds="1.0", author_seconds="2.0", run_record_ref="records/" + record_name)
        write_rows(self.study / "run_costs_RESEARCHER_ONLY.csv", costs)
        sample_for_packet = {row["packet_id"]: row["sample_id"] for row in assignments}
        for reader in range(1, 7):
            path = self.study / f"reader_R{reader:02}.csv"
            rows = read_rows(path)
            for row in rows:
                row["task_prompt"] = prompts[sample_for_packet[row["packet_id"]]]
            write_rows(path, rows)
        rubric = dict(version="synthetic-v1", tasks=[dict(sample_id=sample, task_prompt=prompt,
            expected_answer="ANSWER_SECRET", scoring_rule="SCORING_SECRET") for sample, prompt in prompts.items()])
        (self.study / "task_rubrics.json").write_text(json.dumps(rubric), encoding="utf-8")

    def assert_blocked(self):
        report = inspect_study(self.study)
        self.assertEqual(report["status"], "not_ready")
        self.assertTrue(report["blockers"])
        self.assertTrue(all(isinstance(value, str) for value in report["blockers"]))
        with self.assertRaises(ValueError):
            build_reader_packets(self.study, self.output)
        self.assertFalse(self.output.exists())

    def test_empty_templates_block_export(self):
        self.assert_blocked()

    def test_complete_synthetic_fixture_exports_only_reader_materials(self):
        self.complete_fixture()
        report = inspect_study(self.study)
        self.assertEqual(report["status"], "ready", report["blockers"])
        self.assertEqual(report["blockers"], [])
        self.assertIsInstance(report["counts"], dict)
        self.assertIsInstance(build_reader_packets(self.study, self.output), dict)
        self.assertEqual({path.name for path in self.output.iterdir()}, {f"R{i:02}" for i in range(1, 7)})
        for number in range(1, 7):
            reader = f"R{number:02}"
            directory = self.output / reader
            self.assertEqual({path.name for path in directory.iterdir()}, {"tasks.csv", "evaluation.csv", "texts"})
            tasks = read_rows(directory / "tasks.csv")
            evaluation = read_rows(directory / "evaluation.csv")
            self.assertEqual(len(tasks), 7)
            self.assertEqual(len(evaluation), 7)
            self.assertEqual({row["reader_id"] for row in tasks + evaluation}, {reader})
            packets = {row["packet_id"] for row in tasks}
            self.assertEqual({path.stem for path in (directory / "texts").iterdir()}, packets)
            for packet in packets:
                self.assertEqual((directory / "texts" / f"{packet}.txt").read_bytes(),
                                 (self.study / "packets" / f"{packet}.txt").read_bytes())
            for path in directory.rglob("*"):
                if path.is_file():
                    content = path.read_text(encoding="utf-8")
                    self.assertNotRegex(content, r"baseline|windtunnel|variant|sample_id|ANSWER_SECRET|SCORING_SECRET|cost_usd")
                    for other in range(1, 7):
                        if other != number:
                            self.assertNotIn(f"R{other:02}", content)

    def test_changed_packet_hash_blocks_export(self):
        self.complete_fixture()
        next((self.study / "packets").iterdir()).write_text("changed", encoding="utf-8")
        self.assert_blocked()

    def test_changed_draft_hash_blocks_export(self):
        self.complete_fixture()
        (self.study / "materials/S01-draft.txt").write_text("changed", encoding="utf-8")
        self.assert_blocked()

    def test_absolute_and_parent_paths_are_rejected(self):
        self.complete_fixture()
        path = self.study / "study_run.json"
        original = json.loads(path.read_text())
        outside = self.base / "external.txt"
        outside.write_text("exists but outside study", encoding="utf-8")
        for unsafe in (str(outside), "../external.txt"):
            with self.subTest(path=unsafe):
                run = dict(original, paid_model_authorization_ref=unsafe)
                path.write_text(json.dumps(run), encoding="utf-8")
                self.assert_blocked()

    def test_same_sample_different_task_is_rejected(self):
        self.complete_fixture()
        path = self.study / "reader_R01.csv"
        rows = read_rows(path)
        rows[0]["task_prompt"] = "Different task for the same sample"
        write_rows(path, rows)
        self.assert_blocked()

    def test_withdrawn_reader_is_rejected(self):
        self.complete_fixture()
        path = self.study / "reader_consent_RESEARCHER_ONLY.csv"
        rows = read_rows(path)
        rows[0]["withdrawal_requested_at"] = FROZEN_AT
        write_rows(path, rows)
        self.assert_blocked()

    def test_missing_source_authorization_is_rejected(self):
        self.complete_fixture()
        path = self.study / "source_authorization.csv"
        write_rows(path, read_rows(path)[1:])
        self.assert_blocked()

    def test_existing_destination_is_preserved(self):
        self.complete_fixture()
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaises(ValueError):
            build_reader_packets(self.study, self.output)
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_changed_prompt_hash_blocks_export(self):
        self.complete_fixture()
        (self.study / "prompts/baseline.txt").write_text("Changed after freeze", encoding="utf-8")
        self.assert_blocked()

    def test_missing_model_run_record_blocks_export(self):
        self.complete_fixture()
        path = self.study / "run_costs_RESEARCHER_ONLY.csv"
        row = read_rows(path)[0]
        (self.study / row["run_record_ref"]).unlink()
        self.assert_blocked()

    def test_missing_cost_without_reason_blocks_export(self):
        self.complete_fixture()
        path = self.study / "run_costs_RESEARCHER_ONLY.csv"
        rows = read_rows(path)
        rows[0]["cost_usd"] = ""
        rows[0]["missing_reason"] = ""
        write_rows(path, rows)
        self.assert_blocked()

    def test_unknown_metrics_with_reason_remain_unknown(self):
        self.complete_fixture()
        path = self.study / "run_costs_RESEARCHER_ONLY.csv"
        rows = read_rows(path)
        for field in ("cost_usd", "input_tokens", "output_tokens", "wall_seconds", "author_seconds"):
            rows[0][field] = ""
        rows[0]["missing_reason"] = "Synthetic provider does not report metrics"
        write_rows(path, rows)
        report = inspect_study(self.study)
        self.assertEqual(report["status"], "ready", report["blockers"])
        self.assertEqual(read_rows(path)[0]["cost_usd"], "")

    def test_negative_or_nonfinite_cost_is_rejected(self):
        self.complete_fixture()
        path = self.study / "run_costs_RESEARCHER_ONLY.csv"
        rows = read_rows(path)
        for invalid in ("-1", "NaN", "Infinity", "not-a-number"):
            with self.subTest(cost=invalid):
                rows[0]["cost_usd"] = invalid
                write_rows(path, rows)
                self.assert_blocked()

    def test_model_and_prompt_record_must_match_frozen_run(self):
        self.complete_fixture()
        path = self.study / "run_costs_RESEARCHER_ONLY.csv"
        original = read_rows(path)
        for field, invalid in (("model", "different-model"), ("prompt_sha256", "d" * 64), ("call_count", "0")):
            with self.subTest(field=field):
                rows = [dict(row) for row in original]
                rows[0][field] = invalid
                write_rows(path, rows)
                self.assert_blocked()

    def test_blind_packet_cannot_disclose_variant_labels(self):
        self.complete_fixture()
        mapping_path = self.study / "assignment_key_RESEARCHER_ONLY.csv"
        rows = read_rows(mapping_path)
        packet = self.study / "packets" / f"{rows[0]['packet_id']}.txt"
        for label in ("baseline", "windtunnel", "有迹", "内容风洞"):
            with self.subTest(label=label):
                packet.write_text(f"Synthetic text generated by {label}", encoding="utf-8")
                rows[0]["rendered_text_sha256"] = digest(packet)
                write_rows(mapping_path, rows)
                self.assert_blocked()


class PublicCandidatePreparationTests(unittest.TestCase):
    def test_public_snapshots_keep_hashes_license_and_no_outcomes(self):
        import sys
        script = TEMPLATES.parent / "public_samples/verify.py"
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("10 public samples", result.stdout)

    def test_init_seeds_sources_without_authorizing_freezing_or_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "private-study"
            result = initialize_study(output)
            self.assertEqual(result["candidate_samples"], 10)
            registry = read_rows(output / "sample_registry.csv")
            self.assertEqual(len(registry), 10)
            self.assertTrue(all(digest(output / r["draft_path"]) == r["draft_sha256"] for r in registry))
            self.assertTrue(all(not r["frozen_at"] and not r["feedback_path"] for r in registry))
            rights = read_rows(output / "source_authorization.csv")
            self.assertEqual(len(rights), 20)
            self.assertTrue(all(not r["verified_by"] and not r["verified_at"] for r in rights))
            self.assertEqual(inspect_study(output)["status"], "not_ready")
            with self.assertRaises(ValueError):
                build_reader_packets(output, Path(temporary) / "packets")
            with self.assertRaises(ValueError):
                initialize_study(output)


if __name__ == "__main__":
    unittest.main()
