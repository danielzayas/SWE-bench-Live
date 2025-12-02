# SWE-bench-Live Architecture

## Overview

SWE-bench-Live is a continuously updated benchmark for evaluating AI systems on real-world software engineering tasks. It builds upon the foundation of [SWE-bench](https://swebench.com) by introducing an **automated curation pipeline** that enables monthly dataset updates, scalable environment setup, and contamination-free evaluation.

## Relationship to SWE-bench and SWE-smith

### SWE-bench (Foundation)
**SWE-bench** is the original benchmark for evaluating language models on software engineering tasks. It provides:
- A curated dataset of real GitHub issues paired with their solutions
- Manual environment setup procedures
- Test-based evaluation infrastructure
- Core evaluation harness with Docker-based execution

SWE-bench-Live **forks and extends** the SWE-bench evaluation code with minimal modifications to support the Live dataset while maintaining compatibility.

### SWE-smith (Training Data Generator)
**SWE-smith** is a complementary toolkit designed for:
- Creating execution environments at scale
- Generating SWE-bench-style task instances for **training purposes**
- Producing large-scale training datasets for models

**Key Distinction**: While SWE-smith focuses on creating training data, SWE-bench-Live focuses on creating **evaluation benchmarks** with continuous updates.

### SWE-bench-Live (Automated Evaluation Pipeline)
SWE-bench-Live innovates by:
- **Automating** the entire curation pipeline from instance creation to environment setup
- Enabling **continuous monthly updates** to the benchmark
- Providing **contamination-free evaluation** with fresh, never-seen-before issues
- Scaling to support multiple programming languages and platforms
- Maintaining **full compatibility** with SWE-bench evaluation infrastructure

## Repository Structure

```
swebench/              # Core evaluation code (forked from SWE-bench)
├── collect/           # Dataset building and curation
├── harness/           # Test execution and Docker management
└── inference/         # LLM inference utilities

launch/                # RepoLaunch - Automated environment setup
├── agent/             # LLM-based agentic workflow
├── utilities/         # Helper tools and language handlers
└── workflow.py        # State graph orchestration

curation/              # Dataset curation scripts
└── swe_task_crawling/ # GitHub PR/issue collection pipeline
```

## Automated Curation Pipeline

The SWE-bench-Live curation pipeline consists of five major stages:

### 1. Repository Crawling

**Purpose**: Identify high-quality GitHub repositories to source tasks from

**Components**:
- `curation/crawl_repo.py` - Crawls repositories by star range and language
- `curation/filter_repo.py` - Applies quality control filters

**Process**:
1. Query GitHub API for repositories matching criteria (stars, language)
2. Implement BFS-based star range splitting to handle GitHub's 1000-result limit
3. Filter repositories based on:
   - Minimum 200 pull requests and issues
   - Minimum 200 forks
   - Main language code percentage > 60%
4. Output: `filtered_repos.jsonl`

**Key Features**:
- Token rotation for handling GitHub API rate limits
- Parallel processing with multiple GitHub tokens
- Automatic retry mechanisms

### 2. Issue-PR Pair Collection

**Purpose**: Extract task instances from resolved GitHub issues

**Components**:
- `curation/swe_task_crawling/fetch_pulls.py` - Fetches pull requests and associated issues
- `curation/swe_task_crawling/get_tasks_pipeline.py` - Orchestrates PR collection
- `swebench/collect/build_dataset.py` - Converts PRs to task instances
- `swebench/collect/utils.py` - Core extraction utilities

#### SWE-fixer Enhancement

The scripts in `curation/swe_task_crawling/` are provided by the **[SWE-fixer](https://github.com/InternLM/SWE-Fixer)** team, which optimized the original SWE-bench crawling approach. Instead of relying on regex-based string matching to find issue-PR relationships, SWE-fixer uses:

**GraphQL-based Issue-PR Linking**:
```graphql
timelineItems {
  nodes {
    ... on ClosedEvent {
      closer {
        ... on PullRequest {
          number
        }
      }
    }
  }
}
```

This queries the `ClosedEvent` timeline items of issues to definitively identify which PR closed which issue, providing a **more robust and accurate** approach than searching for keywords like "fixes #123" in PR descriptions.

**Process**:
1. For each repository, use GraphQL to fetch all closed issues after a cutoff date
2. Extract PR-issue relationships from `ClosedEvent` timeline items
3. Identify issue-first pairs (PRs that close specific issues)
4. For each valid PR, extract:
   - **Problem statement** from linked issue
   - **Base commit** (SHA before changes)
   - **Patch** (gold solution - code changes only)
   - **Test patch** (test file modifications)
   - **Hints** (additional context from issue comments before first commit)
5. Validate instances:
   - Must have associated issue
   - Must be merged
   - Must contain valid patch and problem statement
6. Output: `{repo}-task-instances.jsonl`

#### Test Patch Separation

The `extract_patches` function (`swebench/collect/utils.py`) separates test changes from code changes using a path-based heuristic:

```python
def extract_patches(pull: dict, repo: Repo) -> tuple[str, str]:
    patch = requests.get(pull["diff_url"]).text
    patch_test = ""
    patch_fix = ""
    for hunk in PatchSet(patch):
        if any(test_word in hunk.path for test_word in ["test", "tests", "e2e", "testing"]):
            patch_test += str(hunk)
        else:
            patch_fix += str(hunk)
    return patch_fix, patch_test
```

**Logic**: Any file path containing "test", "tests", "e2e", or "testing" is classified as a test patch; everything else is the gold solution patch. This ensures the model doesn't see the test changes during evaluation.

**Data Schema**:
```json
{
  "repo": "owner/repo",
  "pull_number": 123,
  "instance_id": "owner__repo-123",
  "issue_numbers": [456],
  "base_commit": "abc123...",
  "patch": "diff --git...",
  "test_patch": "diff --git...",
  "problem_statement": "Issue description...",
  "hints_text": "Additional context...",
  "created_at": "2024-05-01T..."
}
```

### 3. Environment Setup with RepoLaunch

**Purpose**: Automatically create testable Docker environments for each instance

RepoLaunch is the **core innovation** of SWE-bench-Live - an LLM-based agentic tool that automates the previously manual bottleneck of environment setup.

#### Architecture

RepoLaunch uses a **LangGraph-based state machine** with the following workflow:

```
locate_related_file → select_base_image → start_bash_session → setup → verify → save_result
                                                                   ↑        ↓
                                                                   └────────┘
                                                                   (retry loop)
```

#### Workflow Stages

**Stage 1: Locate Related Files** (`launch/agent/locate.py`)
- Analyzes repository structure to identify relevant documentation
- Searches for setup guides, installation docs, contributing guides
- Uses pattern matching: `README`, `INSTALL`, `CONTRIBUTING`, `docs/`

**Stage 2: Select Base Image** (`launch/agent/base_image.py`)

RepoLaunch uses an **LLM-driven approach** to select the most appropriate Docker base image:

**Selection Process**:
1. **Get candidate images** from language-specific handlers:
   - Python: `python:3.6` through `python:3.11`
   - JavaScript: `node:18`, `node:20`, `node:22`
   - Rust: `rust:1.70` through `rust:1.75`
   - Java: `openjdk:11`, `openjdk:17`, `openjdk:21`
   - Go: `golang:1.19` through `golang:1.22`
   - C/C++: `gcc:11`, `gcc:12`, `ubuntu:20.04`, `ubuntu:22.04`

2. **LLM analyzes repository documentation** (README, installation guides) to determine:
   - Required language version
   - System dependencies
   - OS requirements

3. **LLM selects image** from candidates, wrapping choice in `<image>ubuntu:20.04</image>` tags

4. **Validation**: If selected image not in candidate list, LLM is prompted to try again (up to 5 attempts)

**Important Note**: Docker images created by RepoLaunch are **committed locally** but **not automatically pushed** to remote registries. The code in `launch/workflow.py` (lines 81-94) shows:
```python
# Image commit code is currently commented out:
# session.commit(image_name=key, push=False)
```

Images are intended to be named with the convention: `starryzhang/sweb.eval.x86_64.{instance_id}` and could be pushed to Docker Hub, but this step is disabled in the current implementation. The evaluation harness can work with either local images or pre-existing remote images from the `starryzhang` namespace.

**Stage 3: Start Bash Session** (`launch/agent/setup.py`)
- Launches Docker container with selected base image
- Initializes SetupRuntime with:
  - Bash session inside container
  - Repository cloned to `/testbed`
  - Time-machine package server (for historical Python dependencies)
- Mounts volume for file access

**Stage 4: Setup Agent** (`launch/agent/setup.py`)
- LLM-driven ReAct agent that installs dependencies and prepares environment
- **Actions**:
  - `<command>bash command</command>` - Execute shell commands
  - `<search>query</search>` - Web search for information (Tavily API)
  - `<stop></stop>` - Signal completion
- **System Prompt**: Guides LLM to:
  - Install dependencies (language-specific: pip, npm, cargo, etc.)
  - Set up development environment
  - Handle language-specific package managers
  - Not modify source code
- Iterates up to `max_steps` (default: 20)
- Records all setup commands for reproducibility

**Stage 5: Verify Agent** (`launch/agent/verify.py`)
- Validates that tests can run successfully
- **Actions**:
  - `<command>test command</command>` - Execute test commands
  - `<issue>description or None</issue>` - Report issues or success
- **System Prompt**: Instructs LLM to:
  - Run project test suite
  - Generate detailed pass/fail output (e.g., pytest -rA)
  - Tolerate a few test failures (as long as most pass)
  - Report issues without attempting fixes
- Validates test output format for parsability
- Records final test commands

**Stage 6: Save Result**
- If successful:
  - Commits Docker container to image
  - Namespace: `starryzhang/sweb.eval.x86_64.{instance_id}`
  - Saves setup and test commands
- Records:
  - Duration (minutes)
  - Success/failure status
  - Exception details (if failed)
- Cleans up resources (session, language-specific servers)

#### Agent State Management

The `AgentState` (defined in `launch/agent/state.py`) tracks:
- **Instance metadata**: repo, commit, instance_id, language, created_at
- **LLM provider**: OpenAI/Azure OpenAI client
- **Message history**: Separate for setup and verify agents
- **Execution context**: Docker session, base image, commands
- **Progress tracking**: trials, success status, exceptions
- **Tools**: Web search, language-specific handlers
- **Repository context**: structure, documentation, date

#### Language Support

RepoLaunch supports multiple languages through `language_handlers.py`:
- **Python**: pip, conda, poetry, historical PyPI server (time-machine)
- **JavaScript/TypeScript**: npm, yarn, node version management
- **Rust**: cargo, rustup
- **Go**: go mod
- **C/C++**: make, cmake, build-essential
- **Java**: maven, gradle
- **Ruby**: gem, bundler

Each handler manages:
- Package installation
- Version pinning (time-aware)
- Dependency resolution
- Build commands
- Environment cleanup

#### Parallel Execution

`launch/run.py` orchestrates parallel processing:
- ThreadPoolExecutor with configurable `max_workers`
- Progress tracking with Rich library
- Per-instance workspace isolation
- Graceful error handling and retry logic
- Skip logic for already-processed instances

**Output**: `{workspace_root}/{instance_id}/result.json`

### 4. Validation

**Purpose**: Verify that instances can be successfully solved with gold patches and extract test cases

**Components**:
- `swebench/harness/run_validation.py` - Validates instances with pre/post patch testing
- `swebench/harness/grading.py` - Extracts pass/fail test cases and computes resolution metrics

**Process** (Critical two-phase testing):

**Phase 1: Pre-Patch Testing** (Lines 159-198 in `run_validation.py`):
1. Build Docker container with RepoLaunch environment setup
2. **Run tests WITHOUT applying gold patch** (base commit state)
3. Parse test output to create `pre_test_map` (test_name → status)
4. Save to `pre_test_output.txt` and `pre_test_map.json`

**Phase 2: Post-Patch Testing** (Lines 200-267):
1. Apply the gold patch to the container
2. **Run tests WITH gold patch applied**
3. Parse test output to create `post_test_map` (test_name → status)
4. Save to `test_output.txt` and `post_test_map.json`

**Test Classification** (using `get_p2p_f2p` function):
```python
def get_p2p_f2p(pre_test_map, post_test_map):
    for test, pre_status in pre_test_map.items():
        post_status = post_test_map.get(test)
        
        if is_fail(pre_status) and is_pass(post_status):
            fail2pass.append(test)  # ✅ FAIL_TO_PASS
        elif is_pass(pre_status) and is_pass(post_status):
            pass2pass.append(test)  # ✅ PASS_TO_PASS
```

**Key Validation**: This two-phase approach **confirms**:
- **FAIL_TO_PASS tests actually fail** before the patch (preventing false positives)
- **PASS_TO_PASS tests pass** both before and after (maintenance verification)
- The gold patch successfully resolves the issue

**Filtering**:
- Only instances with **both** FAIL_TO_PASS and PASS_TO_PASS tests are kept
- Instances where F2P tests don't actually fail in pre-patch testing are rejected
- Output: `instance.json` with extracted test lists in `logs/run_validation/{run_id}/gold/{instance_id}/`

**Test Output Parsing**:
- Language-specific parsers in `swebench/harness/log_parsers/`
- Python: pytest output parsing (looks for `PASSED`, `FAILED`, `ERROR` markers)
- JavaScript: Jest/Mocha output parsing
- Rust: cargo test output parsing
- Go: go test output parsing
- Each parser extracts `test_name → status` mapping from detailed test output

### 5. Production Dataset Creation

**Purpose**: Generate final dataset splits with quality filtering

**Components**:
- `swebench/collect/produce/make_full.py` - Creates full dataset
- `swebench/collect/produce/make_lite.py` - Creates lite split (monthly sample)
- `swebench/collect/produce/make_verified.py` - LLM-based quality filtering

**Process**:

**Full Dataset**:
1. Collect all validated instances from `logs/run_validation/{run_id}/gold/*/instance.json`
2. Process each instance with:
   - Convert numeric fields to strings (`pull_number`, `issue_numbers`)
   - Add `difficulty` metrics computed from patch using `unidiff`:
     ```python
     difficulty = {
         "files": number_of_files_changed,
         "hunks": number_of_hunks,
         "lines": number_of_lines_added_or_removed
     }
     ```
3. Merge with previous month's data
4. Output: `datasets/full-{date}.jsonl`

**Full Dataset Schema** (from `swebench/collect/produce/make_full.py`):
```json
{
  "instance_id": "owner__repo-123",
  "repo": "owner/repo",
  "pull_number": "123",              // String (converted from int)
  "issue_numbers": ["456", "789"],   // Array of strings
  "base_commit": "abc123def...",
  "patch": "diff --git a/...",       // Gold solution (code only)
  "test_patch": "diff --git a/...",  // Test changes
  "problem_statement": "Issue description...",
  "hints_text": "Additional context...",
  "created_at": "2024-05-01T12:00:00Z",
  "FAIL_TO_PASS": [                  // Tests that must pass
    "tests/test_feature.py::test_case_1",
    "tests/test_feature.py::test_case_2"
  ],
  "PASS_TO_PASS": [                  // Tests that must remain passing
    "tests/test_other.py::test_existing_1",
    "tests/test_other.py::test_existing_2"
  ],
  "difficulty": {                    // Patch complexity metrics
    "files": 3,
    "hunks": 5,
    "lines": 42
  }
}
```

**Critical Fields**:
- `FAIL_TO_PASS`: Tests that fail on base commit, must pass after fix (resolution metric)
- `PASS_TO_PASS`: Tests that pass on base commit, must still pass after fix (maintenance metric)
- These are populated during validation and are **required** for a complete dataset entry

**Lite Dataset** (For leaderboard evaluation):
1. Sample 50 high-quality instances per month
2. Stratified sampling across repositories
3. Frozen after creation to ensure fair comparison
4. Output: `datasets/lite-{date}.jsonl`

**Verified Dataset** (LLM-filtered):
1. Use reasoning model (GPT-o3) to assess instance quality
2. Classification categories:
   - **Category 1**: Minor vagueness (acceptable)
   - **Category 2**: Highly vague (filter out)
   - **Category 3**: Misleading solutions (filter out)
   - **Category 4**: Inadequate tests (filter out)
   - **Category 5**: Over-constrained tests (filter out)
   - **Category 6**: Trivial fix provided (filter out)
   - **Category 7**: Good instance (keep)
   - **Category 8**: Other issues (filter out)
3. Only Category 7 instances kept in Verified split
4. Filter ratio: ~38% of instances removed
5. Precision: ~72% agreement with human filtering (92% excluding trivial cases)
6. Output: `datasets/verified-{date}.jsonl` + filtering logs

**Quality Metrics**:
- Full split: All validated instances (continuous updates)
- Lite split: 50/month, frozen after creation
- Verified split: 500 initial instances, high-quality subset

## Evaluation Infrastructure

The evaluation infrastructure is forked from SWE-bench with minimal changes to maintain compatibility.

### Components

**Docker-based Execution** (`swebench/harness/docker_build.py`):
- Three-tier image hierarchy:
  - **Base image**: Language/OS foundation
  - **Environment image**: Instance-specific dependencies (from RepoLaunch)
  - **Evaluation image**: With test patches applied
- Instance-level isolation
- Reproducible builds with image caching

**Test Specification** (`swebench/harness/test_spec/test_spec.py`):
- `TestSpec` dataclass containing:
  - Instance metadata (id, repo, version, language)
  - Script lists (repo setup, environment setup, evaluation)
  - Test cases (FAIL_TO_PASS, PASS_TO_PASS)
  - Docker specifications
  - Log parser for language
- Scripts generated from RepoLaunch output

**Evaluation Runner** (`swebench/harness/run_evaluation.py`):
- Parallel instance processing
- Patch application with multiple strategies:
  - `git apply --verbose`
  - `git apply --verbose --reject` (partial application)
  - `patch --batch --fuzz=5 -p1 -i` (fuzzy matching)
- Test execution with timeout
- Log collection and parsing
- Report generation

**Grading** (`swebench/harness/grading.py`):
- Parse test logs using language-specific parsers
- Extract test statuses (PASSED, FAILED, SKIPPED, ERROR)
- Compare against gold test cases
- Compute resolution status:
  - ✅ **Resolved**: All FAIL_TO_PASS pass, all PASS_TO_PASS pass
  - ❌ **Not Resolved**: Otherwise

**Reporting** (`swebench/harness/reporting.py`):
- Aggregate results across instances
- Compute resolution rates
- Generate leaderboard-ready reports

### Running Evaluation

```bash
python -m swebench.harness.run_evaluation \
    --dataset_name SWE-bench-Live/SWE-bench-Live \
    --split lite \
    --namespace starryzhang \
    --predictions_path path/to/predictions.jsonl \
    --max_workers 10 \
    --run_id my-evaluation
```

**Prediction Format**:
```json
{
  "instance_id": "owner__repo-123",
  "model_patch": "diff --git...",
  "model_name_or_path": "my-model"
}
```

## Key Innovations

### 1. Automated Environment Setup
- **Problem**: Manual Docker environment creation was the bottleneck
- **Solution**: RepoLaunch - LLM agentic workflow that automates setup
- **Impact**: Enables scaling to hundreds of repositories and continuous updates

### 2. LangGraph State Machine
- **Modular workflow**: Each agent (setup, verify) has clear responsibility
- **Retry mechanism**: Automatic retries with state preservation
- **Observability**: Full logging of agent reasoning and actions

### 3. Time-Aware Package Resolution
- **Problem**: Historical issues need historical dependencies
- **Solution**: Time-machine PyPI server that serves package versions from specific dates
- **Language handlers**: Extensible to support time-aware resolution for other languages

### 4. Multi-Language Support
- **Original SWE-bench**: Python-only
- **RepoLaunch**: C, C++, C#, Python, Java, Go, JavaScript/TypeScript, Rust
- **Multi-platform**: Linux and Windows support

### 5. Continuous Updates
- **Monthly refresh**: 50 new verified instances added to test split
- **Contamination-free**: Fresh issues never seen during training
- **Frozen subsets**: Lite and Verified splits remain stable for fair comparison

### 6. LLM-based Quality Filtering
- **Automated verification**: GPT-o3 reasoning model classifies instance quality
- **High precision**: 72% agreement with human annotation (92% excluding trivial)
- **Scalable**: Can process thousands of instances without manual review

## Data Flow Diagram

```
┌─────────────────┐
│  GitHub Repos   │
└────────┬────────┘
         │ 1. Crawl & Filter
         ▼
┌─────────────────┐
│ Filtered Repos  │ (filtered_repos.jsonl)
└────────┬────────┘
         │ 2. Collect Issue-PR Pairs
         ▼
┌─────────────────┐
│  Raw Instances  │ (raw_tasks.jsonl)
└────────┬────────┘
         │ 3. RepoLaunch
         ▼
┌─────────────────┐
│ Setup Results   │ (result.json per instance)
│  + Docker Image │
└────────┬────────┘
         │ 4. Validation
         ▼
┌─────────────────┐
│  Pre-validated  │ (pre-validated-instances.jsonl)
│   + Test Info   │
└────────┬────────┘
         │ 5. Production
         ▼
┌─────────────────────────────────────┐
│  Final Datasets                      │
│  • full-{date}.jsonl (all)          │
│  • lite-{date}.jsonl (50/month)     │
│  • verified-{date}.jsonl (filtered) │
└─────────────────────────────────────┘
```

## Frequently Asked Questions

### Q1: What is SWE-fixer and how does it help with issue-PR pair extraction?

**SWE-fixer** is a toolkit from the [InternLM team](https://github.com/InternLM/SWE-Fixer) that provides optimized GitHub data collection scripts. SWE-bench-Live's `curation/swe_task_crawling/` scripts are based on SWE-fixer's approach.

**Key Innovation**: Instead of the original SWE-bench's regex-based string matching (looking for "fixes #123" patterns in PR text), SWE-fixer uses **GitHub's GraphQL API** to query the issue timeline:

```graphql
timelineItems {
  nodes {
    ... on ClosedEvent {
      closer {
        ... on PullRequest {
          number
        }
      }
    }
  }
}
```

This directly queries which PR closed which issue through the `ClosedEvent` relationship, providing **definitive linkage** rather than heuristic matching. This approach is:
- More accurate (no false positives from similar text)
- More complete (catches PRs that don't use keywords)
- More efficient (single GraphQL query vs. multiple REST calls)

### Q2: How does SWE-bench-Live separate test_patch from patch for a given PR?

The separation happens in `swebench/collect/utils.py` using the `extract_patches` function with a **path-based heuristic**:

```python
def extract_patches(pull: dict, repo: Repo) -> tuple[str, str]:
    patch = requests.get(pull["diff_url"]).text
    patch_test = ""
    patch_fix = ""
    for hunk in PatchSet(patch):
        if any(test_word in hunk.path for test_word in ["test", "tests", "e2e", "testing"]):
            patch_test += str(hunk)
        else:
            patch_fix += str(hunk)
    return patch_fix, patch_test
```

**Logic**:
1. Downloads the complete diff from GitHub
2. Parses it using `unidiff` library into individual hunks (file changes)
3. Checks each file path for test-related keywords: `["test", "tests", "e2e", "testing"]`
4. Classifies as:
   - **test_patch**: Any file containing test keywords → shown to evaluation harness to apply tests
   - **patch**: Everything else → the gold solution that models must reproduce

This ensures models don't see the test changes during problem-solving, maintaining evaluation integrity.

### Q3: How does RepoLaunch select a base Docker image? Are images pushed to a container registry?

**Selection Process** (LLM-driven):

1. **Language Handler provides candidates**: Each language has a predefined list of suitable base images:
   - Python: `python:3.6` through `python:3.11`
   - JavaScript: `node:18`, `node:20`, `node:22`
   - Rust: `rust:1.70-1.75`, etc.

2. **LLM analyzes repository**: The `select_base_image` agent (`launch/agent/base_image.py`) reads repository documentation (README, installation guides) and selects the most appropriate image based on:
   - Required language version
   - System dependencies mentioned
   - Build tools needed

3. **Format**: LLM responds with `<image>python:3.9</image>` tag

4. **Validation**: Selection must be from candidate list (retries up to 5 times if not)

**Container Registry Publishing**:

Images are **NOT automatically pushed** to remote registries. The code in `launch/workflow.py` lines 81-94 shows:

```python
# Docker image commit is currently COMMENTED OUT:
# try:
#     session.commit(image_name=key, push=False)
#     logger.info(f"Image {key} committed successfully.")
# except Exception as e:
#     logger.error(f"Failed to commit image: {e}")
```

**Intended naming convention**: `starryzhang/sweb.eval.x86_64.{instance_id}`

**Current behavior**: 
- Images are built and used locally during RepoLaunch
- Not committed as Docker images after successful setup
- Evaluation harness can reference pre-existing images from `starryzhang` namespace if they exist
- Setup commands are saved and can recreate environments from base images

### Q4: Does SWE-bench-Live validate that F2P tests fail before the gold patch is applied?

**Yes!** This is a critical feature to prevent false positives. The validation process in `swebench/harness/run_validation.py` uses **two-phase testing**:

**Phase 1: Pre-Patch Testing** (lines 159-198):
```python
# 1. Run tests WITHOUT gold patch (base commit state)
pre_test_output, timed_out, total_runtime = exec_run_with_timeout(
    container, "/bin/bash /eval.sh", timeout
)

# 2. Parse test results
pre_test_map, found = get_logs_eval(test_spec, pre_test_output_path)
# pre_test_map = {"tests/test_x.py::test_a": "FAILED", ...}
```

**Phase 2: Post-Patch Testing** (lines 200-267):
```python
# 1. Apply gold patch
applied_patch = container.exec_run(f"git apply {DOCKER_PATCH}")

# 2. Run tests WITH gold patch applied
test_output, timed_out, total_runtime = exec_run_with_timeout(
    container, "/bin/bash /eval.sh", timeout
)

# 3. Parse test results
post_test_map, found = get_logs_eval(test_spec, test_output_path)
# post_test_map = {"tests/test_x.py::test_a": "PASSED", ...}
```

**Comparison** (`get_p2p_f2p` function, lines 72-95):
```python
for test, pre_status in pre_test_map.items():
    post_status = post_test_map.get(test)
    
    if is_fail(pre_status) and is_pass(post_status):
        fail2pass.append(test)  # ✅ Confirmed F2P
    elif is_pass(pre_status) and is_pass(post_status):
        pass2pass.append(test)  # ✅ Confirmed P2P
```

**Result**: Only tests that **actually fail** before the patch and **pass** after are included in FAIL_TO_PASS. This guarantees the gold patch truly resolves the issue.

### Q5: What is the data format for full-*.jsonl artifacts?

The `full-{date}.jsonl` file (produced by `swebench/collect/produce/make_full.py`) contains one JSON object per line with this schema:

```json
{
  "instance_id": "owner__repo-123",
  "repo": "owner/repo",
  "pull_number": "123",              // String (converted from int)
  "issue_numbers": ["456"],          // Array of strings
  "base_commit": "abc123def...",
  "patch": "diff --git a/file.py...",
  "test_patch": "diff --git a/test_file.py...",
  "problem_statement": "Description of the issue...",
  "hints_text": "Additional context from comments...",
  "created_at": "2024-05-01T12:00:00Z",
  "FAIL_TO_PASS": [
    "tests/test_module.py::test_function_a",
    "tests/test_module.py::test_function_b"
  ],
  "PASS_TO_PASS": [
    "tests/test_other.py::test_existing_1",
    "tests/test_other.py::test_existing_2"
  ],
  "difficulty": {
    "files": 3,
    "hunks": 5,
    "lines": 42
  }
}
```

**Key Field Details**:

| Field | Type | Description |
|-------|------|-------------|
| `instance_id` | string | Unique identifier: `{owner}__{repo}-{pr_number}` |
| `repo` | string | Repository full name |
| `pull_number` | string | PR number (converted to string) |
| `issue_numbers` | string[] | Associated issue numbers (converted to strings) |
| `base_commit` | string | Git SHA to checkout before applying patch |
| `patch` | string | Gold solution diff (code changes only, no tests) |
| `test_patch` | string | Test file changes (to verify solution works) |
| `problem_statement` | string | Issue description from GitHub |
| `hints_text` | string | Comments from issue thread before first commit |
| `created_at` | string | ISO timestamp of issue/PR creation |
| `FAIL_TO_PASS` | string[] | Test names that fail before patch, pass after |
| `PASS_TO_PASS` | string[] | Test names that pass both before and after |
| `difficulty` | object | Patch complexity: files changed, hunks, lines modified |

**Critical Requirements**:
- Both `FAIL_TO_PASS` and `PASS_TO_PASS` must be non-empty
- These fields are populated during validation phase
- Instances missing these fields were filtered out (couldn't validate with gold patch)

**Difficulty Calculation** (using `unidiff` library):
```python
patch = PatchSet(diff_text)
difficulty = {
    "files": len(patch),  # Number of files changed
    "hunks": sum(len(f) for f in patch),  # Number of change hunks
    "lines": sum(1 for f in patch for h in f for l in h 
                 if l.is_added or l.is_removed)  # Lines added/removed
}
```

## Configuration and Extensibility

### RepoLaunch Configuration

Configured via JSON file (`config.json`):
```json
{
  "llm_provider_name": "OpenAI",
  "model_config": {
    "model_name": "gpt-4.1",
    "temperature": 0.0
  },
  "workspace_root": "playground/run/",
  "dataset": "input/tasks.jsonl",
  "print_to_console": false,
  "max_workers": 5,
  "overwrite": false,
  "instance_id": null,
  "first_N_repos": -1
}
```

### Adding Language Support

To add a new language:

1. **Create language handler** in `launch/utilities/language_handlers.py`:
```python
class NewLanguageHandler(LanguageHandler):
    def get_package_server_instructions(self, date):
        # Return instructions for time-aware package resolution
        pass
    
    def get_setup_instructions(self):
        # Return language-specific setup instructions
        pass
    
    def cleanup_environment(self, session, server):
        # Cleanup resources
        pass
```

2. **Add log parser** in `swebench/harness/log_parsers/`:
```python
def parse_log_newlang(log: str) -> dict[str, str]:
    # Parse test output to extract test_name -> status mapping
    pass
```

3. **Register in constants** (`swebench/harness/constants/newlang.py`):
```python
MAP_REPO_TO_EXT["owner/repo"] = "newlang"
```

### Customizing Agents

Agent behavior is controlled by:
- **System prompts** in `launch/agent/setup.py` and `verify.py`
- **Action schemas** (Pydantic models)
- **Workflow parameters** (`max_trials`, `max_steps` in `launch/workflow.py`)

## Performance and Scalability

### Throughput
- **Parallel processing**: 5-20 instances concurrently (configurable)
- **Average duration**: 10-30 minutes per instance
- **Success rate**: 70-80% of instances successfully launched

### Resource Requirements
- **Compute**: Docker-enabled Linux machine
- **Memory**: 4-8GB per worker
- **Storage**: 10-50GB per instance (Docker images)
- **API costs**: OpenAI API calls ($1-5 per instance for GPT-4)

### Optimizations
- **Workspace reuse**: Skip already-processed instances
- **Image caching**: Docker layer caching reduces rebuild time
- **Token rotation**: Multiple GitHub tokens for high API throughput
- **Graceful degradation**: Continue on individual failures

## Testing and Validation

### Quality Assurance
1. **Gold patch validation**: All instances must resolve with gold patch
2. **Test suite completeness**: Both FAIL_TO_PASS and PASS_TO_PASS required
3. **LLM filtering**: Verified split uses reasoning model for quality check
4. **Human review**: Spot-checking of filtered instances

### Metrics
- **Resolution rate**: % of instances solved by gold patch
- **Launch success rate**: % of instances with successful environment setup
- **Filter precision**: Agreement with human annotation
- **Test stability**: Consistent pass/fail across multiple runs

## Future Directions

### Planned Enhancements
1. **LLM-based test extraction**: Replace hardcoded parsers with LLM agent
2. **Cross-language contamination detection**: Identify similar issues across repos
3. **Difficulty estimation**: Automated classification of task complexity
4. **Multi-step tasks**: Support for issues requiring multiple commits
5. **Streaming evaluation**: Real-time result reporting during evaluation

### Community Contributions
The repository welcomes contributions to:
- Add support for new languages
- Improve agent prompts and strategies
- Enhance test output parsing
- Optimize Docker image sizes
- Improve launch success rates

## Comparison Summary

| Feature | SWE-bench | SWE-smith | SWE-bench-Live |
|---------|-----------|-----------|----------------|
| **Purpose** | Evaluation benchmark | Training data generation | Continuously updated evaluation |
| **Curation** | Manual | Semi-automated | Fully automated |
| **Updates** | Static | On-demand | Monthly (50/month) |
| **Environment Setup** | Manual Docker configs | Automated | RepoLaunch (LLM agent) |
| **Languages** | Python-focused | Python-focused | Multi-language (8+) |
| **Scale** | ~2,300 instances | Thousands of instances | 1,500+ and growing |
| **Use Case** | Model evaluation | Model training | Fresh evaluation, leaderboard |
| **Contamination Risk** | High (static dataset) | N/A (training data) | Low (continuous updates) |
| **Dataset Splits** | Full, Lite, Verified | Fine-tuning dataset | Full, Lite, Verified |

## References

- **SWE-bench-Live Paper**: [arXiv:2505.23419](https://arxiv.org/abs/2505.23419)
- **SWE-bench Paper**: [ICLR 2024](https://openreview.net/forum?id=VTF8yNQM66)
- **SWE-smith**: [Website](https://swesmith.com/) | [GitHub](https://github.com/SWE-bench/SWE-smith)
- **Leaderboard**: [swe-bench-live.github.io](https://swe-bench-live.github.io/)
- **Dataset**: [HuggingFace](https://huggingface.co/datasets/SWE-bench-Live/SWE-bench-Live)

---

*This document reflects the architecture as of December 2024. For the latest updates, see the [repository](https://github.com/microsoft/SWE-bench-Live) and [tutorial](./curation/tutorial.md).*
