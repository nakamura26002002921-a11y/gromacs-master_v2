# recovery_server.py
# ============================================================
# Usage:
#   1. 復旧APIで使用するAPIキーを環境変数に設定
#      export RECOVERY_API_KEY="$(openssl rand -hex 32)"
#
#   2. 復旧サーバーを起動
#      python3 recovery_server.py
#
#   3. 別ターミナルでCloudflare Tunnelを起動
#      cloudflared tunnel --url http://127.0.0.1:5000
#
#   4. 表示されたURLに対してPOSTすると動作確認できる
#      curl -X POST https://ant-status-matched-settled.trycloudflare.com/ \
#        -H "Content-Type: application/json" \
#        -H "X-API-Key: XXXXYYYYZZZZ123456789" \
#        -d '[{"ノード": "web-server-01"}]'
#
# 通信の流れ:
#   dynamic_orchestrater.py
#       ↓
#   historyをJSONとしてPOST
#       ↓
#   Cloudflare Tunnel
#       ↓
#   recovery_server.py
#       ↓
#   historyを受け取って復旧コマンドを作成
#       ↓
#   復旧コマンドをJSONで返す
#       ↓
#   dynamic_orchestrater.py
#
# 送信データの例:
#   [
#     {
#       "ノード": "web-server-01",
#       "実行コマンド": "...",
#       "目的": "...",
#       "出力": "...",
#       "エラー": "...",
#       "終了コード": 1
#     }
#   ]
#
# 返却データの例:
#   {
#     "実行コマンド": "echo recovery",
#     "目的": "web-server-01の復旧処理"
#   }
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
