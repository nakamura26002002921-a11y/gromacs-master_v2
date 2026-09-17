# recovery_server.py
# ============================================================
# Usage:
# ============================================================

from flask import Flask, request, jsonify

app = Flask(__name__)

def recover(history):
    last = history[-1]
    return {"実行コマンド": "echo recovery", "目的": "直前のノードの失敗から復旧する"}

@app.route("/", methods=["POST"])
def recovery():
    history = request.get_json()
    return jsonify([recover(history)])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
