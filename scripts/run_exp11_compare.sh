#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_TS="$(date +%Y%m%d_%H%M%S)"
COMPARE_DIR="${ROOT_DIR}/outputs/exp11_compare_${OUT_TS}"
mkdir -p "${COMPARE_DIR}"

: "${IMAGE:?ERROR: set IMAGE, e.g. IMAGE=wwiras/ahbn-peer:v11 ./scripts/run_exp11_compare.sh}"
export IMAGE
export NAMESPACE="${NAMESPACE:-ahbn-exp11}"
export RELEASE="${RELEASE:-ahbn}"

echo "[A] Running AHBN baseline for Exp11 churn"
"${ROOT_DIR}/scripts/run_experiment.sh" experiments/exp11_ahbn_baseline.yaml | tee "${COMPARE_DIR}/ahbn_run.log"
AHBN_DIR="$(grep 'DONE ->' "${COMPARE_DIR}/ahbn_run.log" | tail -1 | awk '{print $3}')"

# Clean up before next run so StatefulSet/Job state does not leak into Q-AHBN.
helm uninstall "${RELEASE}" -n "${NAMESPACE}" >/dev/null 2>&1 || true
kubectl delete namespace "${NAMESPACE}" --wait=true >/dev/null 2>&1 || true
sleep 5

echo "[B] Running Q-AHBN for Exp11-Q churn"
"${ROOT_DIR}/scripts/run_experiment.sh" experiments/exp11_qahbn.yaml | tee "${COMPARE_DIR}/qahbn_run.log"
QAHBN_DIR="$(grep 'DONE ->' "${COMPARE_DIR}/qahbn_run.log" | tail -1 | awk '{print $3}')"

# cp "${AHBN_DIR}/exp11_summary.csv" "${COMPARE_DIR}/exp11_ahbn_summary.csv"
# cp "${QAHBN_DIR}/exp11_summary.csv" "${COMPARE_DIR}/exp11_qahbn_summary.csv"

python "${ROOT_DIR}/app/plot_exp11_qahbn_compare.py" \
  --ahbn-log "${AHBN_DIR}/logs.jsonl" \
  --qahbn-log "${QAHBN_DIR}/logs.jsonl" \
  --expected-nodes 20 \
  --outdir "${COMPARE_DIR}"

echo "DONE -> ${COMPARE_DIR}"
echo "AHBN  -> ${AHBN_DIR}"
echo "Q-AHBN -> ${QAHBN_DIR}"
