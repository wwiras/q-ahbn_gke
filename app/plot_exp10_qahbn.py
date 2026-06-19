from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def load_jsonl(path: str) -> pd.DataFrame:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return pd.DataFrame(rows)


def adaptation_efficiency(delivery_ratio: float, duplicate_ratio: float,
                          forwards_norm: float, latency_norm: float) -> float:
    # Higher is better: delivery achieved per normalized adaptation cost.
    cost = 1.0 + duplicate_ratio + forwards_norm + latency_norm
    return delivery_ratio / max(cost, 1e-9)


def summarize(df: pd.DataFrame, expected_nodes: int) -> pd.DataFrame:
    rows = []
    for run_id, g in df.groupby("run_id", dropna=False):
        recv = g[g["event"] == "received_new"].copy()
        dup = g[g["event"] == "received_duplicate"].copy()
        fwd = g[g["event"] == "forward"].copy()
        fail = g[g["event"] == "failure_triggered"].copy()
        qd = g[g["event"] == "q_decision"].copy()

        strategy = g["strategy"].dropna().iloc[0] if "strategy" in g.columns and not g["strategy"].dropna().empty else "unknown"
        delivered = recv[["message_id", "peer_id"]].drop_duplicates().shape[0] if not recv.empty else 0
        
        # expected = expected_nodes * max(1, recv["message_id"].nunique() if not recv.empty else 1)
        injected = g[g["event"] == "message_injected"]

        message_count = (
            injected["message_id"].nunique()
            if not injected.empty
            else 1
        )

        expected = expected_nodes * message_count
        
        dr = delivered / expected if expected > 0 else 0.0
        duplicates = len(dup)
        forwards = len(fwd)
        dup_ratio = duplicates / max(1, delivered + duplicates)
        inject_ts = g.loc[g["event"] == "message_injected", "ts"].min()
        max_recv_ts = recv["ts"].max() if not recv.empty else float("nan")
        delay = max_recv_ts - inject_ts if pd.notna(inject_ts) and pd.notna(max_recv_ts) else float("nan")
        
        # fail_ts = fail["ts"].min() if not fail.empty else float("nan")
        # recovery = max_recv_ts - fail_ts if pd.notna(fail_ts) and pd.notna(max_recv_ts) else float("nan")
        fail_ts = fail["ts"].min() if not fail.empty else float("nan")

        if pd.notna(fail_ts) and not recv.empty:

            post_failure_recv = recv[recv["ts"] > fail_ts]

            if not post_failure_recv.empty:
                recovery = post_failure_recv["ts"].min() - fail_ts
            else:
                recovery = float("nan")

        else:
            recovery = float("nan")

        latency_norm = min(2.0, delay / 10.0) if pd.notna(delay) else 2.0
        forwards_norm = min(2.0, forwards / max(1, expected * 2))
        ae = adaptation_efficiency(dr, dup_ratio, forwards_norm, latency_norm)

        rows.append({
            "run_id": run_id,
            "strategy": strategy,
            "delivery_ratio": dr,
            "duplicates": duplicates,
            "duplicate_ratio": dup_ratio,
            "total_forwards": forwards,
            "propagation_delay_s": delay,
            "recovery_time_s": recovery,
            "adaptation_efficiency": ae,
            "q_decisions": len(qd),
            "q_updates": int(qd["q_updates"].max()) if not qd.empty and "q_updates" in qd else 0,
            
            # "q_pct_recovery_push": (qd["q_action"].eq("recovery_push").mean() if not qd.empty and "q_action" in qd else 0.0),
            "q_pct_recovery_push": (
                qd["q_action"].eq("recovery_push").mean()
                if not qd.empty and "q_action" in qd
                else 0.0
            ),
            "q_pct_more_gossip": (
                qd["q_action"].eq("more_gossip").mean()
                if not qd.empty and "q_action" in qd
                else 0.0
            ),
            "q_pct_more_structured": (
                qd["q_action"].eq("more_structured").mean()
                if not qd.empty and "q_action" in qd
                else 0.0
            ),
            "q_pct_duplicate_suppression": (
                qd["q_action"].eq("duplicate_suppression").mean()
                if not qd.empty and "q_action" in qd
                else 0.0
            ),
            "q_pct_resource_conservative": (
                qd["q_action"].eq("resource_conservative").mean()
                if not qd.empty and "q_action" in qd
                else 0.0
            ),
            
            "expected_deliveries": expected,
            "actual_deliveries": delivered,
        })
        
    summary = pd.DataFrame(rows)

    summary = summary[
        summary["strategy"].notna()
    ]

    summary = summary[
        summary["strategy"] != "unknown"
    ]

    return summary
    # return pd.DataFrame(rows)


def plot_failure_timeline(df: pd.DataFrame, out_png: Path) -> None:
    recv = df[df["event"] == "received_new"].copy()
    fail = df[df["event"] == "failure_triggered"].copy()
    if recv.empty:
        return
    recv = recv.sort_values("ts")
    t0 = recv["ts"].min()
    recv["delivered_count"] = range(1, len(recv) + 1)
    plt.figure(figsize=(8, 4))
    plt.plot(recv["ts"] - t0, recv["delivered_count"], label="cumulative delivery")
    if not fail.empty:
        plt.axvline(fail["ts"].min() - t0, linestyle="--", linewidth=1, label="failure")
    plt.xlabel("Time since first delivery (s)")
    plt.ylabel("Cumulative new deliveries")
    plt.title("Figure 18. Exp10-Q Kubernetes failure timeline")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=180)
    plt.close()


def plot_adaptation_efficiency(summary: pd.DataFrame, out_png: Path) -> None:
    plt.figure(figsize=(7, 4))
    labels = summary["strategy"].astype(str).tolist()
    vals = summary["adaptation_efficiency"].tolist()
    plt.bar(labels, vals)
    plt.ylabel("Adaptation efficiency")
    plt.title("Figure 21. Adaptation Efficiency Summary")
    plt.tight_layout()
    plt.savefig(out_png, dpi=180)
    plt.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", nargs="+", required=True, help="One or more jsonl log files")
    ap.add_argument("--expected-nodes", type=int, default=20)
    ap.add_argument("--outdir", default="outputs/exp10q_gke")
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = Path(args.outdir)
    figdir = outdir / "figures"
    tabdir = outdir / "tables"
    figdir.mkdir(parents=True, exist_ok=True)
    tabdir.mkdir(parents=True, exist_ok=True)

    frames = []
    for log in args.log:
        df = load_jsonl(log)
        if not df.empty:
            frames.append(df)
            stem = Path(log).stem
            plot_failure_timeline(df, figdir / f"{stamp}_fig18_failure_timeline_{stem}.png")

    if not frames:
        raise SystemExit("No JSON log rows found")
    df_all = pd.concat(frames, ignore_index=True)
    summary = summarize(df_all, expected_nodes=args.expected_nodes)
    table_path = tabdir / f"{stamp}_table13_exp10q_gke_failure_results.csv"
    summary.to_csv(table_path, index=False)
    plot_adaptation_efficiency(summary, figdir / f"{stamp}_fig21_adaptation_efficiency_summary.png")

    print(f"Saved {table_path}")
    print(f"Saved {figdir / (stamp + '_fig21_adaptation_efficiency_summary.png')}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
