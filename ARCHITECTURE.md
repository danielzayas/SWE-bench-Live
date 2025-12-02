# SWE-bench-Live Architecture

## Overview

SWE-bench-Live is a continuously updated benchmark for evaluating AI systems' ability to resolve real-world software engineering tasks. It builds upon the foundation of SWE-bench but introduces an **automated curation pipeline** that streamlines the entire process from instance creation to environment setup, removing manual bottlenecks and enabling scalability and continuous updates.

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

## Directory Structure

```
SWE-bench-Live/
├── swebench/             # Evaluation code (forked from SWE-bench)
│   ├── harness/          # Test execution and grading
│   ├── collect/          # Dataset collection and production
│   └── versioning/       # Version management utilities
├── launch/               # RepoLaunch environment setup tool
│   ├── agent/            # LLM agents (setup, verify, etc.)
│   ├── utilities/        # Language handlers, config, etc.
│   └── workflow.py       # Workflow graph definition
├── curation/             # Curation pipeline scripts
│   ├── crawl_repo.py     # Repository crawling
│   ├── filter_repo.py    # Repository filtering
│   └── swe_task_crawling/ # Issue-PR pair extraction
└── assets/               # Documentation assets
```

- SWE-bench-Live **forks the evaluation code** from SWE-bench (`swebench/` directory) with minimal modifications
- The evaluation harness, test execution, and grading logic remain consistent with SWE-bench to reduce migration effort
- SWE-bench-Live extends SWE-bench by:
  - Automating the curation pipeline (SWE-bench required manual curation)
  - Enabling continuous monthly updates (SWE-bench was a static dataset)
  - Supporting multi-language repositories (SWE-bench primarily focused on Python/PyPI)

## Automated Curation Pipeline

The SWE-bench-Live curation pipeline consists of five main stages:

```
Repository Crawling → Issue-PR Pair Extraction → Environment Setup (RepoLaunch) → Validation → Dataset Production
```

### Stage 1: Repository Crawling

**Purpose**: Identify high-quality GitHub repositories to source tasks from

**Components**:
- `curation/crawl_repo.py` - Crawls repositories by star range and language
- `curation/filter_repo.py` - Applies quality control filters

**Process**:
1. **Raw Repository Collection**: Crawls GitHub repositories based on criteria:
   - Language (e.g., Python, Java, Go, Rust)
   - Star count range (e.g., 10,000-100,000 stars)
   - Uses multiple GitHub tokens to handle rate limits

2. **Quality Filtering**: Filters repositories based on:
   - Minimum number of pull requests and issues (>200)
   - Minimum number of forks (>200)
   - Main language code percentage (>60%)

**Output**: `filtered_repos.jsonl` - List of high-quality repositories suitable for task extraction

### Stage 2: Issue-PR Pair Extraction

**Purpose**: Extract task instances from resolved GitHub issues

**Components**:
- `curation/swe_task_crawling/fetch_pulls.py` - Fetches pull requests and associated issues
- `curation/swe_task_crawling/get_tasks_pipeline.py` - Orchestrates PR collection
- `swebench/collect/build_dataset.py` - Converts PRs to task instances
- `swebench/collect/utils.py` - Core extraction utilities

**Process**:
1. **Pull Request Collection**: For each repository, fetches all pull requests created after a cutoff date
   - Uses GitHub API to retrieve PR metadata
   - Stores in `<repo>-prs.jsonl` files

2. **Issue-PR Matching**: Converts PRs to SWE-bench-like task instances
   - Identifies associated issues using **SWE-fixer**'s improved matching approach
   - Extracts gold patches from PR diffs
   - Separates test patches from code patches
   - Filters for PRs that modify test files (indicating testable tasks)
   - Creates task instances with:
     - Repository information
     - Base commit
     - Issue description
     - Gold patch (code changes)
     - Test patch (test modifications)

#### SWE-fixer and Issue-PR Pair Extraction

