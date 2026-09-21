# dynamic_orchestrater.py
# ============================================================
# Usage:
#   python3 dynamic_orchestrater.py -p plan.json --api-key YOUR_API_KEY --recovery-url https://example.com
#   python3 dynamic_orchestrater.py -p plan.json -s nvt -e npt_pr --api-key YOUR_API_KEY --recovery-url https://example.com
#   python3 dynamic_orchestrater.py -p plan.json -ep /path/to/workdir --api-key YOUR_API_KEY --recovery-url https://example.com
#   python3 dynamic_orchestrater.py -p plan.json --history histories/test.json -l logs/test.json --api-key YOUR_API_KEY --recovery-url https://example.com
#   python3 dynamic_orchestrater.py -p plan.json --max-retries 3 --timeout 1800 --api-key YOUR_API_KEY --recovery-url https://example.com
# ============================================================

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime

POLL_INTERVAL = 5
HTTP_TIMEOUT = 30
# Cloudflare が Python-urllib の既定 User-Agent を弾くことがあるため明示する
USER_AGENT = "gromacs-orchestrator/2.0"


def api_request(method, url, api_key, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"X-API-Key": api_key, "User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as res:
            status, raw = res.status, res.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        print(f"復旧サーバーに接続できません: {e}")
        return None, None
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        print(f"復旧サーバーの応答がJSONではありません (HTTP {status})")
        return None, None
    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else None
    if not isinstance(parsed, dict):
        return None, None
    return status, parsed


def wait_for_approval(history, url, api_key, timeout):
    url = url.rstrip("/")
    deadline = time.time() + timeout
    request_id = None
    while request_id is None:
        if time.time() > deadline:
            return {"status": "timeout"}
        code, data = api_request("POST", url + "/", api_key, history)
        if code in (401, 403):
            print(f"復旧サーバーに認証されませんでした (HTTP {code})。--api-key を確認してください。")
            return {"status": "error"}
        if data is not None and code == 200 and data.get("status") == "pending" and data.get("request_id"):
            request_id = data["request_id"]
            print("復旧コマンドの承認待ちです。")
            print("承認ページ: " + data["approval_url"])
        else:
            time.sleep(POLL_INTERVAL)
    while time.time() <= deadline:
        code, result = api_request("GET", url + "/result/" + request_id, api_key)
        if code in (401, 403):
            print(f"復旧サーバーに認証されませんでした (HTTP {code})。--api-key を確認してください。")
            return {"status": "error"}
        if result is not None and result.get("status") not in (None, "pending"):
            return result
        time.sleep(POLL_INTERVAL)
    return {"status": "timeout"}


def validate_plan(plan, start, end):
    if not isinstance(plan, dict) or not plan:
        raise SystemExit("plan が空、またはオブジェクトではありません")
    for name, n in plan.items():
        if not isinstance(n, dict):
            raise SystemExit(f"ノード '{name}' がオブジェクトではありません")
        for key in ("実行コマンド", "目的"):
            if not isinstance(n.get(key), str):
                raise SystemExit(f"ノード '{name}' に文字列の「{key}」がありません")
        nxt = n.get("次のノード")
        if nxt is not None and nxt not in plan:
            raise SystemExit(f"ノード '{name}' の「次のノード」'{nxt}' は plan に存在しません")
    for label, value in (("--start", start), ("--end", end)):
        if value is not None and value not in plan:
            raise SystemExit(f"{label} のノード '{value}' は plan に存在しません。使えるノード: {', '.join(plan)}")


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
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--timeout", type=int, default=3600)
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
    validate_plan(plan, a.start, a.end)
    nodes = list(plan.keys())
    node = a.start or nodes[0]
    end = a.end or nodes[-1]
    history = []
    retries = 0
    succeeded = False
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
                if retries >= a.max_retries:
                    print(f"リトライ上限({a.max_retries}回)に達したため停止します。")
                    break
                retries += 1
                try:
                    recovery_result = wait_for_approval(history, a.recovery_url, a.api_key, a.timeout)
                except KeyboardInterrupt:
                    print("承認待ちを中断しました。")
                    raise
                if recovery_result["status"] != "approved":
                    print("復旧コマンドが承認されなかったため停止します: " + recovery_result["status"])
                    break
                cmd = recovery_result.get("command")
                if not isinstance(cmd, dict) or not isinstance(cmd.get("実行コマンド"), str) or not isinstance(cmd.get("目的"), str):
                    print("復旧サーバーから不正な形式の復旧コマンドが返されたため停止します。")
                    break
                try:
                    cmd_r = subprocess.run(cmd["実行コマンド"], shell=True, cwd=execution_path, capture_output=True, text=True)
                    recovery_execution_result = {"ノード": node, "実行コマンド": cmd["実行コマンド"], "目的": cmd["目的"], "出力": cmd_r.stdout, "エラー": cmd_r.stderr, "終了コード": cmd_r.returncode}
                except KeyboardInterrupt:
                    history.append({"ノード": node, "実行コマンド": cmd["実行コマンド"], "目的": cmd["目的"], "出力": "", "エラー": "KeyboardInterrupt (^C)", "終了コード": -2})
                    raise
                history.append(recovery_execution_result)
                if recovery_execution_result["終了コード"] != 0:
                    break
                continue
            if r.returncode != 0:
                break
            if node == end:
                succeeded = True
                break
            retries = 0
            node = n["次のノード"]
    finally:
        json.dump(history, open(history_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        json.dump(history, open(log_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return succeeded


if __name__ == "__main__":
    try:
        sys.exit(0 if main() else 1)
    except KeyboardInterrupt:
        print("中断されました。history は保存済みです。")
        sys.exit(130)
