#!/usr/bin/env python3
"""Print the exact ACLF evidence-gathering and assessment system prompts."""

from __future__ import annotations

import argparse

from instructions import GATHER_SYSTEM, build_assess_system


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=("gather", "assess", "both"),
        default="both",
        help="Prompt phase to print (default: both).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.phase in {"gather", "both"}:
        print("=== GATHER SYSTEM PROMPT ===")
        print(GATHER_SYSTEM.strip())
    if args.phase == "both":
        print()
    if args.phase in {"assess", "both"}:
        print("=== ASSESS SYSTEM PROMPT ===")
        print(build_assess_system().strip())


if __name__ == "__main__":
    main()
