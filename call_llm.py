# ============================================================
# Usage:
#   python3 call_llm.py \
#     --system-prompt system.txt \
#     --user-prompt user.txt \
#     --schema schema.json \
#     --api_key "YOUR_API_KEY"
# ============================================================

import argparse
import csv
import json
import subprocess
import sys
import time
from groq import Groq


def main(system_prompt, user_prompt, schema, api_key):
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0,
        max_tokens=2000,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "graph",
                "strict": True,
                "schema": schema
            }
        }
    )
    usage = response.usage
    print(
        f"  tokens: "
        f"prompt={usage.prompt_tokens}, "
        f"completion={usage.completion_tokens}, "
        f"total={usage.total_tokens}"
    )
    return json.loads(response.choices[0].message.content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--system-prompt", required=True)
    parser.add_argument("--user-prompt", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--api_key", required=True)
    args = parser.parse_args()
  
    system_prompt = open(args.system_prompt, encoding="utf-8").read()
    user_prompt = open(args.user_prompt, encoding="utf-8").read()
    schema = json.load(open(args.schema, encoding="utf-8"))

    main(system_prompt, user_prompt, schema, args.api_key)
