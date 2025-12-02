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

## Implementation Q&A

### What is SWE-fixer and how are Issue–PR pairs extracted?
The SWE-Fixer team contributed the crawling scripts under `curation/swe_task_crawling/` (`README.md`). Instead of the original SWE-bench heuristic that matched issue IDs by string similarity, SWE-Fixer queries the GitHub GraphQL API for each repo’s closed issues and inspects their timeline events to see which pull request actually closed them (`get_pull_issue_dict.py`). Only issues whose `ClosedEvent` references a specific PR (and fall after the `--cutoff-date`) are emitted, yielding an explicit `pull_number → [issue_numbers]` mapping that feeds `build_dataset.py`. This makes the PR–issue linkage deterministic, supports repositories with nonstandard naming, and allows resumes/retries because the intermediate JSONL files capture every matched pair.

### How are `patch` and `test_patch` separated?
`build_dataset.py` calls `extract_patches` in `curation/swe_task_crawling/utils.py`, which downloads the PR’s unified diff and parses it with `unidiff.PatchSet`. Each hunk is classified by file path: files whose paths include tokens such as `test`, `tests`, `testing`, or `e2e` are appended to `test_patch`, while every other file is routed to `patch`. This heuristic mirrors the original SWE-bench behavior and ensures the evaluation harness can apply the code fix separately from the tests that assert it.

### How is the base Docker image selected, and are Dockerfiles emitted?
RepoLaunch inspects repo docs (the `locate_related_file` step) and then asks an LLM to choose a base image from a language-specific allowlist (`launch/launch/agent/base_image.py`, `launch/launch/utilities/language_handlers.py`). For example, Python repos may select from `python:3.6`–`python:3.11`, while Java projects pick among official `openjdk` tags. The agent never writes a Dockerfile; instead it starts a container from the chosen base image, runs the synthesized `setup_commands`, records the `test_commands`, and, upon success, prepares to snapshot the container into an image named `starryzhang/sweb.eval.<arch>.<instance_id>` inside `save_result` (`launch/launch/workflow.py`). The `session.commit` call that performs the actual image commit/push is hook-ready (currently commented for local runs), so the published artifact is the JSON recipe plus the resulting Docker image tag—not a bespoke Dockerfile.

### Does validation ensure Fail-to-Pass (F2P) tests actually fail before patching?
Yes. `swebench.harness.run_validation` first executes the repository’s test command inside the environment before any patch is applied, storing the pre-patch test map (`LOG_PRE_TEST_OUTPUT`). Only after capturing those failures does it apply the gold patch and rerun the tests, producing a post-patch map. `get_p2p_f2p` then labels a test as `FAIL_TO_PASS` only if it was failing/erroring before and passing afterward, so every F2P entry is grounded in an observed pre-patch failure.

### What does a `full-*.jsonl` line look like?
`swebench/collect/produce/make_full.py` walks every validated `instance.json` file, ensures both `FAIL_TO_PASS` and `PASS_TO_PASS` arrays are present, normalizes string fields, and writes each instance as a single JSON line. Each record contains:
- The provenance fields from curation (`repo`, `pull_number`, `issue_numbers`, `base_commit`, `created_at`, `commit_urls`, natural-language `problem_statement`/`hints_text`, and the raw `patch`/`test_patch` payloads).
- The RepoLaunch outputs (`setup_commands`, `test_cmds`, `base_image`, `log_parser`).
- Validation metadata (`FAIL_TO_PASS`, `PASS_TO_PASS`, and optionally timing/runtime stats).
- A computed `difficulty` object summarizing the patch’s number of files/hunks/changed lines (added right before writing).
This JSONL format is what gets uploaded to Hugging Face (e.g., `full-2025-09-17.jsonl`), so downstream consumers can stream the file line-by-line without extra packaging.

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