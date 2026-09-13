# dynamic_orchestrater.py
# ============================================================
# Usage:
#   python3 dynamic_orchestrater.py -p plan.json -k API_KEY -m example@example.com
#   python3 dynamic_orchestrater.py -p plan.json -k API_KEY -m example@example.com -s nvt -e npt_pr
#   python3 dynamic_orchestrater.py -p plan.json -k API_KEY -m example@example.com -ep /path/to/workdir
#   python3 dynamic_orchestrater.py -p plan.json -k API_KEY -m example@example.com --history histories/test.json -l logs/test.json
# ============================================================

import argparse
import json
import os
import smtplib
import imaplib
import email
import subprocess
import time
from pathlib import Path
from datetime import datetime
from email.mime.text import MIMEText

from utils.call_llm import call_llm


def send_confirmation_mail(mail_address, node, command, purpose):
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    body = f"""以下のコマンドを実行しようとしています。
ノード: {node}
実行コマンド:
{command}
目的:
{purpose}
実行する場合は、このメールに「y」と返信してください。
実行しない場合は、「n」と返信してください。
修正したい場合は、修正内容をそのまま返信してください。
"""

    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = f"[GROMACS 実行確認] {node}"
    message["From"] = smtp_user
    message["To"] = mail_address
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(message)

def wait_confirmation_mail(mail_address, node):
    imap_host = os.environ.get("IMAP_HOST", "imap.gmail.com")
    imap_port = int(os.environ.get("IMAP_PORT", "993"))
    imap_user = os.environ["IMAP_USER"]
    imap_password = os.environ["IMAP_PASSWORD"]
    while True:
        mail = imaplib.IMAP4_SSL(imap_host, imap_port)
        mail.login(imap_user, imap_password)
        mail.select("INBOX")
        status, messages = mail.search(None, f'FROM "{mail_address}"')
        if status == "OK":
            message_ids = messages[0].split()
            for message_id in reversed(message_ids):
                status, data = mail.fetch(message_id, "(RFC822)")
                if status != "OK":
                    continue
                message = email.message_from_bytes(data[0][1])
                subject = message.get("Subject", "")
                if node not in subject:
                    continue
                body = ""
                if message.is_multipart():
                    for part in message.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body += payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                else:
                    payload = message.get_payload(decode=True)
                    if payload:
                        body = payload.decode(message.get_content_charset() or "utf-8", errors="ignore")
                answer = body.strip()
                if answer.lower() == "y":
                    mail.logout()
                    return {"回答": "y"}
                if answer.lower() == "n":
                    mail.logout()
                    return {"回答": "n"}
                if answer:
                    mail.logout()
                    return {"回答": "修正", "修正内容": answer}
        mail.logout()
        time.sleep(10)


def revise_command(node, command, purpose, revision, api_key):
    error = f"""
現在、以下のコマンドを実行しようとしています。

ノード:
{node}

実行コマンド:
{command}

目的:
{purpose}

ユーザーから以下の修正指示がありました。

{revision}

この修正指示を反映して、実行するコマンドを修正してください。
"""
    return call_llm(error, api_key)


def confirm_execution(mail_address, node, command, purpose, api_key):
    while True:
        send_confirmation_mail(mail_address, node, command, purpose)
        print(f"[CONFIRM] {node}")
        print(f"[COMMAND] {command}")
        print("[CONFIRM] メールで y / n または修正指示の返信を待っています...")
        confirmation = wait_confirmation_mail(mail_address, node)
        if confirmation["回答"] == "y":
            return {
                "実行": True,
                "実行コマンド": command,
                "目的": purpose
            }
        if confirmation["回答"] == "n":
            return {
                "実行": False,
                "実行コマンド": command,
                "目的": purpose
            }
        revision = confirmation["修正内容"]
        print(f"[REVISION] {revision}")
        revised = revise_command(node, command, purpose, revision, api_key)
        command = revised["実行コマンド"]
        purpose = revised["目的"]
        print(f"[REVISED COMMAND] {command}")
        print(f"[REVISED PURPOSE] {purpose}")


def recovery(node, result, plan, history, execution_path, api_key, mail_address):
    print(f"[ERROR] {node}\n{result['エラー']}")
    recovery_result = call_llm(result["エラー"], api_key)
    command = recovery_result["実行コマンド"]
    purpose = recovery_result["目的"]
    print(f"[RECOVERY] {command}")
    print(f"[PURPOSE] {purpose}")
    confirmation = confirm_execution(mail_address, node, command, purpose, api_key)
    if not confirmation["実行"]:
        print("[RECOVERY] 実行を中止しました")
        return False
    r = subprocess.run(confirmation["実行コマンド"], shell=True, cwd=execution_path, capture_output=True, text=True)
    recovery_history = {
        "ノード": node,
        "実行コマンド": confirmation["実行コマンド"],
        "目的": confirmation["目的"],
        "出力": r.stdout,
        "エラー": r.stderr,
        "終了コード": r.returncode
    }
    history.append(recovery_history)
    return r.returncode == 0

def main():
    p = argparse.ArgumentParser()
    p.add_argument("-p", "--plan", required=True)
    p.add_argument("--history")
    p.add_argument("-l", "--logpath")
    p.add_argument("-s", "--start")
    p.add_argument("-e", "--end")
    p.add_argument("-ep", "--executionpath")
    p.add_argument("-k", "--api-key", required=True)
    p.add_argument("-m", "--mail", required=True)
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
    nodes = list(plan)
    node = a.start or nodes[0]
    end = a.end or nodes[-1]
    history = []
    try:
        while True:
            n = plan[node]
            confirmation = confirm_execution(a.mail, node, n["実行コマンド"], n["目的"], a.api_key)
            if not confirmation["実行"]:
                print(f"[ABORT] {node} の実行を中止しました")
                break
            try:
                r = subprocess.run(confirmation["実行コマンド"], shell=True, cwd=execution_path, capture_output=True, text=True)
            except KeyboardInterrupt:
                raise
            result = {
                "ノード": node,
                "実行コマンド": confirmation["実行コマンド"],
                "目的": confirmation["目的"],
                "出力": r.stdout,
                "エラー": r.stderr,
                "終了コード": r.returncode
            }
            history.append(result)
            if r.returncode != 0:
                if recovery(node, result, plan, history, execution_path, a.api_key, a.mail):
                    continue
                break
            if node == end:
                break
            node = n["次のノード"]
    finally:
        json.dump(history, open(history_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        json.dump(history, open(log_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
