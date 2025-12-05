#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

export BASE_IMAGE_BUILD_DIR="${BASE_IMAGE_BUILD_DIR:-$REPO_ROOT/logs/build_images/base}"
export ENV_IMAGE_BUILD_DIR="${ENV_IMAGE_BUILD_DIR:-$REPO_ROOT/logs/build_images/env}"
export INSTANCE_IMAGE_BUILD_DIR="${INSTANCE_IMAGE_BUILD_DIR:-$REPO_ROOT/logs/build_images/instances}"

: "${STAGE4_PRED_PATH:=$REPO_ROOT/launch/output/asteroid_stage4_predictions_success.jsonl}"
: "${STAGE4_IDS_PATH:=$REPO_ROOT/launch/output/asteroid_stage4_instance_ids_success.txt}"
: "${STAGE4_DATASET_PATH:=$REPO_ROOT/curation/output/asteroid_stage3_tasks.jsonl}"
: "${STAGE4_RUN_ID:=asteroid-stage4-rerun}"
: "${STAGE4_NAMESPACE:=danielzayas}"
: "${STAGE4_INSTANCE_TAG:=latest}"
: "${STAGE4_MAX_WORKERS:=4}"
: "${STAGE4_TIMEOUT:=1800}"

PRED_PATH="$STAGE4_PRED_PATH"
IDS_PATH="$STAGE4_IDS_PATH"
DATASET_PATH="$STAGE4_DATASET_PATH"
RUN_ID="$STAGE4_RUN_ID"
NAMESPACE="$STAGE4_NAMESPACE"
INSTANCE_IMAGE_TAG="$STAGE4_INSTANCE_TAG"
MAX_WORKERS="$STAGE4_MAX_WORKERS"
TIMEOUT="$STAGE4_TIMEOUT"

if [[ ! -f "$PRED_PATH" ]]; then
  echo "Missing predictions file at $PRED_PATH" >&2
  exit 1
fi

if [[ ! -f "$IDS_PATH" ]]; then
  echo "Missing instance id list at $IDS_PATH" >&2
  exit 1
fi

readarray -t INSTANCE_IDS < "$IDS_PATH"

python swebench/harness/run_validation.py \
  --dataset_name "$DATASET_PATH" \
  --split test \
  --instance_ids "${INSTANCE_IDS[@]}" \
  --predictions_path "$PRED_PATH" \
  --max_workers "$MAX_WORKERS" \
  --force_rebuild False \
  --cache_level env \
  --clean False \
  --run_id "$RUN_ID" \
  --timeout "$TIMEOUT" \
  --namespace "$NAMESPACE" \
  --instance_image_tag "$INSTANCE_IMAGE_TAG" \
  --report_dir "logs/run_validation" \
  --modal False
