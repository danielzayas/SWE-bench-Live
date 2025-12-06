from __future__ import annotations
import argparse
import json
import os
from datetime import date
from pathlib import Path
from typing import Iterator
from unidiff import PatchSet


def stats_with_unidiff(diff_text: str) -> dict[str, int]:
    patch = PatchSet(diff_text)
    files = len(patch)
    hunks = sum(len(f) for f in patch)
    lines = sum(
        1
        for f in patch
        for h in f
        for l in h
        if l.is_added or l.is_removed
    )
    return {"files": files, "hunks": hunks, "lines": lines}


def processing_one_instance(instance: dict):
    instance["pull_number"] = str(instance["pull_number"])
    instance["issue_numbers"] = [str(i) for i in instance["issue_numbers"]]
    instance["difficulty"] = stats_with_unidiff(instance["patch"])
    return instance


def iter_instances_from_dir(root: Path) -> Iterator[dict]:
    for instance_path in root.rglob("instance.json"):
        try:
            with instance_path.open(encoding="utf-8") as fp:
                dct = json.load(fp)
        except (json.JSONDecodeError, OSError) as err:
            print(f"Skipping {instance_path}: {err}")
            continue

        if dct.get("FAIL_TO_PASS") and dct.get("PASS_TO_PASS"):
            yield dct


def iter_instances_from_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as fp:
        for line_no, line in enumerate(fp, 1):
            line = line.strip()
            if not line:
                continue
            try:
                dct = json.loads(line)
            except json.JSONDecodeError as err:
                print(f"Skipping line {line_no} in {path}: {err}")
                continue
            if dct.get("FAIL_TO_PASS") and dct.get("PASS_TO_PASS"):
                yield dct


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect valid instances to create full dataset")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--input-dir",
        type=Path,
        help="Root directory containing per-instance folders (Stage 4 logs)",
    )
    input_group.add_argument(
        "--input-jsonl",
        type=Path,
        help="Stage 4 aggregated JSONL file (output of launch/to_swebench.py)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("datasets"),
        help="Directory for generated dataset (default: datasets/)",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
    )

    args = parser.parse_args()

    if args.output_file is None:
        today = date.today().isoformat()
        args.output_file = args.output_dir / f"full-{today}.jsonl"

    if args.input_jsonl:
        if not args.input_jsonl.is_file():
            raise SystemExit(f"Input JSONL {args.input_jsonl} not found")
        source_iter = iter_instances_from_jsonl(args.input_jsonl)
    else:
        if not args.input_dir.is_dir():
            raise SystemExit(f"Expected directory {args.input_dir} not found")
        source_iter = iter_instances_from_dir(args.input_dir)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    with args.output_file.open("w", encoding="utf-8") as outfile:
        for dct in source_iter:
            dct = processing_one_instance(dct)
            json.dump(dct, outfile, ensure_ascii=False)
            outfile.write("\n")

    print(f"Collected records written to {args.output_file.resolve()}")


if __name__ == "__main__":
    main()
