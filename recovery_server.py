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
#   5. (任意) 承認URLに載せる、このサーバーの公開URLを設定
#      export PUBLIC_URL="https://xxxx.trycloudflare.com"
#
#   6. LAN公開で起動（デフォルト5000番）
#      python3 recovery_server.py --offline
#
#   7. LAN公開でポートを指定
#      python3 recovery_server.py --offline --offline-port 5000
#
#   8. 通常起動
#      python3 recovery_server.py
#
#   9. gunicorn で起動 (--offline / --offline-port は使えない)
#      gunicorn -b 127.0.0.1:5000 recovery_server:app
# ============================================================

import argparse
import hmac
import os
import secrets
import socket
import sys
import time
from urllib.parse import quote, urlsplit
from flask import Flask, request, jsonify
from flask_cors import CORS


def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"環境変数 {name} が設定されていません。")
    return value


API_KEY = require_env("RECOVERY_API_KEY")
APPROVAL_URL = require_env("APPROVAL_URL")
APPROVAL_TTL = int(os.environ.get("APPROVAL_TTL", "3600"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")


def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


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
    return hmac.compare_digest(key.encode(), API_KEY.encode())


def check_token(item):
    token = request.headers.get("X-Approval-Token", "")
    return hmac.compare_digest(token.encode(), item["token"].encode())


def is_expired(item):
    return time.time() - item["created_at"] > APPROVAL_TTL


def build_approval_url(request_id, token):
    # トークンは # 以降(フラグメント)に入れる。フラグメントはサーバーにも Referer にも送られない
    api = PUBLIC_URL or f"{request.headers.get('X-Forwarded-Proto', request.scheme)}://{request.host}"
    return f"{APPROVAL_URL}#id={quote(request_id, safe='')}&token={token}&api={quote(api, safe='')}"


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
    token = secrets.token_urlsafe(32)
    pending_requests[request_id] = {
        "command": command,
        "purpose": purpose,
        "status": "承認待ち",
        "token": token,
        "created_at": time.time()
    }
    print(f"[Approval] New request: {request_id}")
    return jsonify({"status": "承認待ち", "id": request_id, "approval_url": build_approval_url(request_id, token)})


@app.route("/api/requests/<request_id>", methods=["GET"])
def get_approval(request_id):
    item = pending_requests.get(request_id)
    if item is None:
        return jsonify({"status": "not_found"}), 404
    if not (check_api_key() or check_token(item)):
        return jsonify({"status": "unauthorized"}), 401
    if item["status"] == "承認待ち" and is_expired(item):
        item["status"] = "期限切れ"
    return jsonify({"status": item["status"], "command": item["command"], "purpose": item["purpose"]})


def update_status(request_id, status):
    item = pending_requests.get(request_id)
    if item is None:
        return jsonify({"status": "not_found"}), 404
    if not check_token(item):
        return jsonify({"status": "unauthorized"}), 401
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

@app.route("/", methods=["GET"])
def health():
    return jsonify({"name": "recovery_server", "status": "ok"})

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--offline-port", type=int, default=5000)
    args = parser.parse_args()
    host = "0.0.0.0" if args.offline else "127.0.0.1"
    address = get_local_ip() if args.offline else "127.0.0.1"
    print(f"Approval Server: http://{address}:{args.offline_port}")
    print(f"Binding Address: {host}:{args.offline_port}")
    print(f"Approval TTL: {APPROVAL_TTL} seconds")
    app.run(host=host, port=args.offline_port)
