# run_lats.py
"""
LATSエージェントの検証スクリプト。
まず use_llm: false で決定論的MCTSとして動かし、
木の形が正しいことを確認してから use_llm: true にする。
"""

import yaml
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from lats_agent.lats_agent import LATSRecoveryAgent


def main():
    parser = argparse.ArgumentParser(description="LATS Recovery Agent")
    parser.add_argument("pdb", help="Input PDB file path")
    parser.add_argument("--config", default="config.yaml", help="Config file")
    parser.add_argument("--no-llm", action="store_true",
                        help="LLMを使わず決定論的MCTSとして動かす(デバッグ用)")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    if args.no_llm:
        config.setdefault("lats", {})["use_llm"] = False

    agent = LATSRecoveryAgent(config)
    result = agent.run(args.pdb)

    print("\n" + "="*60)
    if result["success"]:
        print(f"SUCCESS: {result['repair_path']}")
        print(f"  Depth: {result['depth']}")
        print(f"  Structure altered: {result['structure_altered']}")
    else:
        print(f"FAILED after exploring {result['tree_stats']['total_nodes']} nodes")
    print("="*60)


if __name__ == "__main__":
    main()
