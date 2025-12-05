#!/usr/bin/env python3
"""
Utility to remove stale Stage 2 artifacts before rerunning the issue-first pipeline.

The script deletes the contents of the PR, task-instance, and split-job folders so
that a subsequent Stage 2 run starts from a clean slate. By default it operates on
`curation/output`, but the base directory can be overridden.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Dict, List


DEFAULT_TARGETS: Dict[str, str] = {
    "prs": "GitHub PR scrape outputs",
    "tasks": "Task instance jsonl outputs",
    "split_jobs": "Token split assignments and job metadata",
}


def _empty_directory(path: Path) -> List[Path]:
    """Delete all files/sub-directories under ``path`` and return the removed paths."""
    removed: List[Path] = []
    if not path.exists():
        return removed

    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed.append(child)
    return removed


def clean_stage2_outputs(output_root: Path, dry_run: bool = False) -> Dict[str, List[Path]]:
    """
    Remove artifacts inside the default Stage 2 folders.

    Args:
        output_root: Base ``output`` directory that contains Stage 2 folders.
        dry_run: If True, only report the removals without deleting anything.
    Returns:
        Dictionary keyed by logical target name with the removed path list.
    """
    summary: Dict[str, List[Path]] = {}
    for folder_name in DEFAULT_TARGETS:
        folder = output_root / folder_name
        summary[folder_name] = []
        if not folder.exists():
            continue
        if dry_run:
            summary[folder_name] = list(folder.iterdir())
            continue
        summary[folder_name] = _empty_directory(folder)
        folder.mkdir(parents=True, exist_ok=True)
        if folder_name == "split_jobs":
            (folder / "job_status").mkdir(exist_ok=True)
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Remove Stage 2 output artifacts so the rerun starts fresh."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parent / "output",
        help="Root directory that contains Stage 2 folders (default: curation/output).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print which files would be deleted without removing them.",
    )
    args = parser.parse_args()

    root = args.output_root.expanduser()
    summary = clean_stage2_outputs(root, dry_run=args.dry_run)

    print(f"Stage 2 output root: {root}")
    action = "Would remove" if args.dry_run else "Removed"
    for name, removed in summary.items():
        folder_desc = DEFAULT_TARGETS[name]
        folder = root / name
        if not folder.exists() and not removed:
            print(f"⚠️  Skipped '{name}' ({folder_desc}) — folder does not exist.")
            continue
        print(f"{action} {len(removed)} entries from '{folder}' ({folder_desc}).")
        for entry in removed:
            print(f"   - {entry.relative_to(root)}")

    if args.dry_run:
        print("Dry run completed. Re-run without --dry-run to delete the files.")


if __name__ == "__main__":
    main()