**SWE-fixer** is a tool developed by the [InternLM team](https://github.com/InternLM/SWE-Fixer) that provides optimized scripts for issue-PR pair extraction. The scripts in `curation/swe_task_crawling/` are provided by SWE-fixer and replace the original SWE-bench crawling approach.

**How SWE-fixer improves issue-PR matching**:
- **Robust GraphQL-based matching**: Uses GitHub's GraphQL API to identify which issues are resolved by which pull requests
- **Event-based linking**: Analyzes GitHub timeline events (specifically `ClosedEvent` nodes) to find when issues were closed by pull requests
- **More reliable than string matching**: The original SWE-bench approach relied on string matching in PR descriptions (e.g., "Fixes #123"), which could miss many valid pairs. SWE-fixer uses GitHub's native event system for more accurate matching
- **Handles edge cases**: Better handles cases where issues are closed by commits within PRs, or when multiple PRs reference the same issue

The key script `get_pull_issue_dict.py` uses GraphQL queries to:
1. Fetch closed issues from repositories
2. Examine timeline events to find which PRs closed which issues
3. Build a mapping of PR numbers to resolved issue numbers

#### Test Patch Separation

The `extract_patches()` function in `curation/swe_task_crawling/utils.py` separates the test patch from the main code patch:

**Process**:
1. **Fetch PR diff**: Retrieves the full unified diff from the PR's `diff_url`
2. **Parse with PatchSet**: Uses the `unidiff` library to parse the diff into individual file hunks
3. **Path-based classification**: For each hunk in the diff:
   - If the file path contains any of: `'test'`, `'tests'`, `'e2e'`, or `'testing'` → goes to `test_patch`
   - Otherwise → goes to `patch` (the main code patch)
4. **Return both patches**: Returns `(patch_fix, patch_test)` as separate strings

This separation is critical because:
- The **patch** (code changes) is what agents need to reproduce
- The **test_patch** (test modifications) is used to identify which tests should fail before the fix and pass after
- Both patches are applied to the base commit during validation

**Key Scripts**:
- `fetch_pulls.py`: Retrieves PR data from GitHub
- `get_pull_issue_dict.py`: Maps PRs to issues using SWE-fixer's GraphQL approach
- `build_dataset.py`: Converts PRs to task instances (calls `extract_patches()`)
- `get_tasks_pipeline.py`: Orchestrates the pipeline

**Output**: `raw_tasks.jsonl` - Candidate task instances ready for environment setup, each containing separate `patch` and `test_patch` fields

### Stage 3: Environment Setup with RepoLaunch

**Purpose**: Automatically create testable Docker environments for each instance

**Location**: `launch/`

**RepoLaunch** is the **core innovation** of SWE-bench-Live. It is an LLM-based agentic tool that automates the creation of testable containerized environments for any GitHub repository. This addresses the major bottleneck in SWE-bench where environment setup was manual.

#### RepoLaunch Architecture

**Workflow Graph** (defined in `launch/launch/workflow.py`):

```
START → locate_related_file → select_base_image → start_bash_session → setup → verify → save_result → END
                                                                          ↑         ↓
                                                                          └─────────┘
                                                                        (retry loop)
```

**Components**:

1. **Base Image Selection** (`launch/agent/base_image.py`):
   - **LLM-based analysis**: Uses an LLM to analyze repository documentation and related files
   - **Language-specific candidates**: Each language handler provides a list of candidate base images (e.g., `python:3.9`, `python:3.10`, `node:18`, `ubuntu:20.04`)
   - **Context-aware selection**: The LLM receives:
     - Repository documentation (README, setup files, etc.)
     - Language requirements
     - Common system dependencies
   - **Selection process**:
     1. LLM analyzes the repository context
     2. Recommends a base image from the candidate list
     3. Validates the selection is in the candidate list (retries if not)
     4. Returns the selected base image name
   - **Supported languages**: Python, Java, Go, JavaScript/TypeScript, Rust, C/C++, C#, PHP, Ruby
   
   **Docker Image Publishing**:
   - **No Dockerfile creation**: RepoLaunch does not generate Dockerfiles. Instead, it:
     1. Starts with the selected base image
     2. Runs setup commands interactively in a container
     3. Commits the container state to a new Docker image
   - **Image naming convention**: `{namespace}/sweb.eval.{arch}.{instance_id}`
     - Default namespace: `starryzhang`
     - Architecture: `x86_64` (or platform-specific)
     - Instance ID: Repository name with special characters replaced (e.g., `__` → `_1776_`)
   - **Example**: `starryzhang/sweb.eval.x86_64.streamlink_1776_streamlink-6535`
   - **Publishing**: Images are committed locally (with optional push to DockerHub). The commit functionality is available in `launch/launch/runtime.py` but may be commented out in production workflows
   - **Note**: The evaluation harness (`swebench/harness`) uses Dockerfiles for building evaluation images, but RepoLaunch uses container state commits for environment setup images

2. **Setup Agent** (`launch/agent/setup.py`):
   - LLM-powered agent that installs dependencies and configures the environment
   - Uses ReAct (Reasoning + Acting) pattern:
     - **Action types**: `command`, `search`, `stop`
     - Executes bash commands in Docker container
     - Can search the web for solutions to setup issues
     - Iterates until tests can run successfully
   - Language-specific handlers provide guidance for different ecosystems

3. **Verification Agent** (`launch/agent/verify.py`):
   - Verifies that the environment is correctly set up
   - Runs test commands and checks for proper test output
   - Ensures test framework produces detailed pass/fail status for each test
   - Reports issues if setup is incomplete

4. **State Management** (`launch/agent/state.py`):
   - Maintains agent state throughout the workflow
   - Tracks setup commands, test commands, base image, and session information
   - Handles retries and error recovery

The `AgentState` (defined in `launch/agent/state.py`) tracks:
- **Instance metadata**: repo, commit, instance_id, language, created_at
- **LLM provider**: OpenAI/Azure OpenAI client
- **Message history**: Separate for setup and verify agents
- **Execution context**: Docker session, base image, commands
- **Progress tracking**: trials, success status, exceptions
- **Tools**: Web search, language-specific handlers
- **Repository context**: structure, documentation, date

5. **Runtime** (`launch/runtime.py`):
   - Manages Docker container sessions
   - Provides bash interface for agents
   - Handles file operations and command execution
   - Supports time-aware environment setup (using `created_at` timestamp)

**Key Features**:
- **Parallel Processing**: Can process multiple instances concurrently (`max_workers` config)
- **Retry Logic**: Automatically retries failed setups up to `max_trials`
- **Language Support**: Extensible language handlers for different ecosystems
- **Time-Aware Setup**: Uses historical package versions based on issue creation date
- **Docker Image Committing**: Successful setups are committed to Docker images for reuse

**Output**: 
- `result.json` files for each instance containing:
  - Setup commands used
  - Test commands identified
  - Base image selected
  - Success/failure status
- Docker images: `{namespace}/sweb.eval.{arch}.{instance_id}`

**Export**: `launch/to_swebench.py` converts RepoLaunch results to SWE-bench-Live instance format

### Stage 4: Validation

**Location**: `swebench/harness/run_validation.py`

**Process**:
1. **Pre-Patch Test Execution**: 
   - Runs the test suite **before** applying the gold patch
   - Captures test output and parses individual test results
   - Creates `pre_test_map`: Maps test names to their status (PASSED, FAILED, ERROR, SKIPPED)
   - **Critical validation**: This step ensures that FAIL_TO_PASS tests actually fail before the patch is applied

2. **Gold Patch Application**: 
   - Applies the gold patch to the codebase
   - Uses multiple fallback methods: `git apply`, `git apply --reject`, `patch` command

3. **Post-Patch Test Execution**: 
   - Runs the test suite **after** applying the gold patch
   - Captures test output and parses individual test results
   - Creates `post_test_map`: Maps test names to their status

4. **Test Classification**: 
   - Compares `pre_test_map` and `post_test_map` to identify:
     - **FAIL_TO_PASS**: Tests that have status `FAILED` or `ERROR` before patch and `PASSED` or `XFAIL` after patch (validates the fix works)
     - **PASS_TO_PASS**: Tests that have status `PASSED` or `XFAIL` both before and after patch (regression prevention)
   - Only instances with both FAIL_TO_PASS and PASS_TO_PASS tests are included in the final dataset

(using `get_p2p_f2p` function):
```python
def get_p2p_f2p(pre_test_map, post_test_map):
    for test, pre_status in pre_test_map.items():
        post_status = post_test_map.get(test)
        
        if is_fail(pre_status) and is_pass(post_status):
            fail2pass.append(test)  # ✅ FAIL_TO_PASS
        elif is_pass(pre_status) and is_pass(post_status):
            pass2pass.append(test)  # ✅ PASS_TO_PASS
```

**Validation of F2P Tests**:
- **Yes, SWE-bench-Live validates that F2P tests fail before the gold patch is applied**
- The validation process explicitly:
  1. Runs tests on the base commit (before patch)
  2. Records which tests fail
  3. Applies the gold patch
  4. Runs tests again
  5. Verifies that previously failing tests now pass
- This ensures that the test cases actually validate the fix, not just that tests pass after the patch

**Test Output Parsing**:
- Language-specific parsers in `swebench/harness/log_parsers/`
- Python: pytest output parsing (looks for `PASSED`, `FAILED`, `ERROR` markers)
- JavaScript: Jest/Mocha output parsing
- Rust: cargo test output parsing
- Go: go test output parsing
- Each parser extracts `test_name → status` mapping from detailed test output

**Output**: Validation logs with test results for each instance, including `pre_test_map.json` and `post_test_map.json`. Ouput `instance.json` with extracted test lists in `logs/run_validation/{run_id}/gold/{instance_id}/`.

### Stage 5: Dataset Production

**Purpose**: Generate final dataset splits with quality filtering

**Components**:
- `swebench/collect/produce/make_full.py` - Creates full dataset
- `swebench/collect/produce/make_lite.py` - Creates lite split (monthly sample)
- `swebench/collect/produce/make_verified.py` - LLM-based quality filtering

**Process**:

1. **Full Dataset Creation** (`make_full.py`):
   - Collects all validated instances with both FAIL_TO_PASS and PASS_TO_PASS tests
   - Adds difficulty metrics (files, hunks, lines changed in patch)
   - Outputs: `full-{date}.jsonl`

#### Full Dataset Data Format

The `full-*.jsonl` files contain one JSON object per line (JSONL format). Each instance includes the following fields:

**Core Fields**:
- `repo` (str): Repository full name in format `owner/repo`
- `pull_number` (str): Pull request number that fixed the issue
- `instance_id` (str): Unique identifier in format `owner__repo-{pull_number}` (slashes replaced with `__`)
- `issue_numbers` (list[str]): List of issue numbers resolved by this PR
- `base_commit` (str): Git commit SHA that the PR is based on
- `created_at` (str): ISO timestamp when the PR was created

**Patch Fields**:
- `patch` (str): Unified diff patch containing code changes (excludes test files)
- `test_patch` (str): Unified diff patch containing test file modifications

**Problem Description**:
- `problem_statement` (str): Issue title and body text describing the problem
- `hints_text` (str): Issue comments created before the first commit in the PR (hints available to developers)
- `all_hints_text` (str): All issue comments (for reference)
- `commit_urls` (list[str]): URLs to commits in the PR

**Validation Results** (added during validation):
- `FAIL_TO_PASS` (list[str]): List of test names that fail before patch and pass after
- `PASS_TO_PASS` (list[str]): List of test names that pass both before and after patch

**Metadata** (added during production):
- `difficulty` (dict): Difficulty metrics computed from the patch:
- `files` (int): Number of files modified
- `hunks` (int): Number of diff hunks
- `lines` (int): Number of lines added/removed (excluding context lines)

**Example Instance** (from `test-dataset.jsonl`):
```json
{
  "repo": "amoffat/sh",
  "pull_number": "744",
  "instance_id": "amoffat__sh-744",
  "issue_numbers": ["743"],
  "base_commit": "b658ce261b56c02cb8635416d310ca8f30f4dc90",
  "patch": "diff --git a/sh.py b/sh.py\n...",
  "test_patch": "diff --git a/tests/sh_test.py b/tests/sh_test.py\n...",
  "problem_statement": "Need way for await sh.command to return RunningCommand\n...",
  "hints_text": "I think that's a reasonable request...",
  "all_hints_text": "I think that's a reasonable request...",
  "commit_urls": ["https://github.com/amoffat/sh/commit/..."],
  "created_at": "2025-01-08T22:39:32Z",
  "FAIL_TO_PASS": ["tests/sh_test.py::test_async_return_cmd"],
  "PASS_TO_PASS": ["tests/sh_test.py::test_async_exc", ...],
  "difficulty": {"files": 1, "hunks": 1, "lines": 3}
}
```

2. **Lite Dataset Creation** (`make_lite.py`):
   - Samples up to 50 instances per month from the full dataset
   - Maintains temporal distribution
   - Used for cost-effective evaluation
   - Outputs: `lite-{date}.jsonl`
   - **Note**: Lite split remains frozen for fair leaderboard comparisons

3. **Verified Dataset Creation** (`make_verified.py`):
   - Uses LLM (GPT-o3) to filter high-quality instances
   - Categorizes instances into 8 categories:
     1. Minor vagueness in issue description
     2. Highly vague/incomplete issue
     3. Misleading proposed solutions
     4. Inadequate test cases
     5. Unnecessarily narrow constraints
     6. Trivial (solution in issue)
     7. **Good instance** (suitable for evaluation)
     8. Other issues (environmental, licensing, etc.)
   - Filters out categories 1-6 and 8, keeping only category 7
   - Filter ratio: ~38% of instances filtered out
   - Outputs: `verified-{date}.jsonl` and `verified-log-{date}.jsonl`

4. **Merging** (`merge_with_old.py`):
   - Merges new instances with previously published dataset
   - Maintains version history

**Dataset Splits**:
- **full**: All validated instances (continuously updated)
- **lite**: Monthly sample of 50 instances (frozen for leaderboard)
- **verified**: LLM-filtered high-quality subset (frozen)

## Continuous Updates

### Monthly Update Process

1. **Crawling**: New repositories and issues are crawled monthly
2. **Processing**: New instances go through the full pipeline
3. **Validation**: Instances are validated with gold patches
4. **Production**: New instances are added to the `full` split
5. **Publishing**: Updated dataset is published to Hugging Face

### Update Strategy

- **Full Split**: Updated monthly with all new validated instances
- **Lite Split**: Remains frozen to ensure fair leaderboard comparisons
- **Verified Split**: Remains frozen to maintain evaluation consistency
- **Monthly Addition**: ~50 new instances added to test split each month

### Automation Benefits

- **Scalability**: Can process hundreds of repositories in parallel
- **Consistency**: Automated pipeline ensures consistent quality
- **Speed**: LLM-based setup reduces manual intervention time
- **Coverage**: Can handle diverse languages and project structures
- **Freshness**: Monthly updates keep benchmark current

## Key Technologies

### LLM Integration
- **OpenAI API**: Primary LLM provider for RepoLaunch agents
- **Tavily API**: Web search for setup troubleshooting
- **GPT-o3**: Used for Verified dataset filtering (reasoning model)

### Containerization
- **Docker**: All environments run in containers
- **Base Images**: Language-specific base images (Python, Node, Java, etc.)
- **Image Registry**: DockerHub for hosting instance images

### Workflow Management
- **LangGraph**: Workflow orchestration for RepoLaunch agents
- **ReAct Pattern**: Reasoning and acting for agent decision-making
- **State Management**: Centralized state for multi-step agent workflows

### Data Processing
- **GitHub API**: Repository and PR data collection
- **Hugging Face Datasets**: Dataset hosting and distribution
- **JSONL Format**: Line-delimited JSON for streaming processing

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

## Future Directions

2. **Windows Support**: Adding Windows platform support for RepoLaunch
3. **Improved Test Parsing**: LLM-based test case extraction for better language coverage
4. **Enhanced Filtering**: More sophisticated quality filters for Verified dataset
5. **Real-Time Updates**: Moving toward more frequent updates beyond monthly cadence



## RepoLaunch Configuration

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

## Customizing Agents

Agent behavior is controlled by:
- **System prompts** in `launch/agent/setup.py` and `verify.py`
- **Action schemas** (Pydantic models)
- **Workflow parameters** (`max_trials`, `max_steps` in `launch/workflow.py`)

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

## References

- [tutorial](./curation/tutorial.md)
- **SWE-bench-Live Paper**: [arXiv:2505.23419](https://arxiv.org/html/2505.23419v2)
- **SWE-bench Paper**: [ICLR 2024](https://openreview.net/forum?id=VTF8yNQM66)
- **SWE-smith**: [swesmith.com](https://swesmith.com/)
- **Website**: [swe-bench-live.github.io](https://swe-bench-live.github.io/)
- **Dataset**: [Hugging Face](https://huggingface.co/datasets/SWE-bench-Live/SWE-bench-Live)
