# SWE-bench-Live Architecture

SWE-bench-Live is an automated curation and evaluation system for GitHub issue-resolution tasks. It extends the original SWE-bench benchmark with a fully automated pipeline that continuously curates fresh instances, synthesizes execution environments, validates gold solutions, and publishes rolling dataset releases.

## Relationship to SWE-bench and SWE-smith
- **SWE-bench-Live ↔ SWE-bench**: The `swebench/` directory is a lightly modified fork of the original [SWE-bench](https://github.com/SWE-bench/SWE-bench) harness, ensuring evaluation settings and metrics stay compatible. SWE-bench-Live inherits the instance schema, Docker image conventions, and validation utilities (`swebench.harness.run_validation`) so that prior tooling and leaderboard practices remain applicable, while adding automation around data refreshes (`README.md`).
- **SWE-bench-Live ↔ SWE-smith**: SWE-smith is the companion toolkit for generating SWE-bench-style *training* data and execution environments at scale; it emphasizes compatibility with SWE-agent and broader data generation needs (`swebench/collect/README.md`). SWE-bench-Live focuses on *evaluation* data that is continuously refreshed and verified. Both projects share design principles (per-repo environments, test-based verification) and can reuse each other’s environments or task schema.

## End-to-End Pipeline Overview
The curation workflow described in `curation/tutorial.md` and illustrated in `assets/overview.png` runs as a monthly loop:

1. **Repository Discovery & Filtering** (`curation/crawl_repo.py`, `curation/filter_repo.py`)
2. **Issue–PR Pair Construction** (`curation/swe_task_crawling/run_get_tasks_pipeline.sh`, `merge_tasks.py`)
3. **Environment Synthesis with RepoLaunch** (`launch/`, `to_swebench.py`)
4. **Validation & Test Signal Extraction** (`swebench.harness.run_validation`)
5. **Dataset Packaging & Publication** (`swebench/collect/produce/*`)

Every successfully validated instance yields:
- A Docker image tagged under the `starryzhang/sweb.eval.*` namespace (generated during RepoLaunch).
- Metadata rows that populate the `full`, `lite`, and `verified` splits pushed to [Hugging Face](https://huggingface.co/datasets/SWE-bench-Live/SWE-bench-Live).

The team currently publishes **50 new verified issues each month** to the `full` split while keeping `lite` and `verified` frozen for stable leaderboard comparisons (`README.md`).

## Stage 1 – Repository Discovery & Filtering
1. `crawl_repo.py` gathers candidate repositories via the GitHub API, allowing language and star filters plus multiple API tokens for rate-limit resilience (`curation/tutorial.md`).
2. `filter_repo.py` enforces minimum collaboration signals (issues, PR counts, forks) and dominant language ratios to ensure downstream reproducibility.
3. Filtered repositories are stored as JSONL (`output/filtered_repos.jsonl`) and drive the remaining stages.

*Automation characteristics*: scripts can fan out across workers (`--max_workers`), ingest rotating token files, and produce deterministic intermediate artifacts to resume partial runs.

## Stage 2 – Issue–PR Pair Construction
1. `swe_task_crawling/run_get_tasks_pipeline.sh` orchestrates the SWE-Fixer–provided scripts (`README.md`) to download PR metadata (`fetch_pulls.py`, `get_pull_request_content.py`) and map PRs to their GitHub issues (`get_pull_issue_dict.py`).
2. `build_dataset.py` converts each Issue–PR pair into SWE-bench-style task instances, producing `*.jsonl` files that distinguish between "has tests" candidates and broader `*.jsonl.all` collections suitable for fine-tuning.
3. `merge_tasks.py` aggregates per-repo outputs into a single `raw_tasks.jsonl`, preserving creation timestamps for later time-aware filtering (`--cutoff-date`).

*Automation characteristics*: the pipeline supports job splitting (`split_jobs.py`), centralized progress tracking (`track_progress.py`), and throttling via shared `job_status/` folders so monthly crawls can run unattended.

## Stage 3 – Environment Synthesis with RepoLaunch
1. RepoLaunch (`launch/README.md`) is an LLM-driven agent that clones each repository at `base_commit`, infers build/test tooling, and emits the shell recipe (`setup_commands`, `test_commands`) needed to create a runnable sandbox.
2. Runs are configured via JSON (`launch/test-config.json` exemplar) specifying provider/model, dataset path, worker count, and whether to overwrite previous attempts.
3. Successful runs materialize under `playground/<instance_id>/result.json` and are immediately committed to Docker images using the SWE-bench naming convention. `to_swebench.py` translates RepoLaunch outputs into pre-validated instance records for validation.

*Automation characteristics*: RepoLaunch parallelizes across workers, retries failed commands, and integrates Tavily search for tool discovery. Because each environment is captured as a Docker image, subsequent validation and leaderboard agents can reuse identical sandboxes without re-running setup steps.

## Stage 4 – Validation & Test Signal Extraction
1. `python -m swebench.harness.run_validation` applies the gold patch for every candidate instance, runs `test_commands`, and captures `FAIL_TO_PASS` and `PASS_TO_PASS` test cases (`curation/tutorial.md`).
2. The harness reuses SWE-bench functionality, so reporting (`logs/run_evaluation/<run_id>/gold`), status tracking, and reproducibility guarantees carry over.
3. Validation artifacts feed the production scripts as authoritative records of which instances are solvable and which tests assert the fix.

*Automation characteristics*: validation can scale horizontally via `--max_workers`, writes resumable logs, and outputs the data in a format directly consumable by downstream packaging scripts.

## Stage 5 – Dataset Packaging & Publication
1. `swebench/collect/produce/make_full.py` scans validation logs and emits the canonical `full-{date}.jsonl` split.
2. `make_lite.py` samples from date ranges to maintain a cost-effective evaluation subset, while `make_lite` plus `make_full` underpin the public leaderboard splits.
3. `make_verified.py` (described in `swebench/collect/produce/README.md`) applies an LLM-based quality filter (GPT-o3) that labels undesirable instances, yielding `verified-{date}.jsonl` and justification logs.
4. Optional `merge_with_old.py` merges newly validated data with historical releases to maintain backward compatibility.
5. Final artifacts are published to Hugging Face and mirrored to DockerHub, closing the monthly update loop.

*Automation characteristics*: the packaging scripts are idempotent, encode their date stamps, and can be re-run to regenerate releases if upstream validation replays occur.

## Continuous Update Playbook
- **Cadence**: The team targets a monthly refresh with 50 newly verified issues; raw task crawling can be run more frequently, but releases aggregate across the latest month once validation converges (`README.md`).
- **Versioning**: Split filenames include ISO-formatted dates, and Docker tags encode repository plus issue identifiers for traceability.
- **Quality Gates**: Instances must (a) have reproducible tests, (b) succeed through RepoLaunch environment synthesis, and (c) pass gold-patch validation before entering `full`. `verified` adds an LLM moderation step to filter ambiguous or overly easy tasks.
- **Operational Tips**: The tutorial highlights resource tuning (e.g., `ulimit -n 32768` for file descriptor spikes) and recommends running RepoLaunch in tmux due to long runtimes.

## Component Reference
| Layer | Location | Responsibility |
| --- | --- | --- |
| Repository discovery | `curation/crawl_repo.py`, `curation/filter_repo.py` | Find high-signal repos and store JSONL seeds |
| Issue/PR crawler | `curation/swe_task_crawling/` | Build SWE-bench-style instances with metadata |
| Environment builder | `launch/` (RepoLaunch) | Produce containerized, reproducible execution environments |
| Validator | `swebench/harness/` | Apply gold patches, record pass/fail tests |
| Producer | `swebench/collect/produce/` | Publish `full`, `lite`, `verified` splits and logs |

## How to Reason About Dependencies
1. **Data schema compatibility**: Because SWE-bench-Live adheres to SWE-bench’s schema, any SWE-bench evaluator or agent can target the Live dataset by pointing to the Hugging Face feed without code changes.
2. **Environment reuse**: RepoLaunch dramatically lowers onboarding cost for new repos/languages (notably the upcoming multi-language release mentioned in `README.md`) by capturing post-setup state once and sharing Docker images.
3. **Upstream toolkit synergy**: SWE-smith can leverage RepoLaunch outputs to bootstrap training data, while SWE-bench-Live can ingest SWE-smith–generated environments whenever the provenance satisfies its validation gates.

By codifying each stage as a scriptable component and preserving artifacts between stages, SWE-bench-Live eliminates manual bottlenecks in repo triage, environment setup, and validation—making continuous, contamination-free updates feasible for the community.