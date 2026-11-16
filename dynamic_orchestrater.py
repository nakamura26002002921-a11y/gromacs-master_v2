# dynamic_orchestrater.py
# ============================================================
# Usage:
#   export RECOVERY_API_KEY="復旧サーバーと同じ値"
#   python3 dynamic_orchestrater.py -p plan.json --api-key "gsk_..." --server-url "https://xxxx.trycloudflare.com"
#   python3 dynamic_orchestrater.py -p plan.json --api-key "gsk_..." --offline-host 192.168.1.100
#   python3 dynamic_orchestrater.py -p plan.json --api-key "gsk_..." --offline-host 192.168.1.100 --offline-port 5000
#   python3 dynamic_orchestrater.py -p plan.json --api-key "gsk_..." -s nvt -e npt_pr -ep /path/to/workdir --offline-host 192.168.1.100 --offline-port 5000
#   python3 dynamic_orchestrater.py -p plan.json --api-key "gsk_..." --offline-host 172.25.2.122 --approval-api http://127.0.0.1:5000
#   (--approval-api: ブラウザから見える API の URL。ssh -L のトンネル経由なら http://127.0.0.1:5000 を指定する)
#   (--api-key は Groq の API キー。復旧サーバーのキーは環境変数 RECOVERY_API_KEY か --recovery-api-key で渡す)
# ============================================================

import argparse
import json
import os
import requests
import subprocess
import sys
import time
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit
from datetime import datetime
from pathlib import Path
from groq import Groq
from static_orchestrater import validate_plan, save_history

MODEL = "openai/gpt-oss-120b"

