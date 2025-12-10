# Multi-Language Support Analysis: Rust & TypeScript

## Executive Summary

**Do not run the pipeline for new Rust or TypeScript repositories without code modifications.**

While the "RepoLaunch" (setup) phase might succeed in building the environment, the downstream **evaluation harness is currently incapable of processing new repositories** in these languages. The infrastructure for parsing test logs relies on hardcoded, repository-specific lists, making it impossible to automatically onboard a new repository without modifying the core `SWE-bench` source code.

## Detailed Findings & Risks

### 1. Critical Failure Point: Test Log Parsing (High Risk)
The automated curation pipeline creates task instances, but these instances must be evaluated by the `SWE-bench` harness. The harness requires a specific "log parser" to determine if tests passed or failed.

*   **The Issue**: The system uses a strict lookup dictionary `MAP_REPO_TO_PARSER` (found in `swebench/harness/grading.py`) to find the log parser for a given repository.
    *   **Rust**: In `swebench/harness/log_parsers/rust.py`, only ~7 specific repositories (e.g., `burntsushi/ripgrep`) are mapped to the `parse_log_cargo` function. Any new Rust repository will cause a `KeyError` during evaluation.
    *   **TypeScript/JS**: Similarly, `javascript.py` maps specific repositories to specific parsers (Jest, TAP, Karma). There is no logic to automatically detect that a new repository uses "Jest" and assign the correct parser.

*   **The "log_parser" Field Trap**: While the task definition schema allows a `log_parser` field, the code in `swebench/harness/test_spec/test_spec.py` (lines 237-241) only recognizes `"pytest"`. Providing `"cargo"` or `"jest"` in the JSON input will crash the system.

### 2. Poor Reproducibility (Medium Risk)
Unlike the Python handler, which uses `pypi-timemachine` to faithfully restore historical dependencies, the Rust and TypeScript handlers lack time-travel capabilities.

*   **Rust**: The handler simply runs `cargo build` and `cargo test`. If the repository's `Cargo.lock` is missing or ignored, this will pull the *current* versions of dependencies, potentially breaking builds for historical issues (dependency drift).
*   **TypeScript**: The handler runs `npm install`. Without strict lockfile adherence or a registry proxy, this often installs newer compatible versions of packages, leading to "works on my machine" issues where the environment doesn't match the historical state of the PR.

### 3. Limited Test Runner Support
*   **Rust**: The system exclusively parses standard `cargo test` output. If your repository uses a `Makefile`, a custom test runner script, or a test harness that changes the output format, the evaluation will fail to count passes/fails correctly.
*   **TypeScript**: Support is fragmented. If your repository uses a test runner other than Jest, TAP, or Karma (e.g., Mocha, Ava, Jasmine), there is no existing parser to handle the logs.

## Recommendations

If you must proceed, you will need to fork the repository and apply the following fixes:

1.  **Patch `swebench/harness/grading.py`**: Add a fallback mechanism to select a default parser based on the repository's language if the specific repo name is not found in the map.
2.  **Patch `swebench/harness/test_spec/test_spec.py`**: Update the `log_parser_map` to include entries for non-Python parsers (e.g., `"cargo": parse_log_cargo`, `"jest": parse_log_jest`), allowing you to manually specify the parser in your dataset.
3.  **Manual Verification**: For the first batch of instances, manually verify that `npm install` / `cargo build` actually restores a working environment for the specific historical commits you are targeting.

