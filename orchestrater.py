# ============================================================
# Usage:
#   python3 orchestrater.py --graph xxx.json --start "開始" --end "終了"
#   python3 orchestrater.py --graph xxx.json --start "開始" --end "終了" --logpath logs/test.json
# ============================================================

import argparse, json, subprocess
from pathlib import Path
from datetime import datetime

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--graph")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--logpath")
    a = p.parse_args()

    graph = json.load(open(a.graph))
    logpath = Path(a.logpath or f"logs/{datetime.now():%Y%m%d_%H%M%S}.json")
    logpath.parent.mkdir(parents=True, exist_ok=True)
    logs, node = [], a.start

    try:
        while True:
            n = graph[node]
            try:
                r = subprocess.run(n["実行コマンド"], shell=True, capture_output=True, text=True)
                logs.append({"実行コマンド": n["実行コマンド"], "目的": n["目的"], "出力": r.stdout, "エラー": r.stderr})
            except KeyboardInterrupt:
                logs.append({"実行コマンド": n["実行コマンド"], "目的": n["目的"], "出力": "", "エラー": "KeyboardInterrupt (^C)"})
                raise

            if node == a.end: break
            node = n["次のノード"]
    finally:
        json.dump(logs, open(logpath, "w"), ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
