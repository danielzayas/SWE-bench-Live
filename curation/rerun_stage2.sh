#!/bin/bash
#
# One-click helper that re-runs Stage 2:
#   1. Cleans existing Stage 2 outputs
#   2. Re-executes the issue-first crawling pipeline with the 20151210 cutoff
#   3. Merges the resulting task shards (optionally validating them)
#
# Environment variables (all optional):
#   REPOS_JSONL       Path to filtered repos list (default: output/filtered_repos.jsonl)
#   TOKEN_FILE        GitHub token list, one per line (default: tokens.txt)
#   OUTPUT_ROOT       Where Stage 2 outputs live (default: curation/output)
#   CUTOFF_DATE       Cutoff date in YYYYMMDD (default: 20151210)
#   MAX_PULLS         Optional max pulls argument passed to the pipeline
#   MERGED_FILE       Destination for the merged tasks file (default: output/raw_tasks-{cutoff}.jsonl)
#   RUN_VALIDATION    If "true", run swebench.harness.run_validation after merging
#   VALIDATION_DATASET Dataset path to validate (defaults to MERGED_FILE)
#   VALIDATION_WORKERS Worker count for validation (default: 4)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_ROOT="${OUTPUT_ROOT:-$SCRIPT_DIR/output}"
REPOS_JSONL="${REPOS_JSONL:-$OUTPUT_ROOT/filtered_repos.jsonl}"
TOKEN_FILE="${TOKEN_FILE:-$SCRIPT_DIR/tokens.txt}"
CUTOFF_DATE="${CUTOFF_DATE:-20151210}"
MERGED_FILE="${MERGED_FILE:-$OUTPUT_ROOT/raw_tasks-${CUTOFF_DATE}.jsonl}"
MAX_PULLS="${MAX_PULLS:-}"

echo "== Stage 2 Rerun =="
echo "Output root: $OUTPUT_ROOT"
echo "Repo list:   $REPOS_JSONL"
echo "Token file:  $TOKEN_FILE"
echo "Cutoff date: $CUTOFF_DATE"

if [[ ! -f "$REPOS_JSONL" ]]; then
    echo "ERROR: repo list not found at $REPOS_JSONL"
    exit 1
fi

if [[ ! -f "$TOKEN_FILE" ]]; then
    echo "ERROR: token file not found at $TOKEN_FILE"
    exit 1
fi

echo ""
echo "[1/3] Cleaning previous Stage 2 outputs..."
python "$SCRIPT_DIR/clean_stage2_outputs.py" --output-root "$OUTPUT_ROOT"

echo ""
echo "[2/3] Running issue-first pipeline..."
PIPELINE_ARGS=(
    --repos-jsonl "$REPOS_JSONL"
    --token-file "$TOKEN_FILE"
    --cutoff-date "$CUTOFF_DATE"
    --path-prs "$OUTPUT_ROOT/prs"
    --path-tasks "$OUTPUT_ROOT/tasks"
    --output-dir "$OUTPUT_ROOT/split_jobs"
)

if [[ -n "$MAX_PULLS" ]]; then
    PIPELINE_ARGS+=(--max-pulls "$MAX_PULLS")
fi

bash "$SCRIPT_DIR/swe_task_crawling/run_get_tasks_pipeline.sh" "${PIPELINE_ARGS[@]}"

echo ""
echo "[3/3] Merging task shards..."
python "$SCRIPT_DIR/swe_task_crawling/merge_tasks.py" "$OUTPUT_ROOT/tasks" -o "$MERGED_FILE" --validate
echo "Merged tasks saved to $MERGED_FILE"

if [[ "${RUN_VALIDATION:-false}" == "true" ]]; then
    echo ""
    echo "[bonus] Running swebench.harness.run_validation..."
    pushd "$SCRIPT_DIR/.." >/dev/null
    python -m swebench.harness.run_validation \
        --dataset_name "${VALIDATION_DATASET:-$MERGED_FILE}" \
        --predictions_path gold \
        --run_id "stage2-${CUTOFF_DATE}" \
        --max_workers "${VALIDATION_WORKERS:-4}"
    popd >/dev/null
fi

echo ""
echo "Stage 2 rerun orchestration complete."

