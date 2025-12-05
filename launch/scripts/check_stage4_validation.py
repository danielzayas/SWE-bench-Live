#!/usr/bin/env python3
"""Check Stage 4 validation outputs and summarize completion status."""
import argparse
import json
from pathlib import Path

RUN_LOG_DIR = Path("logs/run_evaluation")
DEFAULT_MANIFEST = Path("launch/output/asteroid_stage3_manifest.json")
DEFAULT_SUMMARY = Path("launch/output/asteroid_stage4_summary.json")
DEFAULT_PREDICTIONS = Path("launch/output/asteroid_stage4_predictions.jsonl")


def load_instance_ids(manifest_path: Path) -> list[str]:
    data = json.loads(manifest_path.read_text())
    return [entry["instance_id"] for entry in data]


def load_models(predictions_path: Path) -> set[str]:
    models = set()
    with predictions_path.open() as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            pred = json.loads(line)
            models.add(pred.get("model_name_or_path", "unknown"))
    return models or {"unknown"}


def summarize(run_id: str, manifest_path: Path, predictions_path: Path) -> dict:
    expected_ids = load_instance_ids(manifest_path)
    models = load_models(predictions_path)
    run_dir = RUN_LOG_DIR / run_id
    summary = {
        "run_id": run_id,
        "total_instances": len(expected_ids),
        "models": sorted(models),
        "complete": [],
        "missing_logs": [],
        "missing_pre_map": [],
        "missing_post_map": [],
        "missing_instance_json": [],
    }

    for instance_id in expected_ids:
        instance_logged = False
        for model in models:
            log_dir = run_dir / model.replace("/", "__") / instance_id
            if not log_dir.exists():
                continue
            instance_logged = True
            pre_map = log_dir / "pre_test_map.json"
            post_map = log_dir / "post_test_map.json"
            instance_file = log_dir / "instance.json"
            missing = False
            if not pre_map.exists():
                summary["missing_pre_map"].append(instance_id)
                missing = True
            if not post_map.exists():
                summary["missing_post_map"].append(instance_id)
                missing = True
            if not instance_file.exists():
                summary["missing_instance_json"].append(instance_id)
                missing = True
            if not missing:
                summary["complete"].append(instance_id)
            break
        if not instance_logged:
            summary["missing_logs"].append(instance_id)
    summary["complete_count"] = len(summary["complete"])
    summary["pending_count"] = summary["total_instances"] - summary["complete_count"]
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run_id", default="asteroid-stage4-rerun")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args()

    summary = summarize(args.run_id, args.manifest, args.predictions)
    args.output.write_text(json.dumps(summary, indent=2))
    print(f"Wrote summary to {args.output}")
    print(json.dumps({k: v for k, v in summary.items() if isinstance(v, int)}, indent=2))


if __name__ == "__main__":
    main()
