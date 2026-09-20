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
    request_data = json.dumps(history, ensure_ascii=False)
    result = subprocess.run(["curl", "-sS", "-X", "POST", url, "-H", "Content-Type: application/json", "-H", "X-API-Key: " + api_key, "--data-binary", request_data], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout:
        return None
    data = json.loads(result.stdout)
    return data[0] if isinstance(data, list) and data else data


def get_approved_cmd(request_id, url, api_key):
    result = subprocess.run(["curl", "-sS", "-X", "GET", url + "/result/" + request_id, "-H", "X-API-Key: " + api_key], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout:
        return None
    return json.loads(result.stdout)


def wait_for_approval(history, url, api_key):
    while True:
        data = get_cmd(history, url, api_key)
        if data is None:
            time.sleep(5)
            continue
        if data.get("status") == "approved":
            return data
        if data.get("status") == "rejected":
            return data
        if data.get("status") == "pending":
            request_id = data["request_id"]
            print("復旧コマンドの承認待ちです。")
            print("承認ページ: " + data["approval_url"])
            while True:
                result = get_approved_cmd(request_id, url, api_key)
                if result is not None and result.get("status") in ("approved", "rejected"):
                    return result
                time.sleep(5)
        time.sleep(5)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-p", "--plan", required=True)
    p.add_argument("--history")
    p.add_argument("-l", "--logpath")
    p.add_argument("-s", "--start")
    p.add_argument("-e", "--end")
    p.add_argument("-ep", "--executionpath")
    p.add_argument("--recovery-url", default="")
    p.add_argument("--api-key", required=True)
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
            try:
                r = subprocess.run(n["実行コマンド"], shell=True, cwd=execution_path, capture_output=True, text=True)
                result = {"ノード": node, "実行コマンド": n["実行コマンド"], "目的": n["目的"], "出力": r.stdout, "エラー": r.stderr, "終了コード": r.returncode}
            except KeyboardInterrupt:
                result = {"ノード": node, "実行コマンド": n["実行コマンド"], "目的": n["目的"], "出力": "", "エラー": "KeyboardInterrupt (^C)", "終了コード": -2}
                history.append(result)
                raise
            history.append(result)
            if r.returncode != 0 and a.recovery_url:
                recovery_result = wait_for_approval(history, a.recovery_url, a.api_key)
                if recovery_result["status"] != "approved":
                    break
                cmd = recovery_result["command"]
                cmd_r = subprocess.run(cmd["実行コマンド"], shell=True, cwd=execution_path, capture_output=True, text=True)
                recovery_execution_result = {"ノード": node, "実行コマンド": cmd["実行コマンド"], "目的": cmd["目的"], "出力": cmd_r.stdout, "エラー": cmd_r.stderr, "終了コード": cmd_r.returncode}
                history.append(recovery_execution_result)
                if recovery_execution_result["終了コード"] != 0:
                    break
                continue
            if r.returncode != 0 or node == end:
                break
            node = n["次のノード"]
    finally:
        json.dump(history, open(history_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        json.dump(history, open(log_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
