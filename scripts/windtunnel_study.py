"""Validate study preparation and build isolated reader packets; no model/network calls."""
import argparse
import csv
import hashlib
import io
import json
import math
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path


READERS = [f"R{i:02}" for i in range(1, 7)]
SAMPLES = [f"S{i:02}" for i in range(1, 11)]
HOLDOUT = SAMPLES[3:]
ROOT = Path(__file__).resolve().parents[1]


def safe_file(root, relative):
    """Reject absolute paths, traversal and links escaping the study folder."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("missing or unsafe relative path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe relative path")
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError("missing or unsafe study file")
    return target


def read_csv(root, name):
    with safe_file(root, name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_study(study_dir):
    root = Path(study_dir)
    blockers = []
    counts = {"samples": 0, "packets": 0, "consented_readers": 0, "planned_readings": 0}

    def need(condition, message):
        if not condition:
            blockers.append(message)

    def file_ref(value, label, sha=None):
        try:
            path = safe_file(root, value)
            need(path.stat().st_size > 0, label + ": empty file")
            if sha is not None:
                need(sha == digest(path), label + ": hash mismatch")
            return path
        except ValueError:
            blockers.append(label + ": missing or unsafe file reference")
            return None

    def rows(name):
        try:
            return read_csv(root, name)
        except (ValueError, UnicodeError, csv.Error):
            blockers.append(name + ": unreadable or missing")
            return []

    try:
        run = json.loads(safe_file(root, "study_run.json").read_text(encoding="utf-8"))
        if not isinstance(run, dict):
            raise ValueError("invalid run")
    except (ValueError, UnicodeError):
        run = {}
        blockers.append("study_run.json: missing or invalid; copy and fill study_run_TEMPLATE.json")
    for field in ("mechanism_frozen_at", "code_commit", "model", "baseline_prompt_sha256",
                  "windtunnel_prompt_sha256", "task_rubric_version"):
        need(bool(run.get(field)), "study_run.json: missing " + field)
    for field in ("baseline_prompt_sha256", "windtunnel_prompt_sha256"):
        value = run.get(field)
        need(isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value),
             "study_run.json: invalid " + field)
        file_ref("prompts/" + field.removesuffix("_prompt_sha256") + ".txt", field, value or "")
    need(run.get("sources_authorized") is True, "source authorization not confirmed")
    for field in ("reader_consent_record_ref", "paid_model_authorization_ref"):
        file_ref(run.get(field), field)
    budget = run.get("maximum_budget_usd")
    need(isinstance(budget, (int, float)) and not isinstance(budget, bool)
         and math.isfinite(budget) and budget > 0, "model budget missing or invalid")

    registry = rows("sample_registry.csv")
    need(Counter(r.get("sample_id") for r in registry) == Counter(SAMPLES), "sample registry must contain S01-S10 once")
    authorizations = rows("source_authorization.csv")
    for row in registry:
        sample = row.get("sample_id", "unknown")
        valid = True
        for field in ("content_scenario", "author_alias", "frozen_at"):
            need(bool(row.get(field)), sample + ": missing " + field)
            valid = valid and bool(row.get(field))
        cohort = "holdout" if sample in HOLDOUT else "exploratory"
        need(row.get("cohort") == cohort, sample + ": invalid cohort")
        for field, kind in (("draft_path", "draft"), ("support_material_path", "support"), ("feedback_path", "feedback")):
            if field == "feedback_path" and not row.get(field):
                continue
            path = file_ref(row.get(field), sample + ": " + field,
                            row.get("draft_sha256", "") if kind == "draft" else None)
            valid = valid and path is not None
            rights = [r for r in authorizations if r.get("sample_id") == sample
                      and r.get("source_kind") == kind and r.get("source_location") == row.get(field)]
            verified = False
            for right in rights:
                required = ("source_id", "rights_holder_alias", "collected_at", "permission_scope",
                            "consent_record_ref", "verified_by", "verified_at")
                if all(right.get(k) for k in required) and right.get("personal_data_removed") == "yes":
                    if file_ref(right.get("consent_record_ref"), sample + ": rights evidence"):
                        verified = True
            need(verified, sample + ": no verified authorization for " + kind)
        counts["samples"] += int(valid)

    mapping = rows("assignment_key_RESEARCHER_ONLY.csv")
    packet_ids = [r.get("packet_id") for r in mapping]
    need(len(mapping) == 14 and len(set(packet_ids)) == 14, "need 14 unique blind packets")
    need(Counter((r.get("sample_id"), r.get("variant")) for r in mapping)
         == Counter((s, v) for s in HOLDOUT for v in ("baseline", "windtunnel")), "invalid sample/version mapping")
    packet_map = {}
    for row in mapping:
        packet = row.get("packet_id", "")
        need(len(packet) == 5 and packet.startswith("P") and packet[1:].isdigit(), "invalid blind packet id")
        if len(packet) != 5 or not packet.startswith("P") or not packet[1:].isdigit():
            continue
        path = file_ref("packets/" + packet + ".txt", packet, row.get("rendered_text_sha256", ""))
        need(bool(row.get("frozen_at")), packet + ": freeze timestamp missing")
        if path:
            counts["packets"] += 1
            try:
                text = path.read_text(encoding="utf-8")
                need(not re.search(r"baseline|windtunnel|有迹|内容风洞", text, re.I), packet + ": visible workflow label; remove blind leakage")
            except UnicodeError:
                blockers.append(packet + ": expected UTF-8 plain text")
        packet_map[packet] = row

    costs = rows("run_costs_RESEARCHER_ONLY.csv")
    need(Counter((r.get("sample_id"), r.get("variant")) for r in costs)
         == Counter((s, v) for s in HOLDOUT for v in ("baseline", "windtunnel")), "need fourteen process cost records")
    for row in costs:
        label = row.get("sample_id", "unknown") + ": " + row.get("variant", "unknown")
        need(bool(row.get("model")) and row.get("model") == run.get("model"), label + ": model differs from frozen configuration")
        need(bool(row.get("prompt_sha256")) and row.get("prompt_sha256") == run.get(row.get("variant", "") + "_prompt_sha256"), label + ": prompt hash differs from frozen configuration")
        file_ref(row.get("run_record_ref"), label + ": run provenance")
        for field in ("call_count", "input_tokens", "output_tokens", "cost_usd", "wall_seconds", "author_seconds"):
            value = row.get(field)
            if not value and field != "call_count":
                need(bool(row.get("missing_reason")), label + ": " + field + " unknown without reason")
                continue
            try:
                number = float(value)
                minimum = 1 if field == "call_count" else 0
                need(math.isfinite(number) and number >= minimum and (field not in ("call_count", "input_tokens", "output_tokens") or number.is_integer()), label + ": invalid " + field)
            except (ValueError, TypeError):
                blockers.append(label + ": invalid " + field)

    try:
        rubric = json.loads(safe_file(root, "task_rubrics.json").read_text(encoding="utf-8"))
        need(rubric.get("version") == run.get("task_rubric_version") and bool(rubric.get("version")), "rubric version mismatch")
        tasks = rubric.get("tasks", [])
        need(Counter(t.get("sample_id") for t in tasks) == Counter(HOLDOUT), "need seven frozen task rubrics")
        for task in tasks:
            need(all(task.get(k) for k in ("task_prompt", "expected_answer", "scoring_rule")), "incomplete task rubric")
        rubric_tasks = {t.get("sample_id"): t.get("task_prompt") for t in tasks}
    except (ValueError, UnicodeError, AttributeError, TypeError):
        rubric_tasks = {}
        blockers.append("task_rubrics.json: missing or invalid")

    consents = rows("reader_consent_RESEARCHER_ONLY.csv")
    need(Counter(r.get("reader_id") for r in consents) == Counter(READERS), "need six unique reader consent rows")
    for row in consents:
        reader = row.get("reader_id", "unknown")
        valid = row.get("eligibility") == "yes" and bool(row.get("consented_at")) and not row.get("withdrawal_requested_at")
        ref = file_ref(row.get("consent_record_ref"), reader + ": consent evidence")
        need(valid and ref is not None, reader + ": missing consent, ineligible or withdrawn")
        counts["consented_readers"] += int(valid and ref is not None)
    exposure = Counter()
    for reader in READERS:
        assignments = rows("reader_" + reader + ".csv")
        need(len(assignments) == 7, reader + ": need seven tasks")
        need([r.get("reading_order") for r in assignments] == [str(i) for i in range(1, 8)], reader + ": invalid reading order")
        seen = []
        for row in assignments:
            packet = row.get("packet_id")
            need(row.get("reader_id") == reader, reader + ": another reader included")
            sample = packet_map.get(packet, {}).get("sample_id")
            seen.append(sample)
            exposure[packet] += 1
            need(bool(row.get("task_prompt")) and row.get("task_prompt") == rubric_tasks.get(sample), reader + ": task differs from frozen rubric")
        need(Counter(seen) == Counter(HOLDOUT), reader + ": sample crossover or missing task")
        counts["planned_readings"] += len(assignments)
    need(set(exposure) == set(packet_map) and set(exposure.values()) == {3}, "each blind packet must be read by three readers")
    return {"status": "not_ready" if blockers else "ready", "blockers": list(dict.fromkeys(blockers)),
            "counts": counts, "scope": "preparation records only; no proof of legal rights, reader participation or efficacy",
            "model_calls": 0}


def csv_text(fields, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def initialize_study(output_dir, repository=ROOT):
    """Seed public candidates and blank records without inventing authorization or outcomes."""
    output, repository = Path(output_dir), Path(repository)
    if output.exists():
        raise ValueError("output already exists; refusing overwrite")
    public = repository / "docs/windtunnel/public_samples"
    manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="study-prepare-", dir=output.parent) as temporary:
        staging = Path(temporary) / "study"
        shutil.copytree(repository / "docs/windtunnel/templates", staging)
        shutil.copytree(public, staging / "public_samples", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copyfile(staging / "study_run_TEMPLATE.json", staging / "study_run.json")
        registry = read_csv(staging, "sample_registry.csv")
        candidates = {s["sample_id"]: s for s in manifest["samples"]}
        rights = []
        for row in registry:
            sample = candidates[row["sample_id"]]
            row.update(content_scenario=sample["scenario"], draft_path="public_samples/" + sample["draft_path"],
                       draft_sha256=sample["draft_sha256"], support_material_path="public_samples/" + sample["support_path"],
                       author_alias="Python Software Foundation", notes="Public English excerpt candidate; not frozen; no creator feedback")
            for kind, field in (("draft", "draft_path"), ("support", "support_material_path")):
                rights.append(dict(sample_id=row["sample_id"], source_id=row["sample_id"] + "-" + kind,
                                  source_kind=kind, rights_holder_alias="Python Software Foundation",
                                  source_location=row[field], collected_at=sample["fetched_at_utc"],
                                  permission_scope="PSF-2.0 documentation; retain notice/license and review intended use",
                                  consent_record_ref="public_samples/" + sample["license_ref"],
                                  personal_data_removed="", verified_by="", verified_at=""))
        (staging / "sample_registry.csv").write_text(csv_text(list(registry[0]), registry), encoding="utf-8")
        (staging / "source_authorization.csv").write_text(csv_text(list(rights[0]), rights), encoding="utf-8")
        rubric = {"version": None, "status": "candidate_not_frozen",
                  "tasks": [dict(sample_id=s, task_prompt="", expected_answer="", scoring_rule="") for s in HOLDOUT]}
        (staging / "task_rubrics.json").write_text(json.dumps(rubric, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / "README.md").write_text("# 私有研究准备目录\n\n10份公开英文教程候选已复制；未冻结、未签核许可、没有真人或模型结果。\n先核查场景与难度，按仓库 docs/windtunnel/EXECUTION_GUIDE.md 探索后冻结。\n保留私有记录，禁止把整个目录发给读者。\n", encoding="utf-8")
        output.mkdir()
        try:
            for path in staging.iterdir():
                shutil.move(str(path), output / path.name)
        except Exception:
            shutil.rmtree(output)
            raise
    return {"status": "initialized_not_ready", "candidate_samples": 10,
            "output_dir": str(output.resolve()), "model_calls": 0}


def build_reader_packets(study_dir, output_dir):
    root, output = Path(study_dir), Path(output_dir)
    report = inspect_study(root)
    if report["status"] != "ready":
        raise ValueError("study not ready: " + "; ".join(report["blockers"]))
    if output.exists():
        raise ValueError("output already exists; refusing overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="reader-packets-", dir=output.parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        for reader in READERS:
            folder = staging / reader
            (folder / "texts").mkdir(parents=True)
            tasks = read_csv(root, "reader_" + reader + ".csv")
            fields = ["reader_id", "reading_order", "packet_id", "task_prompt"]
            (folder / "tasks.csv").write_text(csv_text(fields, [{k: r[k] for k in fields} for r in tasks]), encoding="utf-8")
            evaluation_fields = fields[:3] + ["answer_found", "answer_text", "difficulty_1_to_5", "elapsed_seconds", "comment", "completed_at"]
            blank = [{k: r[k] if k in fields[:3] else "" for k in evaluation_fields} for r in tasks]
            (folder / "evaluation.csv").write_text(csv_text(evaluation_fields, blank), encoding="utf-8")
            for row in tasks:
                packet = row["packet_id"]
                shutil.copyfile(safe_file(root, "packets/" + packet + ".txt"), folder / "texts" / (packet + ".txt"))
        # Reserve destination atomically; never replace another directory.
        output.mkdir()
        try:
            for folder in staging.iterdir():
                shutil.move(str(folder), output / folder.name)
        except Exception:
            shutil.rmtree(output)
            raise
    return {"status": "prepared", "reader_count": 6, "readings": 42,
            "output_dir": str(output.resolve()), "sent": False, "model_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init")
    init.add_argument("--output-dir", required=True, type=Path)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--study-dir", required=True, type=Path)
    inspect.add_argument("--output", type=Path)
    pack = sub.add_parser("pack")
    pack.add_argument("--study-dir", required=True, type=Path)
    pack.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.action == "init":
            result = initialize_study(args.output_dir)
        elif args.action == "inspect":
            result = inspect_study(args.study_dir)
        else:
            result = build_reader_packets(args.study_dir, args.output_dir)
    except ValueError as error:
        parser.exit(2, str(error) + "\n")
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.action == "inspect" and args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered, end="")
    return 2 if result["status"] == "not_ready" else 0


if __name__ == "__main__":
    raise SystemExit(main())
