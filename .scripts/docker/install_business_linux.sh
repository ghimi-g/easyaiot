#!/bin/bash

# ============================================
# EasyAIoT 业务系统统一管理脚本
# ============================================
# 管理模块: DEVICE、AI、VIDEO、WEB（不含中间件）
# 各模块实际逻辑委托给对应目录下的 install_linux.sh
#
# 用法:
#   ./install_business_linux.sh <命令> [选项] [模块...]
#
# 示例:
#   ./install_business_linux.sh install              # 安装全部业务模块
#   ./install_business_linux.sh update DEVICE WEB    # 仅更新 DEVICE 与 WEB
#   ./install_business_linux.sh -m AI,VIDEO clean    # 清理 AI 与 VIDEO
#   ./install_business_linux.sh clean-all -y         # 完全清理（含 DEVICE 镜像）
#   ./install_business_linux.sh verify               # 验证全部业务服务健康
#   ./install_business_linux.sh logs DEVICE iot-gateway
# ============================================

set -e

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck source=node/ensure_platform_agent_invoke.sh
source "${PROJECT_ROOT}/.scripts/node/ensure_platform_agent_invoke.sh"

_ensure_platform_agent_info() { print_info "$1"; }
_ensure_platform_agent_ok() { print_success "$1"; }
_ensure_platform_agent_warn() { print_warning "$1"; }

ensure_platform_agent_after_business_stack() {
    ENSURE_PLATFORM_AGENT_INFO=_ensure_platform_agent_info \
    ENSURE_PLATFORM_AGENT_OK=_ensure_platform_agent_ok \
    ENSURE_PLATFORM_AGENT_WARN=_ensure_platform_agent_warn \
    ensure_platform_agent_if_needed || true
}

# 业务模块（按依赖顺序：网关/微服务 -> AI/视频 -> 前端）
ALL_MODULES=(DEVICE AI VIDEO WEB)

declare -A MODULE_NAMES=(
    [DEVICE]="Device 服务"
    [AI]="AI 服务"
    [VIDEO]="Video 服务"
    [WEB]="Web 前端"
)

declare -A MODULE_PORTS=(
    [DEVICE]="48080"
    [AI]="5000"
    [VIDEO]="6000"
    [WEB]="8888"
)

declare -A MODULE_HEALTH_ENDPOINTS=(
    [DEVICE]="/actuator/health"
    [AI]="/actuator/health"
    [VIDEO]="/actuator/health"
    [WEB]="/health"
)

LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/install_business_$(date +%Y%m%d_%H%M%S).log"

SELECTED_MODULES=()
COMMAND=""
EXTRA_ARGS=()
AUTO_YES=false
STOP_ON_ERROR=true

log_to_file() {
    local clean
    clean=$(echo "$1" | sed -r 's/\x1B\[([0-9]{1,2}(;[0-9]{1,2})?)?[mGK]//g')
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $clean" >> "$LOG_FILE"
}

print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; log_to_file "[INFO] $1"; }
print_success() { echo -e "${GREEN}[OK]${NC} $1"; log_to_file "[OK] $1"; }
print_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; log_to_file "[WARN] $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1"; log_to_file "[ERROR] $1"; }

# 模块日志分隔
print_module_banner() {
    local module="$1"
    local cmd="$2"
    local title="${MODULE_NAMES[$module]:-$module}"
    echo ""
    echo "================================================================"
    printf " [%s] %-12s  %s\n" "$module" "$cmd" "$title"
    echo "================================================================"
    echo ""
    log_to_file ""
    log_to_file "======== $module | $cmd | $title ========"
}

print_module_end() {
    local module="$1"
    local cmd="$2"
    local status="$3"
    echo "----------------------------------------------------------------"
    if [ "$status" = "ok" ]; then
        printf " [%s] %-12s  done\n" "$module" "$cmd"
        log_to_file "-------- $module | $cmd | done --------"
    else
        printf " [%s] %-12s  failed\n" "$module" "$cmd"
        log_to_file "-------- $module | $cmd | failed --------"
    fi
    echo "----------------------------------------------------------------"
    echo ""
}

check_command() {
    command -v "$1" &>/dev/null
}

check_docker() {
    if ! check_command docker; then
        print_error "未安装 Docker"
        exit 1
    fi
    if ! docker info &>/dev/null; then
        print_error "无法连接 Docker daemon，请确认服务已启动且当前用户有权限"
        exit 1
    fi
}

