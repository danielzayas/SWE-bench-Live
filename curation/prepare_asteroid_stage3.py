"""
Utilities for preparing Stage 3 (RepoLaunch) inputs for the Astroid repo.

This script filters the Stage 2 `raw_tasks.jsonl` output down to the Astroid
instances, writes a snapshot for bookkeeping, and produces a RepoLaunch-ready
manifest that sets required defaults (e.g., language).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable


def load_instances(raw_tasks_path: Path, repo: str) -> list[dict]:
    """Load JSONL instances and keep only those that match the requested repo."""
    instances: list[dict] = []
    with raw_tasks_path.open() as infile:
        for line in infile:
            obj = json.loads(line)
            if obj.get("repo") == repo:
                instances.append(obj)
    return instances


def write_jsonl(instances: Iterable[dict], output_path: Path) -> None:
    """Write instances to a JSONL file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as outfile:
        for inst in instances:
            outfile.write(json.dumps(inst, sort_keys=True))
            outfile.write("\n")


def write_snapshot(instances: list[dict], raw_tasks_path: Path, snapshot_path: Path) -> None:
    """Persist metadata snapshot for bookkeeping and debugging."""
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": str(raw_tasks_path),
        "repo": instances[0]["repo"] if instances else None,
        "total_instances": len(instances),
        "instance_ids": [inst["instance_id"] for inst in instances],
        "pull_numbers": [inst["pull_number"] for inst in instances],
        "issue_numbers": [inst["issue_numbers"] for inst in instances],
        "base_commits": sorted({inst["base_commit"] for inst in instances}),
    }
    snapshot_path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def apply_manifest_defaults(instances: list[dict], language: str) -> list[dict]:
    """Ensure instances include RepoLaunch-required fields."""
    manifest: list[dict] = []
    for inst in instances:
        inst_with_defaults = dict(inst)
        inst_with_defaults.setdefault("language", language)
        manifest.append(inst_with_defaults)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare Stage 3 inputs for Astroid.")
    parser.add_argument(
        "--raw-tasks",
        type=Path,
        default=Path("curation/output/raw_tasks.jsonl"),
        help="Path to Stage 2 raw_tasks.jsonl output.",
    )
    parser.add_argument(
        "--repo",
        default="pylint-dev/astroid",
        help="Repository slug to keep from the Stage 2 output.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("curation/output/asteroid_stage3_tasks.jsonl"),
        help="Destination JSONL manifest for RepoLaunch.",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path("curation/output/asteroid_stage2_snapshot.json"),
        help="Destination JSON snapshot summarizing filtered entries.",
    )
    parser.add_argument(
        "--language",
        default="python",
        help="Language value to attach to each manifest entry.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    instances = load_instances(args.raw_tasks, args.repo)
    if not instances:
        raise SystemExit(f"No instances found for repo '{args.repo}' in {args.raw_tasks}")
    write_snapshot(instances, args.raw_tasks, args.snapshot)
    manifest = apply_manifest_defaults(instances, args.language)
    write_jsonl(manifest, args.manifest)


if __name__ == "__main__":
    main()

