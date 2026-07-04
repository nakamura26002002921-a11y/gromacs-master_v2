# lats_agent/llm_evaluator.py
"""
LLMをLATSの3つの役割で使う:
  1. Action Generator  : 現在の状態から試すべき修復候補を優先順位付きで提案
  2. Value Function    : 現在の状態の「修復完了しやすさ」をスコアで推定
  3. Reflection        : 失敗した軌跡に対して自己批判を生成し、次の探索に活かす
"""

import json
import re
import requests


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1000


def _call_llm(prompt: str) -> str:
    """Anthropic APIを呼ぶ共通関数"""
    response = requests.post(
        ANTHROPIC_API_URL,
        headers={"Content-Type": "application/json"},
        json={
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    response.raise_for_status()
    data = response.json()
    return data["content"][0]["text"]


def estimate_value(
    fatal_error_text: str,
    repair_history: list,
    available_repair_names: list,
) -> float:
    """
    Value Function:
    現在の状態(エラー内容・修復履歴・残り候補)から、
    「この先成功しやすいか」を0.0〜1.0で推定する。
    LLMに自然言語で根拠を述べさせた上でスコアを返させる。
    """
    history_str = " → ".join(repair_history) if repair_history else "なし"
    candidates_str = ", ".join(available_repair_names) if available_repair_names else "なし"

    prompt = f"""あなたはGROMACSによる分子動力学シミュレーションのセットアップを自動修復するシステムの評価器です。

## 現在の状態
- これまでに試した修復操作: {history_str}
- 現在のGROMACSエラー(Fatal error):
```
{fatal_error_text or "エラーなし(成功)"}
```
- まだ試していない修復候補: {candidates_str}

## 評価タスク
上記の状態から、このエラーが残り候補によって解決できる可能性を0.0〜1.0で推定してください。

評価基準:
- 1.0: エラー内容と修復候補が明確に対応しており、ほぼ確実に解決できる
- 0.5: 解決できるかどうか不明確
- 0.0: 残り候補ではこのエラーは解決できない、または既に手詰まり

## 出力形式(JSONのみ、前後の説明不要)
{{"score": 0.8, "reason": "HB3という水素原子名の不一致は-ignhフラグで対処可能なため"}}"""

    try:
        raw = _call_llm(prompt)
        # JSONブロックを抽出
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            score = float(data.get("score", 0.5))
            return max(0.0, min(1.0, score))  # 0〜1にクランプ
    except Exception as e:
        print(f"  [LLM ValueFunction] Error: {e}. Falling back to 0.5.")
    return 0.5


def generate_reflection(
    fatal_error_text: str,
    repair_history: list,
    failed_repair: str,
) -> str:
    """
    Reflection機構:
    失敗した軌跡を振り返り、「なぜ失敗したか」「次に何を試すべきか」を
    自然言語で生成する。これを次のノード展開のコンテキストとして活用する。
    """
    history_str = " → ".join(repair_history) if repair_history else "なし"

    prompt = f"""あなたはGROMACS修復エージェントの振り返りモジュールです。

## 失敗した軌跡
- 試した修復操作の順序: {history_str}
- 最後に試みた操作: {failed_repair}
- その後のGROMACSエラー:
```
{fatal_error_text}
```

## タスク
この失敗を分析し、以下を日本語で簡潔に答えてください:
1. なぜこの修復操作はこのエラーに対して効果がなかったか
2. このエラーを解決するために次に試すべき戦略(具体的な操作名で)
3. 注意すべき落とし穴

3文以内で答えてください。"""

    try:
        return _call_llm(prompt)
    except Exception as e:
        return f"[Reflection failed: {e}]"


def prioritize_actions(
    fatal_error_text: str,
    repair_history: list,
    candidate_fn_names: list,
    reflection_context: str = "",
) -> list:
    """
    Action Generator:
    現在の状態と振り返りコンテキストを踏まえて、
    候補修復操作の優先順位を並べ替えて返す。

    純粋なルールベース(REPAIR_CANDIDATES)の固定順序と異なり、
    LLMがエラーの内容に応じて順序を動的に決める。
    """
    if not candidate_fn_names:
        return []

    history_str = " → ".join(repair_history) if repair_history else "なし"
    reflection_str = f"\n## 前回の振り返り\n{reflection_context}" if reflection_context else ""

    prompt = f"""あなたはGROMACS修復エージェントの戦略立案モジュールです。

## 現在の状態
- これまでに試した修復操作: {history_str}
- 現在のGROMACSエラー:
```
{fatal_error_text or "エラーなし"}
```
{reflection_str}

## 候補修復操作(以下の中から選ぶ)
{json.dumps(candidate_fn_names, ensure_ascii=False)}

## タスク
上記の候補を、このエラーを解決できる可能性が高い順に並べ替えてください。
既に試した操作は除外してください。

## 出力形式(JSONのみ、前後の説明不要)
{{"ordered": ["最も試すべき操作", "次点", ...]}}"""

    try:
        raw = _call_llm(prompt)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            ordered = data.get("ordered", [])
            # LLMが候補に存在しない操作を返した場合に備えてフィルタ
            valid = [op for op in ordered if op in candidate_fn_names]
            # LLMが返さなかった候補を末尾に追加(取りこぼし防止)
            missing = [op for op in candidate_fn_names if op not in valid]
            return valid + missing
    except Exception as e:
        print(f"  [LLM ActionGenerator] Error: {e}. Using original order.")
    return candidate_fn_names
