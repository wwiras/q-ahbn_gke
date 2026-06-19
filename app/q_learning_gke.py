from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict


StateKey = tuple[str, str, str, str]

@dataclass(frozen=True)
class QAction:
    name: str
    fanout_delta: int
    prefer_mode: str | None = None

class GKEQLearner:
    """Small per-pod Q-learning meta-controller for Kubernetes Exp10-Q.

    It keeps AHBN intact. AHBN first decides mode/fanout using local rules;
    Q-AHBN then applies a small meta-action. State and reward are intentionally
    lightweight because each pod only sees local observations.
    """

    def __init__(self, peer_id: int, min_fanout: int, max_fanout: int,
                 default_fanout: int, mode_threshold: float,
                 cfg: dict | None = None, seed: int = 42) -> None:
        self.peer_id = peer_id
        self.min_fanout = int(min_fanout)
        self.max_fanout = int(max_fanout)
        self.default_fanout = int(default_fanout)
        self.mode_threshold = float(mode_threshold)
        self.cfg = cfg or {}
        self.rng = random.Random(seed)

        self.alpha = float(self.cfg.get("alpha", 0.25))
        self.gamma = float(self.cfg.get("gamma", 0.90))
        self.epsilon = float(self.cfg.get("epsilon", 0.20))
        self.epsilon_min = float(self.cfg.get("epsilon_min", 0.03))
        self.epsilon_decay = float(self.cfg.get("epsilon_decay", 0.995))

        self.w_delivery = float(self.cfg.get("w_delivery", 8.0))
        self.w_dup = float(self.cfg.get("w_dup", 0.30))
        self.w_forward = float(self.cfg.get("w_forward", 0.10))
        self.w_failure_bonus = float(self.cfg.get("w_failure_bonus", 2.0))

        self.actions = [
            QAction("ahbn_base", 0, None),
            QAction("more_structured", -1, "cluster"),
            QAction("more_gossip", 1, "gossip"),
            QAction("duplicate_suppression", -1, "cluster"),
            QAction("recovery_push", 2, "gossip"),
            QAction("resource_conservative", -1, None),
        ]

        self.q: DefaultDict[StateKey, dict[str, float]] = defaultdict(
            lambda: {a.name: 0.0 for a in self.actions}
        )
        self.prev_state: StateKey | None = None
        self.prev_action: str | None = None
        self.updates = 0
        self.decisions = 0
        self.last_reward = 0.0

    @staticmethod
    def bucket3(v: float, low: float, high: float) -> str:
        if v < low:
            return "L"
        if v < high:
            return "M"
        return "H"

    def state(self, duplicate_ratio: float, fail_pressure: float,
              overload_pressure: float, bottleneck_pressure: float) -> StateKey:
        disturbance = max(fail_pressure, overload_pressure, bottleneck_pressure)
        if disturbance >= 0.70:
            phase = "F"   # failure/recovery pressure
        elif disturbance >= 0.25:
            phase = "R"   # recovery transition
        else:
            phase = "N"   # normal
        return (
            self.bucket3(float(duplicate_ratio), 0.10, 0.35),
            self.bucket3(float(fail_pressure), 0.10, 0.50),
            self.bucket3(float(overload_pressure) + float(bottleneck_pressure), 0.10, 0.50),
            phase,
        )

    def choose(self, s: StateKey) -> str:
        if self.rng.random() < self.epsilon:
            return self.rng.choice(self.actions).name
        qvals = self.q[s]
        best = max(qvals.values())
        candidates = [a for a, v in qvals.items() if v == best]
        return self.rng.choice(candidates)

    def reward(self, duplicate_ratio: float, fail_pressure: float,
               recv_count: int, duplicate_count: int, forward_count: int) -> float:
        # Local delivery proxy: new receptions among total receptions.
        new_count = max(0, int(recv_count) - int(duplicate_count))
        delivery_proxy = new_count / max(1, int(recv_count))
        dup = min(1.0, max(0.0, float(duplicate_ratio)))
        f_norm = min(2.0, float(forward_count) / 20.0)
        recovery = min(1.0, max(0.0, float(fail_pressure)))
        return (
            self.w_delivery * delivery_proxy
            - self.w_dup * dup
            - self.w_forward * f_norm
            + self.w_failure_bonus * recovery
        )

    def apply(self, mode: str, fanout: int, action_name: str) -> tuple[str, int]:
        action = next(a for a in self.actions if a.name == action_name)
        new_mode = mode
        if action.prefer_mode is not None:
            new_mode = action.prefer_mode
        new_fanout = max(self.min_fanout, min(self.max_fanout, int(fanout) + action.fanout_delta))
        return new_mode, new_fanout

    def decide_and_apply(self, *, mode: str, fanout: int, duplicate_ratio: float,
                         fail_pressure: float, overload_pressure: float,
                         bottleneck_pressure: float, recv_count: int,
                         duplicate_count: int, forward_count: int) -> dict:
        s = self.state(duplicate_ratio, fail_pressure, overload_pressure, bottleneck_pressure)
        updated = False
        q_value = 0.0
        prev_s = self.prev_state
        prev_a = self.prev_action

        if prev_s is not None and prev_a is not None:
            r = self.reward(duplicate_ratio, fail_pressure, recv_count, duplicate_count, forward_count)
            old = self.q[prev_s][prev_a]
            best_next = max(self.q[s].values())
            q_value = old + self.alpha * (r + self.gamma * best_next - old)
            self.q[prev_s][prev_a] = q_value
            self.last_reward = r
            self.updates += 1
            updated = True

        action = self.choose(s)
        new_mode, new_fanout = self.apply(mode, fanout, action)
        self.prev_state = s
        self.prev_action = action
        self.decisions += 1
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

        return {
            "mode": new_mode,
            "fanout": new_fanout,
            "q_state": "|".join(s),
            "q_action": action,
            "q_reward": self.last_reward,
            "q_epsilon": self.epsilon,
            "q_updates": self.updates,
            "q_updated": updated,
            "q_prev_state": "|".join(prev_s) if prev_s else None,
            "q_prev_action": prev_a,
            "q_value": q_value,
        }
