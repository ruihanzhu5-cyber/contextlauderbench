from __future__ import annotations

import argparse

from .benchmark import run_benchmark, run_golden


def main() -> None:
    parser = argparse.ArgumentParser(description="ContextLaunderBench scripted runner")
    parser.add_argument("command", choices=("golden", "benchmark"))
    parser.add_argument("--adapter", choices=("free", "langgraph", "both"),
                        default="both")
    parser.add_argument("--output", default=None)
    parser.add_argument("--seed", type=int, default=20260925)
    args = parser.parse_args()
    adapters = ("free", "langgraph") if args.adapter == "both" else (args.adapter,)
    output = args.output or ("reports/golden" if args.command == "golden"
                             else "reports/latest")
    results = (run_golden(output, adapters) if args.command == "golden"
               else run_benchmark(output, args.seed, adapters))
    print(f"{args.command}: {len(results)} case runs; outputs in {output}")


if __name__ == "__main__":
    main()