SYSTEM_PROMPT = """
Purpose:
Commands failed. Write a command to recover from the error.
The input is a JSON list of failed commands in chronological order.
The first item is the original failure; later items are recovery attempts that also failed. Do not repeat a command that already failed.
- command: The command to execute
- purpose: Why this command is necessary
All fields must strictly follow the specified JSON Schema types.
Output JSON only. Do not output any other text.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string"},
        "purpose": {"type": "string"}
    },
    "required": ["command", "purpose"],
    "additionalProperties": False
}

RESPONSE_FORMAT = {"type": "json_schema", "json_schema": {"name": "recovery_command", "strict": True, "schema": SCHEMA}}


def build_context(history):
    failures = []
    for item in reversed(history):
        if item["returncode"] == 0:
            break
        failures.insert(0, {"実行コマンド": item["実行コマンド"], "目的": item["目的"], "returncode": item["returncode"], "stderr": item["stderr"][-2000:]})
    return failures


def call_llm(history, api_key):
    client = Groq(api_key=api_key)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": json.dumps(build_context(history), ensure_ascii=False)}]
    response = client.chat.completions.create(model=MODEL, messages=messages, temperature=0, max_tokens=2000, response_format=RESPONSE_FORMAT)
    return json.loads(response.choices[0].message.content)


def create_approval_request(server_url, request_id, command, purpose, api_key):
    response = requests.post(f"{server_url}/api/requests", json={"id": request_id, "purpose": purpose, "command": command}, headers={"X-API-Key": api_key}, timeout=10)
    response.raise_for_status()
    return response.json()


def get_approval_request(server_url, request_id, api_key):
    response = requests.get(f"{server_url}/api/requests/{request_id}", headers={"X-API-Key": api_key}, timeout=10)
    response.raise_for_status()
    return response.json()


def wait_for_approval(server_url, request_id, api_key, timeout, interval):
    started = time.time()
    while True:
        data = get_approval_request(server_url, request_id, api_key)
        if data["status"] == "承認済み":
            return data
        if data["status"] != "承認待ち":
            return None
        if time.time() - started >= timeout:
            return None
        print(f"Waiting for approval: {request_id} ({int(time.time() - started)} seconds elapsed)")
        time.sleep(interval)


def run(node, cmd, cwd):
    print(f"[{node}] Executing: {cmd['実行コマンド']}")
    result = subprocess.run(cmd["実行コマンド"], shell=True, cwd=cwd, capture_output=True, text=True)
    return {"node": node, "実行コマンド": cmd["実行コマンド"], "目的": cmd["目的"], "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def rewrite_approval_api(approval_url, approval_api):
    if not approval_api:
        return approval_url
    parts = urlsplit(approval_url)
    params = [(k, approval_api if k == "api" else v) for k, v in parse_qsl(parts.fragment, keep_blank_values=True)]
    if not any(k == "api" for k, _ in params):
        params.append(("api", approval_api))
    return parts._replace(fragment=urlencode(params, safe="")).geturl()


def request_recovery(a, server_url, node, history, request_id):
    proposal = call_llm(history, a.api_key)
    created = create_approval_request(server_url, request_id, proposal["command"], proposal["purpose"], a.recovery_api_key)
    print(f"Recovery command is waiting for approval: {request_id}")
    print(f"Approval URL: {rewrite_approval_api(created['approval_url'], a.approval_api)}")
    approved = wait_for_approval(server_url, request_id, a.recovery_api_key, a.approval_timeout, a.approval_interval)
    if approved is None:
        print("Approval was not received.")
        return None
    if approved["command"] != proposal["command"]:
        print("Approved command differs from the proposed command. Stopping.")
        return None
    print("Approval confirmed. Executing recovery command.")
    return run(node, {"実行コマンド": proposal["command"], "目的": proposal["purpose"]}, a.executionpath)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-p", "--plan", required=True)
    p.add_argument("--api-key", required=True)
    p.add_argument("--recovery-api-key", default=os.environ.get("RECOVERY_API_KEY", ""))
    p.add_argument("--history")
    p.add_argument("-l", "--logpath")
    p.add_argument("-s", "--start")
    p.add_argument("-e", "--end")
    p.add_argument("-ep", "--executionpath", default=".")
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--server-url")
    p.add_argument("--offline-host")
    p.add_argument("--offline-port", type=int, default=5000)
    p.add_argument("--approval-api", default=os.environ.get("APPROVAL_API", "").rstrip("/"), help="承認ページ(ブラウザ)から見える API の URL。ssh -L のトンネル経由なら http://127.0.0.1:5000")
    p.add_argument("--approval-timeout", type=int, default=3600)
    p.add_argument("--approval-interval", type=int, default=5)
    a = p.parse_args()
    if bool(a.server_url) == bool(a.offline_host):
        p.error("--server-url または --offline-host のどちらか一方を指定してください")
    if not (1 <= a.offline_port <= 65535):
        p.error("--offline-port must be between 1 and 65535")
    if not a.recovery_api_key:
        p.error("復旧サーバーの API キーを環境変数 RECOVERY_API_KEY か --recovery-api-key で指定してください")
    server_url = a.server_url.rstrip("/") if a.server_url else f"http://{a.offline_host}:{a.offline_port}"
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    validate_plan(plan, a.start, a.end)
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    history_path = Path(a.history) if a.history else Path(f"histories/{Path(a.plan).stem}_{now}.json")
    log_path = Path(a.logpath) if a.logpath else Path(f"logs/{Path(a.plan).stem}_{now}.json")
    history_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    history = []
    node = a.start or next(iter(plan))
    end = a.end or list(plan)[-1]
    retries = 0
    request_id = uuid.uuid4().hex[:8]
    while True:
        result = run(node, plan[node], a.executionpath)
        history.append(result)
        save_history(history, history_path, log_path)
        if result["returncode"] == 0:
            if node == end:
                return 0
            node = plan[node]["次のノード"]
            retries = 0
            continue
        recovered = False
        while not recovered and retries < a.max_retries:
            retries += 1
            recovery_result = request_recovery(a, server_url, node, history, request_id)
            if recovery_result is None:
                return 1
            history.append(recovery_result)
            save_history(history, history_path, log_path)
            recovered = recovery_result["returncode"] == 0
        if not recovered:
            return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Interrupted.")
        sys.exit(130)
