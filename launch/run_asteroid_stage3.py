"""
Helper for launching the Astroid Stage 3 RepoLaunch run.

This thin wrapper simply loads the Astroid-specific configuration and then
delegates to the standard launch runner.
"""

from __future__ import annotations

from pathlib import Path

from launch.run import run_launch


def main() -> None:
    config_path = Path(__file__).resolve().parent / "configs" / "asteroid_stage3.json"
    run_launch(str(config_path))


if __name__ == "__main__":
    main()

