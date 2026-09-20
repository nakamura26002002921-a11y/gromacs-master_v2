# recovery_server.py
# ============================================================
# Usage:
#   1. 復旧APIで使用するAPIキーを環境変数に設定
#      export RECOVERY_API_KEY="$(openssl rand -hex 32)"
#
#   2. 承認ページのURLを設定
#      export APPROVAL_URL="https://YOUR-USER.github.io/recovery-approval/"
#
#   3. 復旧サーバーを起動
#      python3 recovery_server.py
#
#   4. Cloudflare Tunnel等でHTTPS公開
#      cloudflared tunnel --url http://127.0.0.1:5000
# ============================================================

import os
import secrets
import time
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

API_KEY = os.environ["RECOVERY_API_KEY"]
APPROVAL_URL = os.environ["APPROVAL_URL"]

requests = {}


def check_api_key():
    return request.headers.get("X-API-Key") == API_KEY


def get_cmd(history):
    last = history[-1]
    command = {"実行コマンド": "echo recovery", "目的": f"{last['ノード']}の復旧処理"}
    request_id = secrets.token_urlsafe(32)
    approval_token = secrets.token_urlsafe(32)
    requests[request_id] = {"history": history, "command": command, "approval_token": approval_token, "status": "pending", "created_at": time.time()}
    return {"status": "pending", "request_id": request_id, "approval_url": APPROVAL_URL + "?request_id=" + request_id + "&token=" + approval_token}


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
    item = requests.get(request_id)
    if item is None:
        return jsonify({"status": "not_found"}), 404
    if item["status"] == "approved":
        return jsonify({"status": "approved", "command": item["command"]})
    if item["status"] == "rejected":
        return jsonify({"status": "rejected"})
    return jsonify({"status": "pending"})


@app.route("/api/request/<request_id>", methods=["GET"])
def get_request(request_id):
    item = requests.get(request_id)
    if item is None:
        return jsonify({"status": "not_found"}), 404
    if request.args.get("token") != item["approval_token"]:
        return jsonify({"status": "unauthorized"}), 401
    return jsonify({"status": item["status"], "history": item["history"], "command": item["command"]})


@app.route("/api/request/<request_id>/approve", methods=["POST"])
def approve(request_id):
    item = requests.get(request_id)
    if item is None:
        return jsonify({"status": "not_found"}), 404
    if request.get_json().get("token") != item["approval_token"]:
        return jsonify({"status": "unauthorized"}), 401
    item["status"] = "approved"
    return jsonify({"status": "approved"})


@app.route("/api/request/<request_id>/reject", methods=["POST"])
def reject(request_id):
    item = requests.get(request_id)
    if item is None:
        return jsonify({"status": "not_found"}), 404
    if request.get_json().get("token") != item["approval_token"]:
        return jsonify({"status": "unauthorized"}), 401
    item["status"] = "rejected"
    return jsonify({"status": "rejected"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
