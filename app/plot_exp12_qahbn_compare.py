from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def load_jsonl(path: str, label: str) -> pd.DataFrame:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                r = json.loads(line)
                r["compare_label"] = label
                rows.append(r)
            except Exception:
                pass
    return pd.DataFrame(rows)


def summarize_one(df: pd.DataFrame, expected_nodes: int, label: str) -> dict:
    injected = df[df["event"] == "message_injected"].copy()
    recv = df[df["event"] == "received_new"].copy()
    dup = df[df["event"] == "received_duplicate"].copy()
    fwd = df[df["event"] == "forward"].copy()
    qd = df[df["event"] == "q_decision"].copy()

    msg_count = injected["message_id"].nunique() if not injected.empty else recv["message_id"].nunique()
    expected = max(1, expected_nodes * max(1, msg_count))
    delivered = recv[["message_id", "peer_id"]].drop_duplicates().shape[0] if not recv.empty else 0

    delivery_ratio = delivered / expected
    duplicates = len(dup)
    forwards = len(fwd)
    duplicate_ratio = duplicates / max(1, delivered + duplicates)
    forwarding_cost = forwards / max(1, expected)

    normal = recv[recv["overload_ms"].fillna(0).astype(float) == 0] if "overload_ms" in recv else pd.DataFrame()
    lowres = recv[recv["overload_ms"].fillna(0).astype(float) > 0] if "overload_ms" in recv else pd.DataFrame()

    normal_delay = normal["latency_ms"].mean() if not normal.empty and "latency_ms" in normal else 0.0
    lowres_delay = lowres["latency_ms"].mean() if not lowres.empty and "latency_ms" in lowres else 0.0
    avg_delay = recv["latency_ms"].mean() if not recv.empty and "latency_ms" in recv else 0.0

    cost = 1.0 + duplicate_ratio + forwarding_cost + min(2.0, avg_delay / 10000.0)
    ae = delivery_ratio / max(cost, 1e-9)

    return {
        "strategy": label,
        "message_count": int(msg_count),
        "delivery_ratio": delivery_ratio,
        "normal_delay_ms": normal_delay,
        "low_resource_delay_ms": lowres_delay,
        "avg_latency_ms": avg_delay,
        "duplicates": duplicates,
        "duplicate_ratio": duplicate_ratio,
        "total_forwards": forwards,
        "forwarding_cost": forwarding_cost,
        "adaptation_efficiency": ae,
        "q_decisions": len(qd),
        "q_pct_resource_conservative": qd["q_action"].eq("resource_conservative").mean() if not qd.empty and "q_action" in qd else 0.0,
        "q_pct_duplicate_suppression": qd["q_action"].eq("duplicate_suppression").mean() if not qd.empty and "q_action" in qd else 0.0,
        "q_pct_more_gossip": qd["q_action"].eq("more_gossip").mean() if not qd.empty and "q_action" in qd else 0.0,
        "q_pct_more_structured": qd["q_action"].eq("more_structured").mean() if not qd.empty and "q_action" in qd else 0.0,
    }


def bar(summary: pd.DataFrame, col: str, title: str, ylabel: str, out: Path) -> None:
    plt.figure(figsize=(7, 4))
    plt.bar(summary["strategy"], summary[col])
    plt.ylabel(ylabel)
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out, dpi=180)
    plt.close()


def grouped_delay(summary: pd.DataFrame, out: Path) -> None:
    x = range(len(summary))
    width = 0.35
    plt.figure(figsize=(7, 4))
    plt.bar([i - width / 2 for i in x], summary["normal_delay_ms"], width, label="normal")
    plt.bar([i + width / 2 for i in x], summary["low_resource_delay_ms"], width, label="low-resource")
    plt.xticks(list(x), summary["strategy"])
    plt.ylabel("Mean latency (ms)")
    plt.title("Figure 15 / 20. Normal vs low-resource delay")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out, dpi=180)
    plt.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ahbn-log", required=True)
    ap.add_argument("--qahbn-log", required=True)
    ap.add_argument("--expected-nodes", type=int, default=20)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    figdir = outdir / "figures"
    tabdir = outdir / "tables"
    figdir.mkdir(parents=True, exist_ok=True)
    tabdir.mkdir(parents=True, exist_ok=True)

    ahbn = load_jsonl(args.ahbn_log, "AHBN")
    qahbn = load_jsonl(args.qahbn_log, "Q-AHBN")

    summary = pd.DataFrame([
        summarize_one(ahbn, args.expected_nodes, "AHBN"),
        summarize_one(qahbn, args.expected_nodes, "Q-AHBN"),
    ])

    summary.to_csv(tabdir / "table15_exp12q_gke_heterogeneity_results.csv", index=False)
    summary.to_csv(tabdir / "table12_exp12q_heterogeneity_results.csv", index=False)

    grouped_delay(summary, figdir / "fig15_normal_vs_low_resource_delay.png")
    grouped_delay(summary, figdir / "fig20_latency_comparison.png")
    bar(summary, "duplicates", "Figure 16. Duplicates under heterogeneity", "Duplicates", figdir / "fig16_duplicates.png")
    bar(summary, "forwarding_cost", "Figure 17. Forwarding cost", "Forwarding cost", figdir / "fig17_forwarding_cost.png")

    print("Saved:")
    print(tabdir / "table15_exp12q_gke_heterogeneity_results.csv")
    print(figdir / "fig15_normal_vs_low_resource_delay.png")
    print(figdir / "fig16_duplicates.png")
    print(figdir / "fig17_forwarding_cost.png")
    print(figdir / "fig20_latency_comparison.png")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
