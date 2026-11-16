
# recovery_server.py
# ============================================================
# Usage:
#   1. APIキーを設定
#      export RECOVERY_API_KEY="$(openssl rand -hex 32)"
#
#   2. 承認ページのURLを設定
#      export APPROVAL_URL="https://YOUR-USER.github.io/recovery_approval-v1/"
#
#   3. (任意) 承認の有効期限を設定
#      export APPROVAL_TTL=3600
#
#   4. (任意) CORS許可オリジンを設定
#      export CORS_ORIGINS="https://YOUR-USER.github.io"
#
#   5. LAN公開で起動
#      python3 recovery_server.py --offline
#
#   6. 通常起動
#      python3 recovery_server.py
# ============================================================

import argparse
import hmac
import os
import socket
import sys
import time
from urllib.parse import urlsplit
from flask import Flask, request, jsonify
from flask_cors import CORS

parser = argparse.ArgumentParser()
parser.add_argument("--offline", action="store_true")
args = parser.parse_args()

def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"環境変数 {name} が設定されていません。")
    return value

API_KEY = require_env("RECOVERY_API_KEY")
APPROVAL_URL = require_env("APPROVAL_URL")
APPROVAL_TTL = int(os.environ.get("APPROVAL_TTL", "3600"))

def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect(("8.8.8.8", 80))
    ip = sock.getsockname()[0]
    sock.close()
    return ip

def get_cors_origins():
    configured = [o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    if configured:
        return configured
    parts = urlsplit(APPROVAL_URL)
    return [f"{parts.scheme}://{parts.netloc}"]

app = Flask(__name__)
CORS(app, origins=get_cors_origins())
pending_requests = {}

def check_api_key():
    key = request.headers.get("X-API-Key", "")
    return isinstance(key, str) and hmac.compare_digest(key.encode(), API_KEY.encode())

def is_expired(item):
    return time.time() - item["created_at"] > APPROVAL_TTL

@app.route("/api/requests", methods=["POST"])
def create_approval():
    if not check_api_key():
        return jsonify({"status": "unauthorized"}), 401
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "invalid_request"}), 400
    request_id = body.get("id")
    command = body.get("command")
    purpose = body.get("purpose")
    if not all(isinstance(v, str) and v for v in (request_id, command, purpose)):
        return jsonify({"status": "invalid_request"}), 400
    if request_id in pending_requests:
        return jsonify({"status": "already_exists"}), 409
    pending_requests[request_id] = {
        "command": command,
        "purpose": purpose,
        "status": "承認待ち",
        "created_at": time.time()
    }
    print(f"[Approval] New request: {request_id}")
    return jsonify({"status": "承認待ち", "id": request_id})


@app.route("/api/requests/<request_id>", methods=["GET"])
def get_approval(request_id):
    if not check_api_key():
        return jsonify({"status": "unauthorized"}), 401
    item = pending_requests.get(request_id)
    if item is None:
        return jsonify({"status": "not_found"}), 404
    if item["status"] == "承認待ち" and is_expired(item):
        item["status"] = "期限切れ"
    return jsonify({"status": item["status"], "command": item["command"], "purpose": item["purpose"]})


def update_status(request_id, status):
    item = pending_requests.get(request_id)
    if item is None:
        return jsonify({"status": "not_found"}), 404
    if item["status"] != "承認待ち":
        return jsonify({"status": item["status"]}), 409
    if is_expired(item):
        item["status"] = "期限切れ"
        return jsonify({"status": "期限切れ"}), 409
    item["status"] = status
    print(f"[Approval] {status}: {request_id}")
    return jsonify({"status": status})

@app.route("/api/requests/<request_id>/approve", methods=["POST"])
def approve(request_id):
    return update_status(request_id, "承認済み")

@app.route("/api/requests/<request_id>/reject", methods=["POST"])
def reject(request_id):
    return update_status(request_id, "却下")

if __name__ == "__main__":
    host = "0.0.0.0" if args.offline else "127.0.0.1"
    address = get_local_ip() if args.offline else "127.0.0.1"
    print(f"Approval Server: http://{address}:5000")
    app.run(host=host, port=5000)
