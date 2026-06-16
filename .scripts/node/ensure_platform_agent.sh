#!/usr/bin/env bash
# 手动在宿主机启动控制面 Node Agent（与 iot-node 启动解耦，需运维主动执行）
#
# 用法:
#   bash .scripts/node/ensure_platform_agent.sh
#
# 凭据来源（按优先级）:
#   1. 环境变量 NODE_ID / AGENT_TOKEN（显式指定）
#   2. Gateway bootstrap 接口（需 iot-node 已运行，容器重建后自动同步新令牌）
#   3. 工作目录下已有 agent.env（bootstrap 不可用时回退）
#
# 环境变量:
#   EASYAIOT_GATEWAY_URL          Gateway 地址，默认 http://127.0.0.1:48080
#   EASYAIOT_AGENT_CONTROL_PLANE_URL  Agent 上报地址（可选，默认由 Gateway 推导）
#   EASYAIOT_AGENT_LOCAL_INSTALL_DIR  安装目录，默认 /opt/easyaiot/node-agent
#   EASYAIOT_AGENT_SOURCE_PATH        源码目录，默认 <repo>/NODE
#   EASYAIOT_AGENT_PORT               监听端口，默认 9100
#   EASYAIOT_AGENT_LOCAL_PYTHON       Python 命令，默认 python3
#   AGENT_USE_CACHED_ENV=1          跳过 bootstrap，仅使用本地 agent.env（离线环境）
#   AGENT_BOOTSTRAP_WAIT_SECONDS=180  install 场景等待 bootstrap 就绪的最长秒数
#   AGENT_BOOTSTRAP_RETRY_INTERVAL=3  轮询间隔（秒）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GATEWAY_URL="${EASYAIOT_GATEWAY_URL:-http://127.0.0.1:48080}"
INSTALL_DIR="${EASYAIOT_AGENT_LOCAL_INSTALL_DIR:-/opt/easyaiot/node-agent}"
SOURCE_DIR="${EASYAIOT_AGENT_SOURCE_PATH:-$ROOT/NODE}"
AGENT_PORT="${EASYAIOT_AGENT_PORT:-9100}"
PYTHON="${EASYAIOT_AGENT_LOCAL_PYTHON:-python3}"
AGENT_BOOTSTRAP_WAIT_SECONDS="${AGENT_BOOTSTRAP_WAIT_SECONDS:-180}"
AGENT_BOOTSTRAP_RETRY_INTERVAL="${AGENT_BOOTSTRAP_RETRY_INTERVAL:-3}"

is_port_listening() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn | grep -q ":${port} "
    return $?
  fi
  if command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "$port" >/dev/null 2>&1
    return $?
  fi
  return 1
}

resolve_work_dir() {
  if [[ -f "$INSTALL_DIR/run_agent.py" ]]; then
    echo "$INSTALL_DIR"
    return 0
  fi
  if [[ -f "$SOURCE_DIR/run_agent.py" ]]; then
    echo "$SOURCE_DIR"
    return 0
  fi
  return 1
}

read_env_credentials() {
  local env_file="$1"
  [[ -f "$env_file" ]] || return 1
  local node_id="" agent_token="" port=""
  # shellcheck disable=SC1090
  set -a
  source "$env_file"
  set +a
  node_id="${NODE_ID:-}"
  agent_token="${AGENT_TOKEN:-}"
  port="${AGENT_LISTEN_PORT:-$AGENT_PORT}"
  if [[ -n "$node_id" && -n "$agent_token" ]]; then
    echo "${node_id}|${agent_token}|${port}"
    return 0
  fi
  return 1
}

fetch_platform_node_credentials() {
  curl -fsS \
    "${GATEWAY_URL}/admin-api/node/platform-agent-bootstrap" 2>/dev/null \
    | PYTHONPATH= python3 -c "
import json, sys
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception:
    sys.exit(1)
payload = data.get('data') or data
node_id = payload.get('nodeId') or payload.get('id')
token = payload.get('agentToken')
port = payload.get('agentPort') or 9100
if node_id and token:
    print(node_id, token, port, sep='|')
" 2>/dev/null || true
}

write_agent_env() {
  local work_dir="$1" node_id="$2" agent_token="$3" port="$4"
  local cp_url="${EASYAIOT_AGENT_CONTROL_PLANE_URL:-${GATEWAY_URL%/}/admin-api/node/agent}"
  cat >"${work_dir}/agent.env" <<EOF
NODE_ID=${node_id}
AGENT_TOKEN=${agent_token}
CONTROL_PLANE_URL=${cp_url}
HEARTBEAT_INTERVAL=10
AGENT_LISTEN_HOST=0.0.0.0
AGENT_LISTEN_PORT=${port}
AI_ROOT=/opt/easyaiot/AI
VIDEO_ROOT=/opt/easyaiot/VIDEO
MEDIA_CLUSTER_ROOT=/opt/easyaiot/media-cluster
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=your-secret
EOF
}

fetch_platform_node_credentials_with_wait() {
  if [[ -n "${NODE_ID:-}" && -n "${AGENT_TOKEN:-}" ]]; then
    return 1
  fi
  if [[ "${AGENT_USE_CACHED_ENV:-}" == "1" ]]; then
    return 1
  fi

  local deadline=$((SECONDS + AGENT_BOOTSTRAP_WAIT_SECONDS))
  local creds=""
  echo "[platform-agent] 等待 bootstrap 就绪（最长 ${AGENT_BOOTSTRAP_WAIT_SECONDS}s）..." >&2
  while [[ $SECONDS -lt $deadline ]]; do
    creds="$(fetch_platform_node_credentials)"
    if [[ -n "$creds" ]]; then
      echo "$creds"
      return 0
    fi
    sleep "$AGENT_BOOTSTRAP_RETRY_INTERVAL"
  done
  echo "[platform-agent] bootstrap 超时，将尝试使用本地 agent.env" >&2
  return 1
}