check_docker_compose() {
    if check_command docker-compose; then
        return 0
    fi
    if docker compose version &>/dev/null 2>&1; then
        return 0
    fi
    print_error "未安装 Docker Compose"
    exit 1
}

create_network() {
    if docker network ls --format '{{.Name}}' | grep -qx 'easyaiot-network'; then
        print_info "网络 easyaiot-network 已存在"
        return 0
    fi
    print_info "创建网络 easyaiot-network..."
    if docker network create easyaiot-network &>/dev/null; then
        print_success "网络 easyaiot-network 已创建"
    else
        print_warning "创建网络失败或网络已存在，继续执行"
    fi
}

warn_middleware() {
    local ok=true
    if ! docker ps --format '{{.Names}}' | grep -q 'nacos-server'; then
        print_warning "未检测到 nacos-server，业务服务可能依赖中间件，请先执行: .scripts/docker/install_linux.sh install"
        ok=false
    fi
    if ! docker ps --format '{{.Names}}' | grep -q 'postgres-server'; then
        print_warning "未检测到 postgres-server"
        ok=false
    fi
    $ok
}

wait_for_service() {
    local port=$1
    local health_endpoint=$2
    local max_attempts=30
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        if [ -n "$health_endpoint" ]; then
            if curl -s --connect-timeout 2 "http://localhost:${port}${health_endpoint}" >/dev/null 2>&1; then
                return 0
            fi
        else
            if check_command nc && nc -z localhost "$port" 2>/dev/null; then
                return 0
            elif check_command timeout && timeout 1 bash -c "cat < /dev/null > /dev/tcp/localhost/$port" 2>/dev/null; then
                return 0
            elif curl -s --connect-timeout 1 "http://localhost:$port" >/dev/null 2>&1; then
                return 0
            fi
        fi
        attempt=$((attempt + 1))
        sleep 2
    done
    return 1
}

verify_module_health() {
    local module=$1
    local module_name="${MODULE_NAMES[$module]}"
    local port="${MODULE_PORTS[$module]}"
    local health_endpoint="${MODULE_HEALTH_ENDPOINTS[$module]}"

    print_module_banner "$module" "verify"
    print_info "检查 http://localhost:$port${health_endpoint} ..."

    if wait_for_service "$port" "$health_endpoint"; then
        if [ -n "$health_endpoint" ]; then
            local response
            response=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${port}${health_endpoint}" 2>/dev/null || echo "000")
            if [ "$response" = "200" ] || [ "$response" = "000" ]; then
                print_success "$module_name 运行正常"
                print_module_end "$module" "verify" "ok"
                return 0
            fi
            print_warning "$module_name 响应异常 (HTTP $response)"
            print_module_end "$module" "verify" "fail"
            return 1
        fi
        print_success "$module_name 运行正常"
        print_module_end "$module" "verify" "ok"
        return 0
    fi

    print_error "$module_name 未就绪"
    print_module_end "$module" "verify" "fail"
    return 1
}

