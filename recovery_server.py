# recovery_server.py
# ============================================================
# Usage:
#   export RECOVERY_API_KEY="$(openssl rand -hex 32)"
#   python3 recovery_server.py
# 別ターミナル:
#   cloudflared tunnel --url http://127.0.0.1:5000
# さらに別ターミナル:
#   curl -X POST https://ant-status-matched-settled.trycloudflare.com/ \
#      -H "Content-Type: application/json" \
#      -H "X-API-Key: XXXXYYYYZZZZ123456789" \
#      -d '[{"ノード": "web-server-01"}]'
# ============================================================

import os
from flask import Flask, request, jsonify

app = Flask(__name__)

API_KEY = os.environ["RECOVERY_API_KEY"]


def get_cmd(history):
    last = history[-1]
    return {"実行コマンド": "echo recovery", "目的": f"{last['ノード']}の復旧処理"}


@app.route("/", methods=["POST"])
def recovery():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"エラー": "Unauthorized"}), 401
    history = request.get_json()
    return jsonify(get_cmd(history))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
