import json
from pathlib import Path

from fire import Fire


def iter_instance_dirs(root: Path):
    """
    Yield directories that contain an instance.json file.
    Handles both flat (e.g. instance.json) and nested (e.g. directory/instance.json) layouts.
    """
    if not root.exists():
        return
    for instance_file in root.rglob("instance.json"):
        yield instance_file.parent, instance_file


def load_result(result_root: Path | None, instance_dir: Path, instance_id: str):
    """
    Locate and return the result.json content for an instance.
    """
    if result_root is None:
        candidate = instance_dir / "result.json"
    else:
        candidate = result_root / instance_id / "result.json"
    if not candidate.exists():
        return None
    return json.loads(candidate.read_text())


def normalize_test_cmds(test_cmds):
    if isinstance(test_cmds, str):
        return [test_cmds]
    if isinstance(test_cmds, list):
        return test_cmds
    return []


def main(
    instance_root,
    output_jsonl,
    result_root=None,
):
    """
    Convert validated instances to SWE-bench format.

    Args:
        instance_root: Directory containing the up-to-date instance.json files
            (e.g., logs/run_evaluation/<run_id>/some-directory/).
        output_jsonl: Destination file for the combined JSONL.
        result_root: optional directory containing workspaces with result.json files
            (e.g., launch/workspaces/<run_id>/). Defaults to instance_root if not set.
    """
    instance_root = Path(instance_root)
    result_root = Path(result_root) if result_root else None

    swe_instances = []
    for instance_dir, instance_path in iter_instance_dirs(instance_root):
        instance = json.loads(instance_path.read_text())
        instance_id = instance.get("instance_id") or instance_dir.name

        result = load_result(result_root, instance_dir, instance_id)
        if not result or not result.get("completed", False):
            continue

        swe_instance = {
            **instance,
            "test_cmds": normalize_test_cmds(result.get("test_commands")),
            "log_parser": result.get("log_parser", "pytest"),
        }
        swe_instances.append(swe_instance)

    with open(output_jsonl, "w") as f:
        for instance in swe_instances:
            f.write(json.dumps(instance) + "\n")
    print(f"Saved {len(swe_instances)} instances to {output_jsonl}")


if __name__ == "__main__":
    Fire(main)
