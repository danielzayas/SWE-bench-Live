# SWE-bench-Live Architecture

## Overview

SWE-bench-Live is a continuously updated benchmark for evaluating AI systems' ability to resolve real-world software engineering tasks. It builds upon the foundation of SWE-bench but introduces an **automated curation pipeline** that streamlines the entire process from instance creation to environment setup, removing manual bottlenecks and enabling scalability and continuous updates.

## Relationship to SWE-bench and SWE-smith

### SWE-bench
- **SWE-bench** is the original benchmark for evaluating language models on real-world GitHub issues
- SWE-bench-Live **forks the evaluation code** from SWE-bench (`swebench/` directory) with minimal modifications
- The evaluation harness, test execution, and grading logic remain consistent with SWE-bench to reduce migration effort
- SWE-bench-Live extends SWE-bench by:
  - Automating the curation pipeline (SWE-bench required manual curation)
  - Enabling continuous monthly updates (SWE-bench was a static dataset)
  - Supporting multi-language repositories (SWE-bench primarily focused on Python/PyPI)

### SWE-smith
- **SWE-smith** is a toolkit for creating execution environments and SWE-bench-style task instances at scale
- It is designed to be compatible with SWE-agent for training data generation and SWE-bench for evaluation
- SWE-bench-Live's **RepoLaunch** tool (in `launch/`) serves a similar purpose to SWE-smith but uses an LLM-based agentic approach
- While SWE-smith focuses on training data generation, SWE-bench-Live focuses on evaluation benchmark curation

### Key Differences

| Aspect | SWE-bench | SWE-smith | SWE-bench-Live |
|--------|-----------|-----------|----------------|
| **Purpose** | Evaluation benchmark | Training data generation | Live evaluation benchmark |
| **Update Frequency** | Static | On-demand | Monthly automated updates |
| **Curation** | Manual | Automated | Fully automated pipeline |
| **Environment Setup** | Manual Docker images | Automated toolkit | LLM-based RepoLaunch agent |
| **Focus** | Python/PyPI | Multi-language | Multi-language (expanding) |

## Automated Curation Pipeline

The SWE-bench-Live curation pipeline consists of five main stages:

```
Repository Crawling → Issue-PR Pair Extraction → Environment Setup (RepoLaunch) → Validation → Dataset Production
```

### Stage 1: Repository Crawling

**Location**: `curation/crawl_repo.py`, `curation/filter_repo.py`

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

**Location**: `curation/swe_task_crawling/`

**Process**:
1. **Pull Request Collection**: For each repository, fetches all pull requests created after a cutoff date
   - Uses GitHub API to retrieve PR metadata
   - Stores in `<repo>-prs.jsonl` files

2. **Issue-PR Matching**: Converts PRs to SWE-bench-like task instances
   - Identifies associated issues (using improved matching from SWE-fixer team)
   - Extracts gold patches from PR diffs
   - Filters for PRs that modify test files (indicating testable tasks)
   - Creates task instances with:
     - Repository information
     - Base commit
     - Issue description
     - Gold patch
     - Test modifications

**Key Scripts**:
- `fetch_pulls.py`: Retrieves PR data from GitHub
- `get_pull_issue_dict.py`: Maps PRs to issues
- `build_dataset.py`: Converts PRs to task instances
- `get_tasks_pipeline.py`: Orchestrates the pipeline

**Output**: `raw_tasks.jsonl` - Candidate task instances ready for environment setup

### Stage 3: Environment Setup with RepoLaunch

**Location**: `launch/`

**RepoLaunch** is an LLM-based agentic tool that automates the creation of testable containerized environments for any GitHub repository. This addresses the major bottleneck in SWE-bench where environment setup was manual.

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
   - Analyzes repository to determine appropriate Docker base image
   - Considers language, dependencies, and project structure
   - Supports multiple languages: Python, Java, Go, JavaScript/TypeScript, Rust, C/C++, C#, PHP, Ruby

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
1. **Gold Patch Application**: Applies the gold patch to each instance
2. **Test Execution**: Runs tests before and after patch application
3. **Test Classification**: Identifies:
   - **FAIL_TO_PASS**: Tests that fail before patch and pass after (validates fix)
   - **PASS_TO_PASS**: Tests that pass both before and after (regression prevention)

**Test Parsing**:
- Language-specific log parsers extract test results
- Supports multiple test frameworks (pytest, unittest, JUnit, etc.)
- Parses detailed test output to map test names to pass/fail status

**Output**: Validation logs with test results for each instance

### Stage 5: Dataset Production

**Location**: `swebench/collect/produce/`

**Process**:

1. **Full Dataset Creation** (`make_full.py`):
   - Collects all validated instances with both FAIL_TO_PASS and PASS_TO_PASS tests
   - Adds difficulty metrics (files, hunks, lines changed in patch)
   - Outputs: `full-{date}.jsonl`

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

## Directory Structure

```
SWE-bench-Live/
├── swebench/              # Evaluation code (forked from SWE-bench)
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

## Evaluation Compatibility

SWE-bench-Live maintains compatibility with SWE-bench evaluation:

- **Same Instance Format**: Uses identical JSON structure
- **Same Test Execution**: Compatible test harness
- **Same Grading**: Identical pass/fail criteria
- **Docker Images**: Follows SWE-bench naming convention (`sweb.eval.*`)

This allows existing SWE-bench evaluation code and agents to work with SWE-bench-Live with minimal modifications.

## Future Directions

1. **Multi-Language Support**: Expanding beyond Python to support more languages
2. **Windows Support**: Adding Windows platform support for RepoLaunch
3. **Improved Test Parsing**: LLM-based test case extraction for better language coverage
4. **Enhanced Filtering**: More sophisticated quality filters for Verified dataset
5. **Real-Time Updates**: Moving toward more frequent updates beyond monthly cadence

## References

- **SWE-bench-Live Paper**: [arXiv:2505.23419](https://arxiv.org/html/2505.23419v2)
- **SWE-bench Paper**: [ICLR 2024](https://openreview.net/forum?id=VTF8yNQM66)
- **SWE-smith**: [swesmith.com](https://swesmith.com/)
- **Website**: [swe-bench-live.github.io](https://swe-bench-live.github.io/)
- **Dataset**: [Hugging Face](https://huggingface.co/datasets/SWE-bench-Live/SWE-bench-Live)
