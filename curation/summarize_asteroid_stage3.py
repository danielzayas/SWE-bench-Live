"""
Summarize RepoLaunch outputs for the Astroid Stage 3 run.

The script scans the workspace root produced by RepoLaunch, aggregates
success/failure counts, emits a JSON summary report, and writes a SWE-bench
formatted JSONL for all successful instances so the harness can ingest them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

ARCH = "x86_64"
NAMESPACE = "danielzayas"


def load_result(instance_folder: Path) -> tuple[dict | None, dict | None]:
    """Return (instance, result) tuple if both files exist."""
    instance_path = instance_folder / "instance.json"
    result_path = instance_folder / "result.json"
    if not instance_path.exists() or not result_path.exists():
        return None, None
    try:
        instance = json.loads(instance_path.read_text())
        result = json.loads(result_path.read_text())
    except json.JSONDecodeError:
        return None, None
    return instance, result


def expected_image_tag(instance_id: str) -> str:
    """Match naming scheme documented in ARCHITECTURE.md."""
    key = f"sweb.eval.{ARCH}.{instance_id.lower()}".replace("__", "_1776_")
    return f"{NAMESPACE}/{key}"


def iterate_instances(workspace_root: Path) -> Iterable[tuple[str, Path]]:
    for child in workspace_root.iterdir():
        if child.is_dir():
            yield child.name, child


def summarize(workspace_root: Path) -> dict:
    successes: list[dict] = []
    failures: list[dict] = []
    pending: list[str] = []

    if not workspace_root.exists():
        return {
            "workspace_root": str(workspace_root),
            "total_instances": 0,
            "completed": 0,
            "failed": 0,
            "pending": 0,
            "arch": ARCH,
            "namespace": NAMESPACE,
            "successes": successes,
            "failures": failures,
            "pending_instance_ids": pending,
        }

    for folder_name, folder_path in iterate_instances(workspace_root):
        instance, result = load_result(folder_path)
        if instance is None or result is None:
            pending.append(folder_name)
            continue

        entry = {
            "instance_id": instance["instance_id"],
            "base_image": result.get("base_image"),
            "test_commands": result.get("test_commands", []),
            "setup_commands": result.get("setup_commands", []),
            "exception": result.get("exception"),
            "completed": result.get("completed", False),
            "result_path": str(folder_path / "result.json"),
            "workspace": str(folder_path),
            "image_tag": expected_image_tag(instance["instance_id"]),
        }
        if result.get("completed"):
            successes.append(entry)
        else:
            failures.append(entry)

    return {
        "workspace_root": str(workspace_root),
        "total_instances": len(successes) + len(failures) + len(pending),
        "completed": len(successes),
        "failed": len(failures),
        "pending": len(pending),
        "arch": ARCH,
        "namespace": NAMESPACE,
        "successes": successes,
        "failures": failures,
        "pending_instance_ids": pending,
    }


def write_report(summary: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True))


def write_swebench(successes: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as outfile:
        for entry in successes:
            instance_path = Path(entry["workspace"]) / "instance.json"
            result_path = Path(entry["workspace"]) / "result.json"
            instance = json.loads(instance_path.read_text())
            result = json.loads(result_path.read_text())
            swe_instance = {
                **instance,
                "test_cmds": result.get("test_commands", []),
                "log_parser": result.get("log_parser", "pytest"),
            }
            outfile.write(json.dumps(swe_instance))
            outfile.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize Astroid RepoLaunch outputs.")
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path("launch/workspaces/asteroid-stage3"),
        help="Workspace directory passed to RepoLaunch.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("curation/output/asteroid_stage3_report.json"),
        help="Where to write the JSON summary.",
    )
    parser.add_argument(
        "--swebench",
        type=Path,
        default=Path("curation/output/asteroid_stage3_verified.jsonl"),
        help="Where to write SWE-bench formatted successes.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = summarize(args.workspace_root)
    write_report(summary, args.report)
    write_swebench(summary["successes"], args.swebench)


if __name__ == "__main__":
    main()