resolve_credentials() {
  local work_dir="$1"
  local creds=""

  if [[ -n "${NODE_ID:-}" && -n "${AGENT_TOKEN:-}" ]]; then
    echo "${NODE_ID}|${AGENT_TOKEN}|${AGENT_LISTEN_PORT:-$AGENT_PORT}"
    return 0
  fi

  if [[ "${AGENT_USE_CACHED_ENV:-}" != "1" ]]; then
    creds="$(fetch_platform_node_credentials_with_wait || true)"
    if [[ -z "$creds" ]]; then
      creds="$(fetch_platform_node_credentials)"
    fi
    if [[ -n "$creds" ]]; then
      local cached=""
      cached="$(read_env_credentials "${work_dir}/agent.env" 2>/dev/null || true)"
      if [[ -n "$cached" && "$cached" != "$creds" ]]; then
        local cached_id cached_token boot_id boot_token
        IFS='|' read -r cached_id cached_token _ <<<"$cached"
        IFS='|' read -r boot_id boot_token _ <<<"$creds"
        if [[ "$cached_id" != "$boot_id" || "$cached_token" != "$boot_token" ]]; then
          echo "[platform-agent] 本地 agent.env 与平台不一致，已从 bootstrap 同步 (nodeId=${boot_id})" >&2
        fi
      fi
      echo "$creds"
      return 0
    fi
  fi

  creds="$(read_env_credentials "${work_dir}/agent.env" 2>/dev/null || true)"
  if [[ -n "$creds" ]]; then
    echo "$creds"
    return 0
  fi
  return 1
}

stop_running_agent() {
  if [[ -f /etc/systemd/system/easyaiot-node-agent.service ]]; then
    if systemctl is-active easyaiot-node-agent >/dev/null 2>&1; then
      sudo systemctl stop easyaiot-node-agent 2>/dev/null || true
    fi
    return 0
  fi
  if command -v fuser >/dev/null 2>&1; then
    sudo fuser -k "${AGENT_PORT}/tcp" >/dev/null 2>&1 || true
  elif command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -ti tcp:"${AGENT_PORT}" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      kill $pids 2>/dev/null || true
      sleep 1
    fi
  fi
}

restart_agent_service() {
  local work_dir="$1"
  stop_running_agent
  if [[ -f /etc/systemd/system/easyaiot-node-agent.service ]]; then
    if [[ -x "${INSTALL_DIR}/install.sh" ]]; then
      sudo bash "${INSTALL_DIR}/install.sh" restart
    else
      sudo systemctl daemon-reload
      sudo systemctl enable easyaiot-node-agent >/dev/null 2>&1 || true
      sudo systemctl restart easyaiot-node-agent
    fi
    echo "[platform-agent] 已通过 systemd 重启 easyaiot-node-agent"
    return 0
  fi

  mkdir -p "${HOME}/logs"
  if [[ -x "${work_dir}/agent-python.sh" ]]; then
    nohup "${work_dir}/agent-python.sh" >>"${HOME}/logs/platform-node-agent.log" 2>&1 &
  else
    set -a
    # shellcheck source=/dev/null
    source "${work_dir}/agent.env"
    set +a
    nohup "$PYTHON" "${work_dir}/run_agent.py" >>"${HOME}/logs/platform-node-agent.log" 2>&1 &
  fi
  echo "[platform-agent] 已后台启动 Agent，日志: ${HOME}/logs/platform-node-agent.log"
}

main() {
  local work_dir
  work_dir="$(resolve_work_dir)" || {
    echo "[platform-agent] 未找到 Agent 目录（${INSTALL_DIR} 或 ${SOURCE_DIR}）" >&2
    echo "[platform-agent] 请先执行 NODE/install.sh 或指定 EASYAIOT_AGENT_SOURCE_PATH" >&2
    exit 1
  }

  local creds node_id agent_token port
  creds="$(resolve_credentials "$work_dir")" || {
    echo "[platform-agent] 缺少 NODE_ID / AGENT_TOKEN" >&2
    echo "[platform-agent] 请编辑 ${work_dir}/agent.env，或确保 Gateway 可访问 bootstrap 接口" >&2
    exit 1
  }
  IFS='|' read -r node_id agent_token port <<<"$creds"

  local cached="" creds_changed=0
  cached="$(read_env_credentials "${work_dir}/agent.env" 2>/dev/null || true)"
  if [[ -n "$cached" ]]; then
    local cached_id cached_token
    IFS='|' read -r cached_id cached_token _ <<<"$cached"
    if [[ "$cached_id" != "$node_id" || "$cached_token" != "$agent_token" ]]; then
      creds_changed=1
    fi
  else
    creds_changed=1
  fi

  if is_port_listening "$AGENT_PORT" && [[ "$creds_changed" -eq 0 ]]; then
    echo "[platform-agent] 端口 ${AGENT_PORT} 已有 Agent 监听且凭据一致，跳过"
    exit 0
  fi

  if is_port_listening "$AGENT_PORT" && [[ "$creds_changed" -eq 1 ]]; then
    echo "[platform-agent] 检测到凭据变更，重启 Agent (nodeId=${node_id})"
  fi

  write_agent_env "$work_dir" "$node_id" "$agent_token" "${port:-$AGENT_PORT}"
  echo "[platform-agent] 已写入 ${work_dir}/agent.env (nodeId=${node_id})"

  restart_agent_service "$work_dir"
}

main "$@"
