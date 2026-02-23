#!/bin/bash
set -euo pipefail

# 最大同時実行数 (環境変数 MAX_JOBS で上書き可能)
MAX_JOBS="${MAX_JOBS:-6}"

LOG_DIR="experiments/logs"
mkdir -p "${LOG_DIR}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

EXP_YAMLS=(
    "experiments/configs/EXP-101.yaml"
    "experiments/configs/EXP-102.yaml"
    "experiments/configs/EXP-103.yaml"
    "experiments/configs/EXP-104.yaml"
    "experiments/configs/EXP-105.yaml"
    "experiments/configs/EXP-106.yaml"
    "experiments/configs/EXP-201.yaml"
    "experiments/configs/EXP-202.yaml"
    "experiments/configs/EXP-203.yaml"
    "experiments/configs/EXP-204.yaml"
    "experiments/configs/EXP-205.yaml"
    "experiments/configs/EXP-206.yaml"
    "experiments/configs/EXP-207.yaml"
    "experiments/configs/EXP-208.yaml"
    "experiments/configs/EXP-209.yaml"
    "experiments/configs/EXP-301.yaml"
    "experiments/configs/EXP-302.yaml"
    "experiments/configs/EXP-303.yaml"
    "experiments/configs/EXP-304.yaml"
    "experiments/configs/EXP-305.yaml"
    "experiments/configs/EXP-306.yaml"
)

TOTAL=${#EXP_YAMLS[@]}
echo "=== 実験並行実行開始: ${TOTAL} 件 (最大同時実行数: ${MAX_JOBS}) ==="
echo "ログディレクトリ: ${LOG_DIR}"
echo ""

# PID → 設定ファイル名 / ログファイルの対応を保持
declare -A PID_MAP
declare -A PID_LOG_MAP
RUNNING=0
SUMMARY_FILE="${LOG_DIR}/summary_${TIMESTAMP}.log"

# --- ログ末尾からエラーメッセージを表示・保存 ---
# TAIL_LINES 行分のログ末尾を表示する
TAIL_LINES=30

show_error_detail() {
    local yaml="$1"
    local exit_code="$2"
    local log_file="$3"
    local exp_name
    exp_name=$(basename "${yaml}" .yaml)

    {
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "✗ 失敗: ${yaml} (exit ${exit_code})"
        echo "  ログ: ${log_file}"
        echo ""
        if [[ -f "${log_file}" ]]; then
            echo "--- ${exp_name} ログ末尾 (最大${TAIL_LINES}行) ---"
            tail -n "${TAIL_LINES}" "${log_file}"
            echo "--- ここまで ---"
        else
            echo "(ログファイルが見つかりません)"
        fi
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    } | tee -a "${SUMMARY_FILE}"
}

# --- 全バックグラウンドジョブを停止する関数 ---
kill_all_jobs() {
    local pids=("${!PID_MAP[@]}")
    if (( ${#pids[@]} > 0 )); then
        echo ""
        echo "⚠ 実行中のジョブを停止しています..."
        for pid in "${pids[@]}"; do
            if kill -0 "${pid}" 2>/dev/null; then
                kill -TERM "${pid}" 2>/dev/null || true
            fi
        done
        # 子プロセスの終了を少し待つ
        sleep 1
        for pid in "${pids[@]}"; do
            if kill -0 "${pid}" 2>/dev/null; then
                kill -KILL "${pid}" 2>/dev/null || true
            fi
        done
        wait 2>/dev/null || true
        echo "全ジョブを停止しました。"
    fi
}

# --- Ctrl+C / SIGTERM で全停止 ---
cleanup() {
    echo ""
    echo "🛑 中断シグナルを受信しました。" | tee -a "${SUMMARY_FILE}"
    kill_all_jobs
    echo ""
    echo "サマリー: ${SUMMARY_FILE}"
    echo "ログディレクトリ: ${LOG_DIR}/"
    exit 130
}
trap cleanup SIGINT SIGTERM

# --- 1つでも失敗したら全停止 ---
abort_on_failure() {
    local failed_yaml="$1"
    local exit_code="$2"
    local failed_pid="$3"
    local log_file="${PID_LOG_MAP[${failed_pid}]:-unknown}"

    show_error_detail "${failed_yaml}" "${exit_code}" "${log_file}"
    kill_all_jobs
    echo ""
    echo "サマリー: ${SUMMARY_FILE}"
    echo "ログディレクトリ: ${LOG_DIR}/"
    exit 1
}

for EXP_YAML in "${EXP_YAMLS[@]}"; do
    # 同時実行数が上限に達したら、いずれかの完了を待つ
    while (( RUNNING >= MAX_JOBS )); do
        DONE_PID=""
        EXIT_CODE=0
        wait -n -p DONE_PID "${!PID_MAP[@]}" || EXIT_CODE=$?
        if [[ -n "${DONE_PID}" ]]; then
            FINISHED_YAML="${PID_MAP[${DONE_PID}]}"
            RUNNING=$((RUNNING - 1))
            if (( EXIT_CODE != 0 )); then
                abort_on_failure "${FINISHED_YAML}" "${EXIT_CODE}" "${DONE_PID}"
            else
                echo "  ✓ 完了: ${FINISHED_YAML}"
            fi
            unset "PID_MAP[${DONE_PID}]"
            unset "PID_LOG_MAP[${DONE_PID}]"
        fi
    done

    # 実験名をファイル名から抽出 (例: EXP-101)
    EXP_NAME=$(basename "${EXP_YAML}" .yaml)
    LOG_FILE="${LOG_DIR}/${EXP_NAME}_${TIMESTAMP}.log"

    echo "▶ 開始: ${EXP_NAME}"
    uv run idea-graph experiment run "${EXP_YAML}" --limit 5 \
        > "${LOG_FILE}" 2>&1 &
    PID=$!
    PID_MAP[${PID}]="${EXP_YAML}"
    PID_LOG_MAP[${PID}]="${LOG_FILE}"
    RUNNING=$((RUNNING + 1))
done

# 残りの全ジョブの完了を待つ
for PID in "${!PID_MAP[@]}"; do
    EXIT_CODE=0
    wait "${PID}" || EXIT_CODE=$?
    FINISHED_YAML="${PID_MAP[${PID}]}"
    if (( EXIT_CODE != 0 )); then
        abort_on_failure "${FINISHED_YAML}" "${EXIT_CODE}" "${PID}"
    else
        echo "  ✓ 完了: ${FINISHED_YAML}"
    fi
    unset "PID_MAP[${PID}]"
    unset "PID_LOG_MAP[${PID}]"
done

echo "" | tee -a "${SUMMARY_FILE}"
echo "=== 全実験完了 (${TOTAL}/${TOTAL} 成功) ===" | tee -a "${SUMMARY_FILE}"
echo "サマリー: ${SUMMARY_FILE}"

echo ""
echo "=== paper-figures 生成 ==="
uv run idea-graph experiment paper-figures
