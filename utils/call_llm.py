# call_llm.py
# ============================================================
# Usage:
#   python3 call_llm.py -k API_KEY -e "エラー内容"
# ============================================================
import argparse
import json
from groq import Groq

SYSTEM_PROMPT = """
目的：
エラーを解消する。

- 実行コマンド: コマンド
- 目的: なぜそのコマンドを実行するかという理由

json形式で出力する。
pythonを実行する場合はpython3 コード << EOFの形で実行すること
利用可能モジュールはnumpy、biopython
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "実行コマンド": {"type": "string"},
        "目的": {"type": "string"}
    },
    "required": ["実行コマンド", "目的"],
    "additionalProperties": False
}


def call_llm(error, api_key):
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"エラー内容:{error}"}
        ],
        temperature=0,
        max_tokens=500,
        response_format={"type": "json_schema", "json_schema": {"name": "gmx_agent", "strict": True, "schema": SCHEMA}}
    )
    return json.loads(response.choices[0].message.content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-k", "--api_key", required=True)
    parser.add_argument("-e", "--error", required=True)
    args = parser.parse_args()

    print(call_llm(args.error, args.api_key))


if __name__ == "__main__":
    main()
