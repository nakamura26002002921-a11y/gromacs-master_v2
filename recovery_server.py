# recovery_server.py
# ============================================================
# Usage:
#   python3 recovery_server.py --port 8000 --workdir ./results
#   (実機側) python3 dynamic_orchestrater.py -p plan.json --recovery-url http://<サーバIP>:8000
# ============================================================

import argparse
import json
import re
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse


def extract_file(body):
    if body.lstrip().startswith(b"{"):
        return body
    return body.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]


def propose(entry):
    cmd = entry["実行コマンド"]
    text = (entry.get("エラー") or "") + "\n" + (entry.get("出力") or "")
    proposals = []
    m = re.search(r"command not found[:\s]+([\w\-.]+)", text)
    if m:
        name = m.group(1)
        proposals.append({"実行コマンド": f"sudo apt-get install -y {name}", "目的": f"不足コマンド {name} をインストールする"})
    if "Permission denied" in text and not cmd.startswith("sudo "):
        proposals.append({"実行コマンド": "sudo " + cmd, "目的": "権限不足のため sudo で再実行する"})
    if "No such file or directory" in text:
        target = cmd.split()[-1]
        proposals.append({"実行コマンド": f"mkdir -p {Path(target).parent}", "目的": "不足しているディレクトリを作成する"})
    if not proposals:
        proposals.append({"実行コマンド": f"echo 'no proposal: {cmd}'", "目的": "該当ルールなしのため診断メッセージを返す"})
    proposals.append({"実行コマンド": cmd, "目的": "元コマンドをそのまま再試行する"})
    return proposals


class Handler(BaseHTTPRequestHandler):
    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _pending(self):
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        m = re.fullmatch(r"/result/([\w\-]+)\.json", urlparse(self.path).path)
        if not m:
            self._json({"error": "not found"}, 404)
            return
        path = self.WORK_DIR / (m.group(1) + ".json")
        if not path.exists():
            self._pending()
            return
        self._json(json.loads(path.read_text(encoding="utf-8")))

    def do_POST(self):
        if urlparse(self.path).path != "/upload":
            self._json({"error": "not found"}, 404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        entry = json.loads(extract_file(body))
        rid = entry.get("id") or uuid.uuid4().hex
        result = {"id": rid, "回復手順": propose(entry)}
        (self.WORK_DIR / f"{rid}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self._json({"id": rid})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--workdir", default="./results")
    args = p.parse_args()
    Handler.WORK_DIR = Path(args.workdir)
    Handler.WORK_DIR.mkdir(parents=True, exist_ok=True)
    HTTPServer(("", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
