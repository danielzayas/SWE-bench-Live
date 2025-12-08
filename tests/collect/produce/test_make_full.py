from __future__ import annotations
import json
import sys
from pathlib import Path

from swebench.collect.produce import make_full

FIXTURE = Path(__file__).parent / "fixtures" / "sample_stage4.jsonl"


def test_iter_instances_from_jsonl_filters_and_processes_valid_records():
    records = list(make_full.iter_instances_from_jsonl(FIXTURE))
    assert {r["instance_id"] for r in records} == {
        "example__repo-42",
        "example__repo-44",
    }

    processed = make_full.processing_one_instance(records[0].copy())
    assert processed["pull_number"] == "42"
    assert processed["issue_numbers"] == ["100"]
    assert processed["difficulty"] == {"files": 1, "hunks": 1, "lines": 3}

    no_pass_record = next(r for r in records if r["instance_id"] == "example__repo-44")
    assert no_pass_record["PASS_TO_PASS"] == []
    assert no_pass_record["FAIL_TO_PASS"]


def test_main_outputs_full_dataset_from_jsonl(monkeypatch, tmp_path):
    output_file = tmp_path / "full.jsonl"
    output_dir = tmp_path / "datasets"
    argv = [
        "make_full.py",
        "--input-jsonl",
        str(FIXTURE),
        "--output-dir",
        str(output_dir),
        "--output-file",
        str(output_file),
    ]
    monkeypatch.setattr(sys, "argv", argv)

    make_full.main()

    lines = output_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    payloads = [json.loads(line) for line in lines]
    ids = {p["instance_id"] for p in payloads}
    assert ids == {"example__repo-42", "example__repo-44"}
    target = next(p for p in payloads if p["instance_id"] == "example__repo-42")
    assert target["pull_number"] == "42"
    assert target["difficulty"] == {"files": 1, "hunks": 1, "lines": 3}
