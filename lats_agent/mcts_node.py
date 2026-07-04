# lats_agent/mcts_node.py
"""
MCTSノードの定義。
各ノードは「ある修復操作を適用した後のPDB状態」を表す。

State = (current_pdb_path, repair_history, fatal_error_text)
Edge  = 修復操作(repair function)
"""

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MCTSNode:
    # --- State ---
    pdb_path: str               # このノード時点のPDBファイルパス
    repair_history: list        # ここに至るまでに適用した修復操作名のリスト
    fatal_error_text: Optional[str]  # 直前のgmx実行で出たFatal error(成功ならNone)
    extra_flags: Optional[list] # 次のgmx実行に渡すフラグ(-ignh等)
    depth: int = 0              # 根からの深さ

    # --- MCTS統計 ---
    visit_count: int = 0        # このノードを訪問した回数(N)
    total_value: float = 0.0    # 累積報酬(W)
    llm_value_estimate: Optional[float] = None  # LLMが推定した価値(V)

    # --- 木構造 ---
    parent: Optional["MCTSNode"] = field(default=None, repr=False)
    children: list = field(default_factory=list, repr=False)
    untried_actions: list = field(default_factory=list, repr=False)
    # untried_actionsは「このノードからまだ試していない修復関数のリスト」

    # --- 結果 ---
    is_terminal: bool = False   # 成功(success)または回復不可で終了したか
    is_success: bool = False    # pdb2gmxが通ったか
    structure_altered: bool = False  # 生物学的に重要な構造変更を伴ったか
    gmx_duration_sec: float = 0.0

    # --- LLMによる振り返り(Reflection) ---
    reflection: Optional[str] = None  # 失敗した場合のLLMの自己批判

    @property
    def q_value(self) -> float:
        """平均報酬 Q(s,a) = W / N"""
        if self.visit_count == 0:
            return 0.0
        return self.total_value / self.visit_count

    def ucb_score(self, exploration_constant: float = 1.4) -> float:
        """
        UCB1スコア = Q(s,a) + c * sqrt(ln(N_parent) / N)
        未訪問ノードは最優先で選ばれるよう+inf を返す
        """
        if self.visit_count == 0:
            return float("inf")
        parent_visits = self.parent.visit_count if self.parent else 1
        exploit = self.q_value
        explore = exploration_constant * math.sqrt(
            math.log(parent_visits) / self.visit_count
        )
        return exploit + explore

    def best_child(self, exploration_constant: float = 1.4) -> "MCTSNode":
        """UCBスコアが最大の子ノードを返す"""
        return max(self.children, key=lambda c: c.ucb_score(exploration_constant))

    def is_fully_expanded(self) -> bool:
        """全ての候補修復操作を試したか"""
        return len(self.untried_actions) == 0

    def action_path(self) -> str:
        """根からこのノードへのパスを文字列で返す(デバッグ用)"""
        return " → ".join(self.repair_history) if self.repair_history else "root"

    def __repr__(self):
        return (
            f"MCTSNode(depth={self.depth}, "
            f"visits={self.visit_count}, "
            f"Q={self.q_value:.3f}, "
            f"path={self.action_path()}, "
            f"success={self.is_success})"
        )
