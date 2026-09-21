# recovery_server.py
# ============================================================
# Usage:
#   1. 復旧APIで使用するAPIキーを環境変数に設定
#      export RECOVERY_API_KEY="$(openssl rand -hex 32)"
#
#   2. 承認ページのURLを設定
#      export APPROVAL_URL="https://YOUR-USER.github.io/recovery_approval-v1/"
#
#   3. (任意) 承認の有効期限を秒で設定 (デフォルト 3600)
#      export APPROVAL_TTL=3600
#
#   3'. (任意) 復旧サーバーの公開URLを設定
#      未設定の場合は、オーケストレーターがアクセスしてきたURL(Host / X-Forwarded-*)から
#      自動で決定し、承認URLの api= に付与する。
#      export PUBLIC_URL="https://xxxx.trycloudflare.com"
#
#   4. 復旧サーバーを起動
#      python3 recovery_server.py
#
#   5. Cloudflare Tunnel等でHTTPS公開
#      cloudflared tunnel --url http://127.0.0.1:5000
# ============================================================

import os
import secrets
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

API_KEY = os.environ["RECOVERY_API_KEY"]
APPROVAL_URL = os.environ["APPROVAL_URL"]
APPROVAL_TTL = int(os.environ.get("APPROVAL_TTL", "3600"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")

pending_requests = {}


def check_api_key():
    return request.headers.get("X-API-Key") == API_KEY


def is_expired(item):
    return time.time() - item["created_at"] > APPROVAL_TTL


def get_public_url():
    """承認ページが接続すべき、この復旧サーバーの公開URLを返す。"""
    if PUBLIC_URL:
        return PUBLIC_URL
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme).split(",")[0].strip()
    host = request.headers.get("X-Forwarded-Host", request.host).split(",")[0].strip()
    return f"{scheme}://{host}"


def build_approval_url(request_id, approval_token):
    """APPROVAL_URL に既存のクエリがあっても壊れないように request_id / token / api を付与する。"""
    parts = urlsplit(APPROVAL_URL)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in ("request_id", "token", "api")]
    query += [("request_id", request_id), ("token", approval_token), ("api", get_public_url())]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def get_cmd(history):
    last = history[-1]
    command = {"実行コマンド": "echo recovery", "目的": f"{last['ノード']}の復旧処理"}
    request_id = secrets.token_urlsafe(32)
    approval_token = secrets.token_urlsafe(32)
    pending_requests[request_id] = {"history": history, "command": command, "approval_token": approval_token, "status": "pending", "created_at": time.time()}
    return {"status": "pending", "request_id": request_id, "approval_url": build_approval_url(request_id, approval_token)}


def get_valid_item(request_id, token):
    item = pending_requests.get(request_id)
    if item is None:
        return None, (jsonify({"status": "not_found"}), 404)
    if token != item["approval_token"]:
        return None, (jsonify({"status": "unauthorized"}), 401)
    if item["status"] == "pending" and is_expired(item):
        item["status"] = "expired"
    return item, None


def decide(request_id, new_status):
    item, error = get_valid_item(request_id, (request.get_json(silent=True) or {}).get("token"))
    if error:
        return error
    if item["status"] != "pending":
        return jsonify({"status": item["status"]}), 409
    item["status"] = new_status
    return jsonify({"status": new_status})


@app.route("/", methods=["POST"])
def recovery():
    if not check_api_key():
        return jsonify({"エラー": "Unauthorized"}), 401
    history = request.get_json()
    return jsonify(get_cmd(history))


@app.route("/result/<request_id>", methods=["GET"])
def result(request_id):
    if not check_api_key():
        return jsonify({"エラー": "Unauthorized"}), 401
    item = pending_requests.get(request_id)
    if item is None:
        return jsonify({"status": "not_found"}), 404
    if item["status"] == "pending" and is_expired(item):
        item["status"] = "expired"
    if item["status"] == "approved":
        return jsonify({"status": "approved", "command": item["command"]})
    return jsonify({"status": item["status"]})


@app.route("/api/request/<request_id>", methods=["GET"])
def get_request(request_id):
    item, error = get_valid_item(request_id, request.args.get("token"))
    if error:
        return error
    return jsonify({"status": item["status"], "history": item["history"], "command": item["command"]})


@app.route("/api/request/<request_id>/approve", methods=["POST"])
def approve(request_id):
    return decide(request_id, "approved")


@app.route("/api/request/<request_id>/reject", methods=["POST"])
def reject(request_id):
    return decide(request_id, "rejected")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
