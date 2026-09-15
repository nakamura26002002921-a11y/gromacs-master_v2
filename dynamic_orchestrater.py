# dynamic_orchestrater.py
# ============================================================
# Usage:
#   python3 dynamic_orchestrater.py -p plan.json
#   python3 dynamic_orchestrater.py -p plan.json -s nvt -e npt_pr
#   python3 dynamic_orchestrater.py -p plan.json -ep /path/to/workdir
#   python3 dynamic_orchestrater.py -p plan.json --history histories/test.json -l logs/test.json
#   python3 dynamic_orchestrater.py -p plan.json --recovery-url http://recovery-server:8000
# ============================================================

import argparse
import json
import subprocess
import uuid
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin


def recovery(node, result, plan, history, execution_path, recovery_url, recovery_id):
    print(f"[ERROR] {node}\n{result['エラー']}")
    request_data = {
        "id": recovery_id,
        "ノード": node,
        "実行コマンド": result["実行コマンド"],
        "目的": result["目的"],
        "出力": result["出力"],
        "エラー": result["エラー"],
        "終了コード": result["終了コード"],
        "plan": plan
    }
    request_path = execution_path / f"recovery_{recovery_id}.json"
    result_path = execution_path / f"recovery_result_{recovery_id}.json"
    json.dump(request_data, open(request_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    upload_command = f"curl -sS -X POST -F 'file=@{request_path}' '{recovery_url}/upload'"
    upload_result = subprocess.run(upload_command, shell=True, cwd=execution_path, capture_output=True, text=True)
    if upload_result.returncode != 0:
        print(f"[ERROR] recovery server upload failed\n{upload_result.stderr}")
        return False
    print(f"[INFO] recovery request uploaded: {recovery_id}")
    result_url = urljoin(f"{recovery_url}/", f"result/{recovery_id}.json")
    while True:
        download_command = f"wget -q -O '{result_path}' '{result_url}'"
        download_result = subprocess.run(download_command, shell=True, cwd=execution_path, capture_output=True, text=True)
        if download_result.returncode == 0:
            print(f"[INFO] recovered plan downloaded: {recovery_id}")
            break
        print(f"[INFO] waiting for recovery: {recovery_id}")
        time.sleep(10)
    recovered_plan = json.load(open(result_path, encoding="utf-8"))
    plan.clear()
    plan.update(recovered_plan)
    return True

def main():
    p = argparse.ArgumentParser()
    p.add_argument("-p", "--plan", required=True)
    p.add_argument("--history")
    p.add_argument("-l", "--logpath")
    p.add_argument("-s", "--start")
    p.add_argument("-e", "--end")
    p.add_argument("-ep", "--executionpath")
    p.add_argument("--recovery-url", required=True)
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
    nodes = list(plan)
    node = a.start or nodes[0]
    end = a.end or nodes[-1]
    history = []
    try:
        while True:
            n = plan[node]
            try:
                r = subprocess.run(n["実行コマンド"], shell=True, cwd=execution_path, capture_output=True, text=True)
            except KeyboardInterrupt:
                raise
            result = {"ノード": node, "実行コマンド": n["実行コマンド"], "目的": n["目的"], "出力": r.stdout, "エラー": r.stderr, "終了コード": r.returncode}
            history.append(result)
            if r.returncode != 0:
                recovery_id = str(uuid.uuid4())
                if recovery(node, result, plan, history, execution_path, a.recovery_url, recovery_id):
                    node = node
                    continue
                break
            if node == end:
                break
            node = n["次のノード"]
    finally:
        json.dump(history, open(history_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        json.dump(history, open(log_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
