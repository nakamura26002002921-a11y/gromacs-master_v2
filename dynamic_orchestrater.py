# dynamic_orchestrater.py
# ============================================================
# Usage:
#   python3 dynamic_orchestrater.py -p plan.json
#   python3 dynamic_orchestrater.py -p plan.json -s nvt -e npt_pr
#   python3 dynamic_orchestrater.py -p plan.json -ep /path/to/workdir
#   python3 dynamic_orchestrater.py -p plan.json --history histories/test.json -l logs/test.json
#   python3 dynamic_orchestrater.py -p plan.json --recovery-url https://example.com/recovery --api-key YOUR_API_KEY
# ============================================================

import argparse
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime


def get_cmd(history, url, api_key):
    json.dump(history, open("recovery_request.json", "w", encoding="utf-8"), ensure_ascii=False)
    subprocess.run(f"wget -q -O recovery_result.json --post-file=recovery_request.json --header='Content-Type: application/json' --header='X-API-Key: {api_key}' '{url}'", shell=True)
    data = json.load(open("recovery_result.json", encoding="utf-8"))
    return data[0] if isinstance(data, list) else data


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-p", "--plan", required=True)
    p.add_argument("--history")
    p.add_argument("-l", "--logpath")
    p.add_argument("-s", "--start")
    p.add_argument("-e", "--end")
    p.add_argument("-ep", "--executionpath")
    p.add_argument("--recovery-url", default="")
    p.add_argument("--api-key", default="")
    a = p.parse_args()

    plan_path = Path(a.plan)
    plan = json.load(open(plan_path, encoding="utf-8"))
    name = plan_path.stem
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    history_path = Path(a.history or f"histories/{name}_{now}.json")
    log_path = Path(a.logpath or f"logs/{name}_{now}.json")
    execution_path = Path(a.executionpath or ".")
    history_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    nodes = list(plan.keys())
    node = a.start or nodes[0]
    end = a.end or nodes[-1]
    history = []

    try:
        while True:
            n = plan[node]
            r = subprocess.run(n["実行コマンド"], shell=True, cwd=execution_path, capture_output=True, text=True)
            result = {"ノード": node, "実行コマンド": n["実行コマンド"], "目的": n["目的"], "出力": r.stdout, "エラー": r.stderr, "終了コード": r.returncode}
            history.append(result)

            if r.returncode != 0:
                while True:
                    cmd = get_cmd(history, a.recovery_url, a.api_key)
                    if cmd:
                        cmd_r = subprocess.run(cmd["実行コマンド"], shell=True, cwd=execution_path, capture_output=True, text=True)
                        result = {"ノード": node, "実行コマンド": cmd["実行コマンド"], "目的": cmd["目的"], "出力": cmd_r.stdout, "エラー": cmd_r.stderr, "終了コード": cmd_r.returncode}
                        history.append(result)
                        node = cmd["次のノード"]
                        break
                    time.sleep(30)
                continue

            if node == end:
                break

            node = n["次のノード"]
    finally:
        json.dump(history, open(history_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        json.dump(history, open(log_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
