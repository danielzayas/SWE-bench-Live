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

**Process**:
1. For each repository, fetch all PRs created after a cutoff date
2. Identify issue-first pairs (PRs that close specific issues)
3. Extract from each PR:
   - **Problem statement** from linked issue
   - **Base commit** (SHA before changes)
   - **Patch** (gold solution)
   - **Test patch** (test modifications)
   - **Hints** (additional context from issue comments)
4. Validate instances:
   - Must have associated issue
   - Must be merged
   - Must contain valid patch and problem statement
5. Output: `{repo}-task-instances.jsonl`

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
- Determines appropriate Docker base image
- Considers:
  - Repository language (Python, JavaScript, Rust, Go, C, etc.)
  - Operating system requirements (Linux, Windows)
  - Time-aware version selection (based on `created_at` date)
- Selects from Ubuntu, Debian, Python official images, or language-specific images

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

**Purpose**: Verify that instances can be successfully solved with gold patches

**Components**:
- `swebench/harness/run_validation.py` - Validates instances
- `swebench/harness/grading.py` - Extracts pass/fail test cases

**Process**:
1. For each successfully launched instance:
2. Apply the gold patch to the base commit
3. Run the test commands from RepoLaunch
4. Parse test output to identify:
   - **FAIL_TO_PASS**: Tests that failed before patch, pass after
   - **PASS_TO_PASS**: Tests that passed both before and after
5. Only instances with both test categories are kept
6. Output: Validation logs in `logs/run_validation/{run_id}/`

**Test Output Parsing**:
- Language-specific parsers in `swebench/harness/log_parsers/`
- Python: pytest output parsing
- JavaScript: Jest/Mocha output parsing
- Rust: cargo test output parsing
- Go: go test output parsing
- Generic: regex-based parsing for standard test frameworks

### 5. Production Dataset Creation

**Purpose**: Generate final dataset splits with quality filtering

**Components**:
- `swebench/collect/produce/make_full.py` - Creates full dataset
- `swebench/collect/produce/make_lite.py` - Creates lite split (monthly sample)
- `swebench/collect/produce/make_verified.py` - LLM-based quality filtering

**Process**:

**Full Dataset**:
1. Collect all validated instances
2. Merge with previous month's data
3. Output: `datasets/full-{date}.jsonl`

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
