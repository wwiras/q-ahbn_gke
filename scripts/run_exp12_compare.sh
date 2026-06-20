#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_TS="$(date +%Y%m%d_%H%M%S)"
COMPARE_DIR="${ROOT_DIR}/outputs/exp12_compare_${OUT_TS}"
mkdir -p "${COMPARE_DIR}"

: "${IMAGE:?ERROR: set IMAGE, e.g. IMAGE=wwiras/qahbn-peer:v7 ./scripts/run_exp12_compare.sh}"
export IMAGE
export NAMESPACE="${NAMESPACE:-ahbn-exp12}"
export RELEASE="${RELEASE:-ahbn}"

echo "[A] Running AHBN baseline for Exp12 heterogeneity"
"${ROOT_DIR}/scripts/run_experiment.sh" experiments/exp12_ahbn_baseline.yaml | tee "${COMPARE_DIR}/ahbn_run.log"
AHBN_DIR="$(grep 'DONE ->' "${COMPARE_DIR}/ahbn_run.log" | tail -1 | awk '{print $3}')"

helm uninstall "${RELEASE}" -n "${NAMESPACE}" >/dev/null 2>&1 || true
kubectl delete namespace "${NAMESPACE}" --wait=true >/dev/null 2>&1 || true
sleep 5

echo "[B] Running Q-AHBN for Exp12-Q heterogeneity"
"${ROOT_DIR}/scripts/run_experiment.sh" experiments/exp12_qahbn.yaml | tee "${COMPARE_DIR}/qahbn_run.log"
QAHBN_DIR="$(grep 'DONE ->' "${COMPARE_DIR}/qahbn_run.log" | tail -1 | awk '{print $3}')"

python "${ROOT_DIR}/app/plot_exp12_qahbn_compare.py" \
  --ahbn-log "${AHBN_DIR}/logs.jsonl" \
  --qahbn-log "${QAHBN_DIR}/logs.jsonl" \
  --expected-nodes 20 \
  --outdir "${COMPARE_DIR}"

echo "DONE -> ${COMPARE_DIR}"
echo "AHBN   -> ${AHBN_DIR}"
echo "Q-AHBN -> ${QAHBN_DIR}"