verify_all() {
    check_docker

    local success_count=0
    local total_count=${#SELECTED_MODULES[@]}
    local failed_modules=()
    local module

    for module in "${SELECTED_MODULES[@]}"; do
        if verify_module_health "$module"; then
            success_count=$((success_count + 1))
        else
            failed_modules+=("${MODULE_NAMES[$module]}")
        fi
    done

    echo ""
    if [ "$success_count" -eq "$total_count" ]; then
        print_success "验证通过 ($success_count/$total_count)"
        return 0
    fi

    print_error "验证失败 ($success_count/$total_count)"
    local name
    for name in "${failed_modules[@]}"; do
        echo "  ✗ $name"
    done
    return 1
}

fix_line_endings() {
    local script_file="$1"
    [ -f "$script_file" ] || return 1
    if grep -q $'\r' "$script_file" 2>/dev/null; then
        sed -i 's/\r$//' "$script_file" 2>/dev/null || tr -d '\r' <"$script_file" >"${script_file}.tmp" && mv "${script_file}.tmp" "$script_file"
        chmod u+x "$script_file" 2>/dev/null || true
    fi
}

is_valid_module() {
    local m="$1"
    local x
    for x in "${ALL_MODULES[@]}"; do
        [ "$x" = "$m" ] && return 0
    done
    return 1
}

normalize_module_name() {
    echo "$1" | tr '[:lower:]' '[:upper:]'
}

resolve_modules() {
    local tokens=("$@")
    local resolved=()
    local t norm

    if [ ${#tokens[@]} -eq 0 ]; then
        SELECTED_MODULES=("${ALL_MODULES[@]}")
        return 0
    fi

    for t in "${tokens[@]}"; do
        norm=$(normalize_module_name "$t")
        if ! is_valid_module "$norm"; then
            print_error "未知模块: $t（可选: ${ALL_MODULES[*]}）"
            exit 1
        fi
        resolved+=("$norm")
    done

    SELECTED_MODULES=()
    local mod
    for mod in "${ALL_MODULES[@]}"; do
        for t in "${resolved[@]}"; do
            if [ "$mod" = "$t" ]; then
                SELECTED_MODULES+=("$mod")
                break
            fi
        done
    done
}

reverse_modules() {
    local reversed=()
    local i
    for ((i=${#SELECTED_MODULES[@]}-1; i>=0; i--)); do
        reversed+=("${SELECTED_MODULES[i]}")
    done
    SELECTED_MODULES=("${reversed[@]}")
}

map_module_command() {
    local module="$1"
    local cmd="$2"

    case "$cmd" in
        clean-all)
            if [ "$module" = "DEVICE" ]; then
                echo "clean-all"
            else
                echo "clean"
            fi
            ;;
        build-base)
            if [ "$module" = "DEVICE" ]; then
                echo "build-base"
            else
                echo ""
            fi
            ;;
        *)
            echo "$cmd"
            ;;
    esac
}

execute_module() {
    local module="$1"
    local cmd="$2"
    shift 2
    local mapped
    local module_dir="$PROJECT_ROOT/$module"
    local install_script="$module_dir/install_linux.sh"

    mapped=$(map_module_command "$module" "$cmd")
    [ -n "$mapped" ] || return 0

    if [ ! -d "$module_dir" ]; then
        print_warning "目录不存在，跳过: $module"
        return 1
    fi

    if [ ! -f "$install_script" ]; then
        print_warning "未找到 $install_script，跳过 $module"
        return 1
    fi

    fix_line_endings "$install_script"

    print_module_banner "$module" "$mapped"
    (
        cd "$module_dir"
        export EASYAIOT_AUTO_YES="${EASYAIOT_AUTO_YES:-0}"
        export EASYAIOT_DEFER_PLATFORM_AGENT_SYNC=1
        bash install_linux.sh "$mapped" "$@"
    ) 2>&1 | tee -a "$LOG_FILE"

    local exit_code=${PIPESTATUS[0]}
    if [ "$exit_code" -ne 0 ]; then
        print_module_end "$module" "$mapped" "fail"
        print_error "$module 失败 (exit $exit_code)"
        return "$exit_code"
    fi
    print_module_end "$module" "$mapped" "ok"
    return 0
}

run_on_modules() {
    local cmd="$1"
    shift
    local module mapped_cmd
    local failed=()
    local need_network=false

    case "$cmd" in
        install|start|restart|update|build|build-base)
            need_network=true
            ;;
    esac

    check_docker
    check_docker_compose

    if $need_network; then
        create_network
    fi

    if [[ "$cmd" == install || "$cmd" == start || "$cmd" == update ]]; then
        warn_middleware || true
    fi

    for module in "${SELECTED_MODULES[@]}"; do
        mapped_cmd=$(map_module_command "$module" "$cmd")
        if [ -z "$mapped_cmd" ]; then
            continue
        fi
        if execute_module "$module" "$mapped_cmd" "$@"; then
            :
        else
            failed+=("$module")
            if $STOP_ON_ERROR; then
                break
            fi
        fi
    done

    if [ ${#failed[@]} -gt 0 ]; then
        print_error "失败模块: ${failed[*]}"
        return 1
    fi

    case "$cmd" in
        install|start|restart|update)
            ensure_platform_agent_after_business_stack
            ;;
    esac
    return 0
}

is_yes() {
    case "$(echo "$1" | tr '[:upper:]' '[:lower:]')" in
        y|yes) return 0 ;;
        *) return 1 ;;
    esac
}

is_no() {
    case "$(echo "$1" | tr '[:upper:]' '[:lower:]')" in
        n|no|'') return 0 ;;
        *) return 1 ;;
    esac
}

