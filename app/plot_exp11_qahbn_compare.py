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
            if not line or not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
                row["variant"] = label
                rows.append(row)
            except Exception:
                continue
    return pd.DataFrame(rows)


def summarize_one(df: pd.DataFrame, expected_nodes: int, variant: str) -> dict:
    injected = df[df["event"] == "message_injected"].copy()
    recv_new = df[df["event"] == "received_new"].copy()
    recv_dup = df[df["event"] == "received_duplicate"].copy()
    forwards = df[df["event"] == "forward"].copy()
    churn = df[df["event"] == "churn_triggered"].copy()
    recovered = df[df["event"] == "churn_recovered"].copy()
    q_decision = df[df["event"] == "q_decision"].copy()
    q_update = df[df["event"] == "q_update"].copy()

    msg_ids = injected["message_id"].dropna().unique().tolist() if not injected.empty else []
    delivered_counts = recv_new.groupby("message_id")["peer_id"].nunique() if not recv_new.empty else pd.Series(dtype=float)

    delay_per_msg = []
    for msg_id in msg_ids:
        inject_ts = injected.loc[injected["message_id"] == msg_id, "ts"].min()
        max_recv_ts = recv_new.loc[recv_new["message_id"] == msg_id, "ts"].max()
        if pd.notna(inject_ts) and pd.notna(max_recv_ts):
            delay_per_msg.append(float(max_recv_ts - inject_ts))

    if not churn.empty and not recovered.empty:
        pairs = []
        for _, ch in churn.iterrows():
            rec = recovered[
                (recovered.get("churn_index") == ch.get("churn_index"))
                | (recovered.get("target_peer") == ch.get("target_peer"))
            ]
            if not rec.empty:
                pairs.append(float(rec["ts"].min() - ch["ts"]))
        avg_recovery = sum(pairs) / len(pairs) if pairs else 0.0
    else:
        avg_recovery = 0.0

    avg_delivery_ratio = float(delivered_counts.mean() / expected_nodes) if len(delivered_counts) else 0.0
    min_delivery_ratio = float(delivered_counts.min() / expected_nodes) if len(delivered_counts) else 0.0
    avg_delay = float(sum(delay_per_msg) / len(delay_per_msg)) if delay_per_msg else 0.0
    duplicate_ratio = float(len(recv_dup) / max(1, len(recv_new) + len(recv_dup)))
    forwards_ratio = float(len(forwards) / max(1, len(recv_new)))
    normalized_cost = (0.50 * duplicate_ratio) + (0.50 * forwards_ratio)
    adaptation_efficiency = avg_delivery_ratio / max(1e-9, normalized_cost)

    return {
        "variant": variant,
        "failure_mode": "churn",
        "message_count": len(msg_ids),
        "avg_delivery_ratio": avg_delivery_ratio,
        "min_delivery_ratio": min_delivery_ratio,
        "avg_propagation_delay_sec": avg_delay,
        "avg_recovery_sec": avg_recovery,
        "duplicates": int(len(recv_dup)),
        "total_forwards": int(len(forwards)),
        "duplicate_ratio": duplicate_ratio,
        "forwards_ratio": forwards_ratio,
        "adaptation_efficiency": adaptation_efficiency,
        "churn_events": int(len(churn)),
        "recovered_events": int(len(recovered)),
        "q_decisions": int(len(q_decision)),
        "q_updates": int(len(q_update)),
        "q_states": int(q_decision["q_state"].nunique()) if not q_decision.empty and "q_state" in q_decision else 0,
    }


def plot_bar(summary: pd.DataFrame, col: str, ylabel: str, title: str, out: Path) -> None:
    plt.figure(figsize=(7.5, 4.5))
    plt.bar(summary["variant"], summary[col])
    plt.ylabel(ylabel)
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out, dpi=180)
    plt.close()


def plot_delivery_timeline(df: pd.DataFrame, expected_nodes: int, out: Path) -> None:
    plt.figure(figsize=(8.5, 4.8))
    for variant, part in df.groupby("variant"):
        injected = part[part["event"] == "message_injected"]
        recv = part[part["event"] == "received_new"]
        if injected.empty or recv.empty:
            continue
        t0 = injected["ts"].min()
        rows = []
        for msg_id, grp in recv.groupby("message_id"):
            inj = injected.loc[injected["message_id"] == msg_id, "ts"]
            if inj.empty:
                continue
            rows.append({
                "t": grp["ts"].max() - t0,
                "delivery_ratio": grp["peer_id"].nunique() / expected_nodes,
            })
        if rows:
            d = pd.DataFrame(rows).sort_values("t")
            plt.plot(d["t"], d["delivery_ratio"], marker="o", label=variant)
    plt.xlabel("Time since first injection (s)")
    plt.ylabel("Delivery ratio per message")
    plt.title("Figure 14 - Delivery ratio under churn")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out, dpi=180)
    plt.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ahbn-log", required=True)
    ap.add_argument("--qahbn-log", required=True)
    ap.add_argument("--expected-nodes", type=int, required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    ahbn = load_jsonl(args.ahbn_log, "AHBN")
    qahbn = load_jsonl(args.qahbn_log, "Q-AHBN")
    combined = pd.concat([ahbn, qahbn], ignore_index=True)

    summary = pd.DataFrame([
        summarize_one(ahbn, args.expected_nodes, "AHBN"),
        summarize_one(qahbn, args.expected_nodes, "Q-AHBN"),
    ])

    summary.to_csv(outdir / "table11_exp11q_gke_churn_results.csv", index=False)
    summary.to_csv(outdir / "exp11q_gke_comparison_summary.csv", index=False)

    plot_bar(summary, "avg_propagation_delay_sec", "Average propagation delay (s)", "Figure 12 - Delay under churn", outdir / "fig12_delay_under_churn.png")
    plot_bar(summary, "avg_recovery_sec", "Average pod recovery time (s)", "Figure 13 - Recovery under churn", outdir / "fig13_recovery_under_churn.png")
    plot_delivery_timeline(combined, args.expected_nodes, outdir / "fig14_delivery_ratio.png")
    plot_bar(summary, "adaptation_efficiency", "Delivery / normalized cost", "Adaptation efficiency under churn", outdir / "fig21_adaptation_efficiency_churn.png")

    print("\nTABLE 11 - Exp11-Q GKE Churn Results")
    print(summary.to_string(index=False))
    print(f"\nSaved outputs to: {outdir}")


if __name__ == "__main__":
    main()