confirm_once() {
    $AUTO_YES && return 0
    local response
    while true; do
        read -r -p "确认继续? [y/n] " response
        if is_yes "$response"; then
            return 0
        fi
        if is_no "$response"; then
            print_info "已取消"
            return 1
        fi
        echo "请输入 y/yes 或 n/no"
    done
}

usage() {
    cat <<EOF
EasyAIoT 业务系统统一管理脚本

管理模块: DEVICE、AI、VIDEO、WEB（不含 Nacos/PostgreSQL 等中间件）

用法:
  $0 <命令> [选项] [模块...]

命令:
  install       安装并启动（首次部署）
  start         启动服务
  stop          停止服务（逆序）
  restart       重启服务
  status        查看状态
  logs [服务名] 查看日志（可指定模块后接服务名，如 logs DEVICE iot-gateway）
  build         重新构建镜像
  build-base    仅 DEVICE：Maven 编译并提取 Jar（第一阶段）
  clean         清理容器（DEVICE 保留镜像）
  clean-all     完全清理（DEVICE 含镜像；其他模块等同 clean）
  update        重新构建并重启
  verify        验证服务健康（HTTP 健康检查 / 端口探测）
  help          显示帮助

选项:
  -m, --modules <列表>   逗号分隔模块，如 DEVICE,WEB
  -y, --yes              清理操作无需确认
  --continue-on-error    某模块失败后继续执行其余模块

模块:
  未指定时默认全部，顺序为 DEVICE -> AI -> VIDEO -> WEB
  stop / clean / clean-all 时自动逆序执行

示例:
  $0 install
  $0 update WEB
  $0 verify
  $0 verify DEVICE WEB
  $0 -m DEVICE,AI status
  $0 clean-all -y
  $0 logs VIDEO

说明:
  中间件请使用 .scripts/docker/install_linux.sh 或 install_middleware_linux.sh
  日志: $LOG_DIR/
EOF
}

parse_args() {
    local positional=()
    local arg

    while [ $# -gt 0 ]; do
        arg="$1"
        case "$arg" in
            -h|--help|help)
                COMMAND="help"
                shift
                ;;
            -y|--yes)
                AUTO_YES=true
                shift
                ;;
            --continue-on-error)
                STOP_ON_ERROR=false
                shift
                ;;
            -m|--modules)
                [ -n "${2:-}" ] || { print_error "-m 需要模块列表"; exit 1; }
                IFS=',' read -r -a _mods <<<"$2"
                positional+=("${_mods[@]}")
                shift 2
                ;;
            install|start|stop|restart|status|logs|build|build-base|clean|clean-all|update|verify)
                COMMAND="$arg"
                shift
                ;;
            -*)
                print_error "未知选项: $arg"
                usage
                exit 1
                ;;
            *)
                positional+=("$arg")
                shift
                ;;
        esac
    done

    if [ -z "$COMMAND" ]; then
        COMMAND="help"
        return 0
    fi

    if [ "$COMMAND" = "help" ]; then
        return 0
    fi

    if [ "$COMMAND" = "logs" ] && [ ${#positional[@]} -gt 0 ]; then
        local first
        first=$(normalize_module_name "${positional[0]}")
        if is_valid_module "$first"; then
            resolve_modules "$first"
            EXTRA_ARGS=("${positional[@]:1}")
            return 0
        fi
    fi

    resolve_modules "${positional[@]}"
}

main() {
    echo "=========================================" >>"$LOG_FILE"
    echo "install_business_linux.sh $*" >>"$LOG_FILE"
    echo "开始: $(date '+%Y-%m-%d %H:%M:%S')" >>"$LOG_FILE"
    echo "=========================================" >>"$LOG_FILE"

    parse_args "$@"

    case "$COMMAND" in
        help|"")
            usage
            ;;
        verify)
            verify_all || exit 1
            ;;
        install|start|restart|update|build|build-base|status)
            run_on_modules "$COMMAND" "${EXTRA_ARGS[@]}" || exit 1
            ;;
        stop|clean|clean-all)
            if [[ "$COMMAND" == clean* ]]; then
                confirm_once || exit 0
                export EASYAIOT_AUTO_YES=1
            fi
            reverse_modules
            run_on_modules "$COMMAND" "${EXTRA_ARGS[@]}" || exit 1
            ;;
        logs)
            run_on_modules "logs" "${EXTRA_ARGS[@]}" || exit 1
            ;;
        *)
            print_error "未知命令: $COMMAND"
            usage
            exit 1
            ;;
    esac
}

main "$@"
