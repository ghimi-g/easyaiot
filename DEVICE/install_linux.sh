#!/bin/bash

# DEVICE模块 Docker Compose 管理脚本
# 两阶段构建：docker run 卷挂载 Maven 编译（增量）→ target/jars → 各模块运行时 Dockerfile

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EASYAIOT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=../.scripts/docker/init-build-cache-dirs.sh
source "${EASYAIOT_ROOT}/.scripts/docker/init-build-cache-dirs.sh"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"

# 检查docker-compose是否存在
if ! command -v docker-compose &> /dev/null && ! command -v docker &> /dev/null; then
    echo -e "${RED}错误: 未找到docker或docker-compose命令${NC}"
    exit 1
fi

# 使用docker compose（新版本）或docker-compose（旧版本）
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
elif docker-compose version &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
else
    echo -e "${RED}错误: 未找到docker compose或docker-compose命令${NC}"
    exit 1
fi

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# compose 文件中定义的服务数量（用于启动前提示）
compose_service_count() {
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" config --services 2>/dev/null | wc -l | tr -d '[:space:]'
}

# 清理 compose recreate 被中断后遗留的「改名孤儿容器」（形如 <12位hex>_iot-xxx）。
# recreate 时 compose 先把旧容器改名让出 container_name，再建新容器；中途被打断旧容器就残留。
# 它的服务标签仍指向 compose 文件里的服务，下次 up 会把它当正主、等它的健康检查——
# 旧配置旧镜像极易 unhealthy，卡死 depends_on(service_healthy) 整条依赖链；
# 注意 --remove-orphans 清不掉它（只清「服务已从 compose 文件移除」的孤儿），必须主动删除。
cleanup_renamed_containers() {
    local names
    names=$(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -E '^[0-9a-f]{12}_iot-' || true)
    [ -z "$names" ] && return 0
    print_warning "清理上次中断遗留的改名孤儿容器: $(echo "$names" | tr '\n' ' ')"
    echo "$names" | xargs -r docker rm -f >/dev/null 2>&1 || true
}

# up 前重启本项目 unhealthy 的容器。
# 典型场景：业务容器在依赖（如 Nacos 账号、中间件）修复【之前】启动，nacos 客户端重试一段时间后
# 放弃，应用进入僵死态（不再重试、永远 unhealthy）；而 up -d 不会动"配置未变的运行中容器"，
# 于是 depends_on(service_healthy) 无论重试多少次 update 都卡死。重启让应用带着已修复的依赖重新初始化。
restart_unhealthy_containers() {
    local names n
    names=$(docker ps --filter "health=unhealthy" --format '{{.Names}}' 2>/dev/null | grep -E '^iot-' || true)
    [ -z "$names" ] && return 0
    for n in $names; do
        print_warning "容器 $n 处于 unhealthy，自动重启以重新连接依赖..."
        docker restart "$n" >/dev/null 2>&1 || true
    done
}

# 后台启动 compose 服务。
# TTY 下 compose 会用 \r 刷新 [+] up x/y，分母残留时易显示成 9/100（实际共 10 个服务）。
compose_up_detached() {
    local count
    count=$(compose_service_count)
    if [ -n "$count" ] && [ "$count" -gt 0 ] 2>/dev/null; then
        print_info "正在启动服务（共 ${count} 个）..."
    else
        print_info "正在启动服务..."
    fi
    cleanup_renamed_containers
    restart_unhealthy_containers
    # --remove-orphans：顺带清理「已从 compose 文件移除的服务」的残留容器
    COMPOSE_ANSI=never $DOCKER_COMPOSE -f "$COMPOSE_FILE" up -d --no-color --remove-orphans "$@"
}

# up 失败时自动展示 unhealthy 容器及其日志尾部，免去手动逐个排查
show_unhealthy_containers() {
    local names n
    names=$(docker ps --filter "health=unhealthy" --format '{{.Names}}' 2>/dev/null | grep -i "iot" || true)
    [ -z "$names" ] && return 0
    for n in $names; do
        print_warning "unhealthy 容器: $n，日志尾部："
        docker logs --tail 30 "$n" 2>&1 | tail -30 || true
        echo ""
    done
}

# 检查docker-compose.yml是否存在
check_compose_file() {
    if [ ! -f "$COMPOSE_FILE" ]; then
        print_error "docker-compose.yml文件不存在: $COMPOSE_FILE"
        exit 1
    fi
    
    # 验证文件是否可读
    if [ ! -r "$COMPOSE_FILE" ]; then
        print_error "docker-compose.yml 文件不可读: $COMPOSE_FILE"
        exit 1
    fi
}

# 检查 Docker daemon 是否运行
check_docker_daemon() {
    if ! docker info > /dev/null 2>&1; then
        print_error "Docker daemon 未运行，请先启动 Docker 服务"
        print_info "尝试启动: sudo systemctl start docker"
        exit 1
    fi
}

JARS_DIR="${SCRIPT_DIR}/target/jars"
MAVEN_CACHE_DIR="$(maven_repository_dir "$EASYAIOT_ROOT")"
# 构建输入哈希戳（纯文件内容哈希，不依赖 git）：update/build 时输入未变则跳过 Maven 编译
BUILD_STAMP_FILE="$(module_cache_root "$EASYAIOT_ROOT" device)/.build-stamp"
# 各运行时镜像产物哈希戳目录：按「Jar 内容 + 该模块 Dockerfile」判断单个镜像是否需要重建（依赖可复现构建）
RUNTIME_STAMP_DIR="$(module_cache_root "$EASYAIOT_ROOT" device)/runtime-stamps"
# 各 Maven 模块源码哈希戳目录：按「模块 pom.xml + src/」判断改了哪些模块，供选择性 reactor 构建（-pl）
MODULE_HASH_DIR="$(module_cache_root "$EASYAIOT_ROOT" device)/module-hashes"
# 宿主机 Maven settings.xml（docker run 卷挂载编译用，aliyun mirror）；首次自动生成
MAVEN_SETTINGS_FILE="$(module_cache_root "$EASYAIOT_ROOT" device)/settings.xml"
# C2（常驻 mvnd 容器，守护进程复用）：默认关闭走 C1 一次性 docker run；USE_MVND=1 启用，不可用时自动回退 C1
USE_MVND="${USE_MVND:-0}"
MVND_IMAGE="${MVND_IMAGE:-device-mvnd:latest}"
MVND_CONTAINER="${MVND_CONTAINER:-device-mvnd-builder}"
MVND_VERSION="${MVND_VERSION:-1.0.6}"
# mvnd 镜像的 glibc 基础镜像：默认复用运行时已在用、服务器必可拉取的 liberica（避免 docker.io 拉取失败）
MVND_BASE_IMAGE="${MVND_BASE_IMAGE:-bellsoft/liberica-openjdk-debian:21.0.8}"
# mvnd daemon 空闲多久自动退出（释放约 1–2GB 内存，容器仍保留，下次用自动重生）。
# 活跃连续构建时 daemon 一直热；停手超过该时长则自动回收内存。值须每次一致（否则起新 daemon）。
MVND_IDLE_TIMEOUT="${MVND_IDLE_TIMEOUT:-30m}"

# 运行时镜像：dockerfile 路径 | 镜像 tag
RUNTIME_IMAGE_SPECS=(
    "iot-gateway/Dockerfile|iot-gateway:latest"
    "iot-system/iot-system-biz/Dockerfile|iot-module-system-biz:latest"
    "iot-infra/iot-infra-biz/Dockerfile|iot-module-infra-biz:latest"
    "iot-device/iot-device-biz/Dockerfile|iot-module-device-biz:latest"
    "iot-dataset/iot-dataset-biz/Dockerfile|iot-module-dataset-biz:latest"
    "iot-node/iot-node-biz/Dockerfile|iot-module-node-biz:latest"
    "iot-tdengine/iot-tdengine-biz/Dockerfile|iot-module-tdengine-biz:latest"
    "iot-file/iot-file-biz/Dockerfile|iot-module-file-biz:latest"
    "iot-message/iot-message-biz/Dockerfile|iot-module-message-biz:latest"
    "iot-sink/iot-sink-biz/Dockerfile|iot-sink-biz:latest"
    "iot-gb28181/iot-gb28181-biz/Dockerfile|iot-gb28181-biz:latest"
)

# 与 RUNTIME_IMAGE_SPECS 中 COPY 的 Jar 一一对应
REQUIRED_RUNTIME_JARS=(
    iot-gateway.jar
    iot-system-biz.jar
    iot-infra-biz.jar
    iot-device-biz.jar
    iot-dataset-biz.jar
    iot-node-biz.jar
    iot-tdengine-biz.jar
    iot-file-biz.jar
    iot-message-biz.jar
    iot-sink-biz.jar
    iot-gb28181-biz.jar
)

check_jars_exist() {
    if [ ! -d "$JARS_DIR" ]; then
        return 1
    fi
    find "$JARS_DIR" -maxdepth 1 -name "*.jar" -type f 2>/dev/null | grep -q .
}

# 第二阶段构建前检查，避免 Docker 日志里出现误导性的「错误: xxx.jar 不存在」RUN 步骤
verify_runtime_jars() {
    local missing=()
    local jar
    for jar in "${REQUIRED_RUNTIME_JARS[@]}"; do
        if [ ! -f "${JARS_DIR}/${jar}" ]; then
            missing+=("$jar")
        fi
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        print_error "缺少运行时 Jar（共 ${#missing[@]} 个）: ${missing[*]}"
        print_info "请先执行: ./install_linux.sh build-base"
        exit 1
    fi
}

# 选择可用的内容哈希命令（优先 sha256sum，其次 shasum，最后 md5sum）
build_hasher() {
    if command -v sha256sum >/dev/null 2>&1; then
        echo "sha256sum"
    elif command -v shasum >/dev/null 2>&1; then
        echo "shasum -a 256"
    else
        echo "md5sum"
    fi
}

# 解析一次哈希命令并缓存，供各哈希函数复用（避免每次 command -v + 子进程）
HASHER="$(build_hasher)"

# 计算影响 Jar 产物的构建输入哈希：各模块 src + 各级 pom.xml + lombok.config + Dockerfile(.base)。
# 纯文件内容哈希（不依赖 git）：update/build 时若哈希与上次成功构建一致，则整段 Maven 编译可跳过。
hash_build_inputs() {
    {
        find "$SCRIPT_DIR" \
            -type d \( -name target -o -name .git \) -prune -o \
            -type f \( -path "*/src/*" -o -name "pom.xml" -o -name "lombok.config" \
                       -o -name "Dockerfile" -o -name "Dockerfile.base" \) -print0 2>/dev/null \
        | LC_ALL=C sort -z \
        | xargs -0 $HASHER 2>/dev/null
    } | $HASHER | awk '{print $1}'
}

# 单个运行时镜像的产物哈希：该模块 Jar 内容 + 其 Dockerfile 内容。
# 依赖可复现构建（根 pom.xml project.build.outputTimestamp）：源码未变 → Jar 字节一致 → 哈希一致 → 跳过重建。
hash_runtime_image() {
    local jar="$1" dockerfile="$2"
    { $HASHER "$jar" "$dockerfile" 2>/dev/null; } | $HASHER | awk '{print $1}'
}

# 某运行时镜像 tag 对应的哈希戳文件路径（tag 中的 / 与 : 替换为 _）
runtime_stamp_file() {
    mkdir -p "$RUNTIME_STAMP_DIR" 2>/dev/null || true
    echo "${RUNTIME_STAMP_DIR}/$(echo "$1" | tr '/:' '__')"
}

# ===== 模块级变更检测（供选择性 reactor 构建 -pl 使用）=====

# 列出所有含 pom.xml 的 Maven 模块目录（相对 SCRIPT_DIR，可直接用于 mvn -pl），排除 target；根模块输出为 "."
enumerate_maven_modules() {
    local pom dir rel
    find "$SCRIPT_DIR" -type d -name target -prune -o -name pom.xml -type f -print 2>/dev/null \
    | while IFS= read -r pom; do
        dir="$(dirname "$pom")"
        rel="${dir#"$SCRIPT_DIR"}"
        rel="${rel#/}"
        [ -z "$rel" ] && rel="."
        printf '%s\n' "$rel"
    done
}

# 计算单个模块的源码哈希：该模块自身 pom.xml + src/ 下所有文件（仅内容，路径无关；子模块各自独立目录不重复计入）
hash_one_module() {
    local rel="$1" base
    if [ "$rel" = "." ]; then base="$SCRIPT_DIR"; else base="$SCRIPT_DIR/$rel"; fi
    {
        [ -f "$base/pom.xml" ] && $HASHER "$base/pom.xml" 2>/dev/null
        if [ -d "$base/src" ]; then
            find "$base/src" -type f -print0 2>/dev/null | LC_ALL=C sort -z | xargs -0 $HASHER 2>/dev/null
        fi
    } | awk '{print $1}' | $HASHER | awk '{print $1}'
}

# 某模块哈希戳文件路径（相对路径中的 / . : 替换为 _）
module_hash_stamp_file() {
    mkdir -p "$MODULE_HASH_DIR" 2>/dev/null || true
    echo "${MODULE_HASH_DIR}/$(echo "$1" | tr '/.:' '___')"
}

# 本轮模块哈希暂存路径（#5：compute 写入、store 复用，避免构建后重复遍历源码树）
module_stage_file() {
    echo "${MODULE_HASH_DIR}/.staging/$(echo "$1" | tr '/.:' '___')"
}

# 全局构建输入哈希：根 pom.xml + iot-parent/pom.xml + lombok.config（任一变化影响所有模块编译 → 触发全量）
hash_global_inputs() {
    {
        [ -f "$SCRIPT_DIR/pom.xml" ] && $HASHER "$SCRIPT_DIR/pom.xml" 2>/dev/null
        [ -f "$SCRIPT_DIR/iot-parent/pom.xml" ] && $HASHER "$SCRIPT_DIR/iot-parent/pom.xml" 2>/dev/null
        [ -f "$SCRIPT_DIR/lombok.config" ] && $HASHER "$SCRIPT_DIR/lombok.config" 2>/dev/null
    } | awk '{print $1}' | $HASHER | awk '{print $1}'
}

# 输出哈希变化（或无戳）的模块相对路径列表；根 "." 由全局文件判定单独处理，此处跳过。
# 同时把本轮每个模块（含 "."）的哈希写入暂存区，供构建成功后 store_module_hashes 直接复用（#5）。
compute_changed_modules() {
    local rel cur stored stampf stagef
    mkdir -p "${MODULE_HASH_DIR}/.staging" 2>/dev/null || true
    while IFS= read -r rel; do
        cur="$(hash_one_module "$rel")"
        stagef="$(module_stage_file "$rel")"
        printf '%s\n' "$cur" > "$stagef" 2>/dev/null || true
        [ "$rel" = "." ] && continue
        stampf="$(module_hash_stamp_file "$rel")"
        stored=""
        [ -f "$stampf" ] && stored="$(cat "$stampf" 2>/dev/null || true)"
        if [ -z "$cur" ] || [ "$cur" != "$stored" ]; then
            printf '%s\n' "$rel"
        fi
    done < <(enumerate_maven_modules)
}

# 构建成功后写回所有模块当前哈希，使下次比对准确。
# #5：若本轮 compute_changed_modules 已把哈希写入暂存区（选择性构建路径），直接复用，避免再遍历源码树；
#     全量构建路径未经 compute（无暂存）→ 现算。
store_module_hashes() {
    local rel cur stampf stagef
    mkdir -p "$MODULE_HASH_DIR" 2>/dev/null || true
    while IFS= read -r rel; do
        stagef="$(module_stage_file "$rel")"
        if [ -f "$stagef" ]; then
            cur="$(cat "$stagef" 2>/dev/null || true)"
        else
            cur="$(hash_one_module "$rel")"
        fi
        stampf="$(module_hash_stamp_file "$rel")"
        [ -n "$cur" ] && printf '%s\n' "$cur" > "$stampf" 2>/dev/null || true
    done < <(enumerate_maven_modules)
    # 同时记录全局输入哈希（根/父 pom + lombok.config），供决策块判定是否需全量构建
    printf '%s\n' "$(hash_global_inputs)" > "${MODULE_HASH_DIR}/.global-inputs" 2>/dev/null || true
}

# 确保宿主机 Maven settings.xml 存在（aliyun mirror）；docker run 卷挂载编译时以 -s 引用
ensure_maven_settings() {
    local s="$1"
    [ -f "$s" ] && return 0
    mkdir -p "$(dirname "$s")" 2>/dev/null || true
    cat > "$s" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0 http://maven.apache.org/xsd/settings-1.0.0.xsd">
  <mirrors>
    <mirror>
      <id>aliyun-all</id>
      <mirrorOf>central,huaweicloud,aliyunmaven,aliyun-plugin</mirrorOf>
      <name>Aliyun Maven</name>
      <url>https://maven.aliyun.com/repository/public</url>
    </mirror>
  </mirrors>
  <interactiveMode>false</interactiveMode>
</settings>
EOF
}

# 从宿主机各模块 target/ 收集运行时 Jar 到 JARS_DIR（复刻原 Dockerfile.base 容器内提取逻辑）。
# 必须强制覆盖（cp -f，绝不能用 cp -u）：可复现构建把 Jar 文件 mtime 钉死为
# outputTimestamp(2026-01-01)，而目标副本 mtime 为复制时刻（较新）；cp -u 会判定"源更旧"
# 而永久跳过，导致重编的新 Jar 进不来、运行时镜像一直用旧 Jar（陈旧 → 容器行为不更新）。
collect_runtime_jars() {
    mkdir -p "$JARS_DIR"
    [ -f "$SCRIPT_DIR/iot-gateway/target/iot-gateway.jar" ] && \
        cp -f "$SCRIPT_DIR/iot-gateway/target/iot-gateway.jar" "$JARS_DIR/iot-gateway.jar"
    local biz jar
    while IFS= read -r biz; do
        jar=$(find "$biz/target" -maxdepth 1 -name "*-biz.jar" \
            ! -name "*-sources.jar" ! -name "*-javadoc.jar" ! -name "*.original" -type f 2>/dev/null | head -1)
        [ -n "$jar" ] && [ -f "$jar" ] && cp -f "$jar" "$JARS_DIR/$(basename "$jar")"
    done < <(find "$SCRIPT_DIR"/iot-* -type d -name "*-biz" 2>/dev/null)
}

# ===== C2：常驻 mvnd builder 容器（守护进程复用）=====

# 确保 mvnd 镜像存在（不存在则自建，从清华源下载 mvnd）。失败返回非 0 → 调用方回退 C1。
ensure_mvnd_image() {
    if docker image inspect "$MVND_IMAGE" >/dev/null 2>&1; then
        return 0
    fi
    print_info "首次构建 mvnd 镜像 $MVND_IMAGE（mvnd $MVND_VERSION，清华源）..."
    docker build -f "${SCRIPT_DIR}/Dockerfile.mvnd" \
        --build-arg "MVND_BASE_IMAGE=${MVND_BASE_IMAGE}" \
        --build-arg "MVND_VERSION=${MVND_VERSION}" \
        -t "$MVND_IMAGE" "$SCRIPT_DIR"
}

# 确保常驻 builder 容器在运行（卷挂载源码 + m2 + settings）。失败返回非 0 → 调用方回退 C1。
ensure_mvnd_builder() {
    ensure_mvnd_image || return 1
    # 已在运行
    if [ "$(docker inspect -f '{{.State.Running}}' "$MVND_CONTAINER" 2>/dev/null)" = "true" ]; then
        return 0
    fi
    # 存在但已停止 → 启动
    if docker inspect "$MVND_CONTAINER" >/dev/null 2>&1; then
        docker start "$MVND_CONTAINER" >/dev/null 2>&1 && return 0
        # 启动失败（卷/配置可能变化）→ 删除重建
        docker rm -f "$MVND_CONTAINER" >/dev/null 2>&1 || true
    fi
    print_info "启动常驻 mvnd builder 容器 $MVND_CONTAINER ..."
    docker run -d --name "$MVND_CONTAINER" \
        --user "$(id -u):$(id -g)" \
        -e HOME=/tmp \
        -v "${SCRIPT_DIR}:/build" \
        -v "${MAVEN_CACHE_DIR}:/m2/repository" \
        -v "${MAVEN_SETTINGS_FILE}:/m2/settings.xml:ro" \
        -w /build \
        "$MVND_IMAGE" >/dev/null 2>&1
}

# 停止并删除常驻 builder 容器（回收 daemon 内存）
stop_mvnd_builder() {
    if docker inspect "$MVND_CONTAINER" >/dev/null 2>&1; then
        print_info "停止 mvnd builder 容器 $MVND_CONTAINER ..."
        docker rm -f "$MVND_CONTAINER" >/dev/null 2>&1 || true
    fi
}

# 第一阶段：Maven 编译（C2 常驻 mvnd 容器，或 C1 一次性 docker run 卷挂载），Jar 收集到 target/jars
build_base_jars() {
    local force="${1:-0}"
    local _t0=$SECONDS

    print_info "========== 第一阶段：Maven 编译（docker run 卷挂载）=========="

    local current_hash stored_hash
    current_hash="$(hash_build_inputs)"
    stored_hash=""
    [ -f "$BUILD_STAMP_FILE" ] && stored_hash="$(cat "$BUILD_STAMP_FILE" 2>/dev/null || true)"

    # 非强制（force≠1 且 FORCE_REBUILD≠1）且 Jar 已存在、输入哈希一致 → 跳过编译
    if [ "$force" != "1" ] && [ "${FORCE_REBUILD:-0}" != "1" ] \
        && check_jars_exist && [ -n "$current_hash" ] && [ "$current_hash" = "$stored_hash" ]; then
        local jar_count
        jar_count=$(find "$JARS_DIR" -maxdepth 1 -name "*.jar" -type f 2>/dev/null | wc -l)
        print_success "构建输入未变（源码/pom 哈希一致），跳过 Maven 编译（$JARS_DIR 现有 $jar_count 个 Jar，耗时 $((SECONDS - _t0))s）"
        echo
        return 0
    fi

    # 清空本轮哈希暂存区：compute 写入、store 复用；陈旧暂存（上轮残留）不得复用（#5）
    rm -rf "${MODULE_HASH_DIR}/.staging" 2>/dev/null || true

    # ===== Maven 构建范围决策（选择性 reactor 构建）=====
    # maven_build_args：空=全量；"-pl A,B -amd"=只编变更模块及其依赖方
    local maven_build_args=""
    local force_full=0
    local cur_global stored_global
    cur_global="$(hash_global_inputs)"
    stored_global=""
    [ -f "${MODULE_HASH_DIR}/.global-inputs" ] && stored_global="$(cat "${MODULE_HASH_DIR}/.global-inputs" 2>/dev/null || true)"

    if [ "$force" = "1" ] || [ "${FORCE_REBUILD:-0}" = "1" ]; then
        force_full=1
        print_info "强制全量构建（force / FORCE_REBUILD=1）"
    elif [ ! -d "$MODULE_HASH_DIR" ] || [ -z "$(ls -A "$MODULE_HASH_DIR" 2>/dev/null)" ]; then
        force_full=1
        print_info "无模块哈希基线（首跑），执行全量构建"
    elif [ ! -d "${MAVEN_CACHE_DIR}/com/basiclab/iot" ]; then
        force_full=1
        print_info "宿主机 m2 缺项目产物，执行全量构建以建立基线"
    elif [ "$cur_global" != "$stored_global" ]; then
        force_full=1
        print_info "全局构建输入变化（根/父 pom 或 lombok.config），执行全量构建"
    fi

    if [ "$force_full" != "1" ]; then
        local changed_list changed_csv
        changed_list="$(compute_changed_modules)"
        if [ -z "$changed_list" ]; then
            # 仅非 Maven 输入变化（如运行时 Dockerfile）：Jar 不受影响，跳过第一阶段，交由第二阶段(D)处理
            print_success "无 Maven 模块源码变化，跳过第一阶段编译（沿用现有 Jar，耗时 $((SECONDS - _t0))s）"
            if [ -n "$current_hash" ]; then
                printf '%s\n' "$current_hash" > "$BUILD_STAMP_FILE" 2>/dev/null \
                    || print_warning "无法写入构建哈希戳: $BUILD_STAMP_FILE"
            fi
            echo
            return 0
        fi
        changed_csv="$(printf '%s' "$changed_list" | paste -sd, -)"
        maven_build_args="-pl ${changed_csv} -amd"
        print_info "选择性构建变更模块及其依赖方: -pl ${changed_csv} -amd"
    else
        print_info "本次为全量构建"
    fi

    check_compose_file
    check_docker_daemon
    cd "$SCRIPT_DIR"
    init_easyaiot_build_cache_dirs "$EASYAIOT_ROOT"

    ensure_maven_settings "$MAVEN_SETTINGS_FILE"
    mkdir -p "$JARS_DIR" "$MAVEN_CACHE_DIR"
    print_info "Maven 本地仓库（卷挂载，直接持久）: $MAVEN_CACHE_DIR"

    # 选择性构建用更快启动的短命 JVM（StopAtLevel=1）；全量构建保持默认（长编译需完整 JIT 吞吐）
    local build_maven_opts=""
    [ -n "$maven_build_args" ] && build_maven_opts="-XX:+TieredCompilation -XX:TieredStopAtLevel=1"

    # 卷挂载编译入口：$1=1 离线(+--network none)，$1=0 联网。
    # 源码 RW（target 写回宿主机 → 增量）、m2 RW（直接持久，无 cp/导出）、settings RO。
    # --user：以宿主机用户身份写产物，避免 root 属主污染。HOME/MAVEN_CONFIG 指向容器内 /tmp（非 root 可写）。
    # -ntp 静默传输进度；bf 收集器加速依赖图；artifact.threads 并行解析/下载。
    _run_build_container() {
        local offline="$1"
        local net=() off=""
        [ "$offline" = "1" ] && { net=(--network none); off="-o"; }
        docker run --rm \
            --user "$(id -u):$(id -g)" \
            -e HOME=/tmp -e MAVEN_CONFIG=/tmp/.m2 \
            -e MAVEN_OPTS="$build_maven_opts" \
            "${net[@]}" \
            -v "${SCRIPT_DIR}:/build" \
            -v "${MAVEN_CACHE_DIR}:/m2/repository" \
            -v "${MAVEN_SETTINGS_FILE}:/m2/settings.xml:ro" \
            -w /build \
            maven:3.9.11-eclipse-temurin-21-alpine \
            mvn -s /m2/settings.xml -B -ntp -T 1C \
                -Dmaven.artifact.threads=8 \
                install ${maven_build_args} ${off} \
                -Dmaven.repo.local=/m2/repository \
                -DskipTests -Dmaven.test.skip=true -Dcheckstyle.skip=true -Drevision=1.0.0
    }

    # 解析第一阶段执行器：USE_MVND=1 且常驻 mvnd 容器就绪 → C2（守护进程复用）；否则 C1（一次性 docker run）
    local stage1_mode="c1"
    if [ "${USE_MVND:-0}" = "1" ]; then
        if ensure_mvnd_builder; then
            stage1_mode="c2"
        else
            print_warning "mvnd 常驻容器不可用，本次回退 C1 一次性编译"
        fi
    fi

    # 统一编译入口：$1=1 离线，$1=0 联网。C2 走 docker exec mvnd（daemon 复用）；C1 委托 _run_build_container。
    compile_stage1() {
        local offline="$1" off=""
        [ "$offline" = "1" ] && off="-o"
        if [ "$stage1_mode" = "c2" ]; then
            docker exec "$MVND_CONTAINER" \
                mvnd -s /m2/settings.xml -B -ntp \
                    -Dmvnd.idleTimeout="${MVND_IDLE_TIMEOUT}" \
                    install ${maven_build_args} ${off} \
                    -Dmaven.repo.local=/m2/repository \
                    -DskipTests -Dmaven.test.skip=true -Dcheckstyle.skip=true -Drevision=1.0.0
        else
            _run_build_container "$offline"
        fi
    }

    if [ -n "$maven_build_args" ]; then
        # 选择性：依赖基线已在 m2 → 优先离线；失败（新增依赖，或 mvnd 内嵌 Maven 与 C1 的插件版本差异）再联网重试，自愈
        print_info "第一阶段编译（${stage1_mode}·选择性·优先离线）: install ${maven_build_args}"
        print_info "（先试离线；若下方出现 BUILD FAILURE/插件未缓存属正常，将自动转联网重试，无需理会）"
        if ! compile_stage1 1; then
            print_warning "离线未命中（新增依赖或插件版本差异），转联网构建..."
            if ! compile_stage1 0; then
                print_error "Maven 编译失败（${stage1_mode}）"
                exit 1
            fi
        fi
    else
        print_info "第一阶段编译（${stage1_mode}·全量·联网）: install"
        if ! compile_stage1 0; then
            print_error "Maven 编译失败（${stage1_mode}）"
            exit 1
        fi
    fi

    print_info "从宿主机各模块 target/ 收集 Jar 到 $JARS_DIR ..."
    collect_runtime_jars

    local jar_count=0
    while IFS= read -r jar_file; do
        [ -f "$jar_file" ] || continue
        jar_count=$((jar_count + 1))
        print_success "  ✓ $(basename "$jar_file")"
    done < <(find "$JARS_DIR" -maxdepth 1 -name "*.jar" -type f 2>/dev/null | sort)

    if [ "$jar_count" -eq 0 ]; then
        print_error "未找到任何 Jar，请检查 Maven 编译日志（docker run 卷挂载）"
        exit 1
    fi

    # 记录本次成功构建的输入哈希，供下次 update/build 判断是否可跳过
    if [ -n "$current_hash" ]; then
        printf '%s\n' "$current_hash" > "$BUILD_STAMP_FILE" 2>/dev/null \
            || print_warning "无法写入构建哈希戳: $BUILD_STAMP_FILE"
    fi
    # 记录所有模块当前源码哈希 + 全局输入哈希，供下次选择性构建比对
    store_module_hashes

    print_success "========== 第一阶段完成（共 $jar_count 个 Jar，耗时 $((SECONDS - _t0))s）=========="
    echo
}

# 第二阶段：仅打包运行时镜像（COPY target/jars，不再执行 Maven）
build_runtime_images() {
    local force="${1:-0}"
    local _t0=$SECONDS

    print_info "========== 第二阶段：构建运行时镜像 ==========="

    if ! check_jars_exist; then
        print_warning "未找到 Jar，先执行第一阶段..."
        build_base_jars 1
    fi

    check_compose_file
    check_docker_daemon
    cd "$SCRIPT_DIR"
    verify_runtime_jars

    # 逐镜像判断是否需要重建（D）：哈希 = 该模块 Jar 内容 + 其 Dockerfile。
    # 命中（镜像已存在且哈希与上次一致）则跳过；否则加入待构建列表。
    # 依赖可复现构建：源码未变 → Jar 字节一致 → 仅真正变化的模块才重建镜像。
    local idx spec dockerfile tag jar img_hash stored_hash stamp
    local build_idx=() img_hashes=()
    for idx in "${!RUNTIME_IMAGE_SPECS[@]}"; do
        spec="${RUNTIME_IMAGE_SPECS[$idx]}"
        dockerfile="${spec%%|*}"
        tag="${spec##*|}"
        jar="${JARS_DIR}/${REQUIRED_RUNTIME_JARS[$idx]}"
        img_hash="$(hash_runtime_image "$jar" "$dockerfile")"
        img_hashes[$idx]="$img_hash"
        stamp="$(runtime_stamp_file "$tag")"
        stored_hash=""
        [ -f "$stamp" ] && stored_hash="$(cat "$stamp" 2>/dev/null || true)"
        if [ "$force" != "1" ] && [ "${FORCE_REBUILD:-0}" != "1" ] \
            && docker image inspect "$tag" >/dev/null 2>&1 \
            && [ -n "$img_hash" ] && [ "$img_hash" = "$stored_hash" ]; then
            print_success "  ⤳ 跳过未变镜像: $tag"
        else
            build_idx+=("$idx")
        fi
    done

    if [ "${#build_idx[@]}" -eq 0 ]; then
        print_success "所有运行时镜像均为最新，跳过第二阶段（耗时 $((SECONDS - _t0))s）"
        echo
        return 0
    fi

    # 并行构建待更新镜像（E）：各镜像仅 COPY 一个 Jar + chown，互相独立，
    # 并行可把「串行累加」缩短为「最慢的一个」。成功后写哈希戳，失败时打印末尾日志。
    local tmp_log_dir ctx_base
    tmp_log_dir="$(mktemp -d 2>/dev/null || echo "/tmp/device-runtime-$$")"
    mkdir -p "$tmp_log_dir"
    # #6：每个镜像用「仅含自己那 1 个 Jar」的最小上下文构建，避免把 target/jars 全部 Jar(GB级)
    # 发给 daemon。上下文目录与 JARS_DIR 同盘，用硬链接(ln)即时构造、零拷贝；跨盘则回退 cp。
    # Dockerfile 经 -f 引用(可在上下文之外)，其 COPY target/jars/<jar> 相对上下文根解析。
    ctx_base="${SCRIPT_DIR}/target/.runtime-ctx"
    rm -rf "$ctx_base" 2>/dev/null || true

    local log jarname ctx
    local pids=() tags=() logs=() dfs=() hashes=()
    for idx in "${build_idx[@]}"; do
        spec="${RUNTIME_IMAGE_SPECS[$idx]}"
        dockerfile="${spec%%|*}"
        tag="${spec##*|}"
        jarname="${REQUIRED_RUNTIME_JARS[$idx]}"
        ctx="${ctx_base}/$(echo "$tag" | tr '/:' '__')"
        mkdir -p "$ctx/target/jars"
        ln "${JARS_DIR}/${jarname}" "${ctx}/target/jars/${jarname}" 2>/dev/null \
            || cp -f "${JARS_DIR}/${jarname}" "${ctx}/target/jars/${jarname}"
        log="${tmp_log_dir}/$(echo "$tag" | tr '/:' '__').log"
        print_info "并行构建运行时镜像: $tag ($dockerfile)"
        ( docker build -f "$dockerfile" -t "$tag" "$ctx" ) >"$log" 2>&1 &
        pids+=("$!"); tags+=("$tag"); logs+=("$log"); dfs+=("$dockerfile")
        hashes+=("${img_hashes[$idx]}")
    done

    local fail=0 i
    for i in "${!pids[@]}"; do
        if wait "${pids[$i]}"; then
            print_success "  ✓ ${tags[$i]}"
            if [ -n "${hashes[$i]}" ]; then
                printf '%s\n' "${hashes[$i]}" > "$(runtime_stamp_file "${tags[$i]}")" 2>/dev/null || true
            fi
        else
            fail=1
            print_error "构建失败: ${tags[$i]} (${dfs[$i]})"
            print_info "----- ${tags[$i]} 构建日志（末尾 30 行）-----"
            tail -n 30 "${logs[$i]}" 2>/dev/null | sed 's/^/    /'
        fi
    done
    rm -rf "$tmp_log_dir" "$ctx_base" 2>/dev/null || true

    if [ "$fail" -ne 0 ]; then
        print_error "存在运行时镜像构建失败，请检查上面的日志"
        exit 1
    fi

    print_success "========== 第二阶段完成（更新 ${#build_idx[@]} 个镜像，耗时 $((SECONDS - _t0))s）==========="
    echo
}

# 按需构建（install / update / build）：基于源码/依赖哈希增量，输入未变则整段跳过。
# 需强制全量重建时设置环境变量 FORCE_REBUILD=1。
build_images_incremental() {
    print_info "========== 构建（按需，输入未变则跳过）=========="
    check_compose_file
    check_docker_daemon
    build_base_jars 0
    build_runtime_images 0
}

# 构建并启动所有服务
build_and_start() {
    local _t_all=$SECONDS
    print_info "========== 开始构建并启动所有服务 =========="
    echo
    
    # 确保权限正确
    print_info "检查 Docker Compose 配置文件..."
    check_compose_file
    check_docker_daemon
    print_success "配置文件检查完成"
    
    print_info "切换到脚本目录: $SCRIPT_DIR"
    if ! cd "$SCRIPT_DIR"; then
        print_error "无法切换到目录: $SCRIPT_DIR"
        exit 1
    fi
    print_success "当前工作目录: $(pwd)"
    
    # 验证 Docker Compose 可以读取配置文件
    print_info "验证 Docker Compose 可以读取配置文件..."
    local compose_test_output
    set +e  # 暂时关闭错误退出，以便捕获退出码
    compose_test_output=$($DOCKER_COMPOSE -f "$COMPOSE_FILE" config 2>&1)
    local compose_test_exit=$?
    set -e  # 重新开启错误退出
    
    if [ $compose_test_exit -ne 0 ]; then
        print_error "Docker Compose 无法读取配置文件"
        echo "$compose_test_output" | sed 's/^/  /'
        exit 1
    else
        print_success "Docker Compose 配置文件验证通过"
    fi
    
    echo
    
    # 按需构建镜像（源码/依赖哈希未变则跳过，首次安装会全量构建）
    build_images_incremental
    
    # 启动所有服务
    print_info "========== 启动所有服务 =========="
    
    print_info "准备启动所有服务..."
    echo
    
    # 启动所有服务
    print_info "启动所有服务..."
    set +e  # 暂时关闭错误退出，以便捕获退出码
    compose_up_detached
    exit_code=$?
    set -e  # 重新开启错误退出
    
    echo  # 添加空行分隔
    
    # 检查命令是否成功
    if [ $exit_code -ne 0 ]; then
        print_error "服务启动失败（退出码: $exit_code）"
        show_unhealthy_containers
        exit 1
    fi
    
    # 验证容器是否真的创建了
    local container_count
    container_count=$($DOCKER_COMPOSE ps -q 2>/dev/null | wc -l)
    if [ "$container_count" -eq 0 ]; then
        print_error "警告：没有检测到运行的容器"
        print_info "请检查 docker-compose.yml 配置和依赖服务（如 Nacos、PostgreSQL、Redis 等）"
        print_info "尝试查看服务状态："
        $DOCKER_COMPOSE ps
        exit 1
    fi
    
    print_success "========== 服务构建并启动完成 =========="
    print_success "服务构建并启动完成（共 $container_count 个容器，总耗时 $((SECONDS - _t_all))s）"
    echo
    print_info "Jar 包: $JARS_DIR"
    print_info "Maven 缓存: $MAVEN_CACHE_DIR"
    print_info "可以使用以下命令查看服务状态:"
    print_info "  $0 status"
    print_info "  $0 logs [服务名]"
}

# 启动所有服务
start_services() {
    print_info "启动所有服务..."
    cd "$SCRIPT_DIR"
    compose_up_detached --quiet-pull 2>&1 | grep -E "(Creating|Starting|Started|Healthy|ERROR|WARNING|Recreate)" || true
    print_success "服务启动完成"
}

# 停止所有服务
stop_services() {
    print_info "停止所有服务..."
    cd "$SCRIPT_DIR"
    $DOCKER_COMPOSE down
    print_success "服务已停止"
}

# 重启所有服务
restart_services() {
    print_info "重启所有服务..."
    cd "$SCRIPT_DIR"
    $DOCKER_COMPOSE restart
    print_success "服务重启完成"
}

# 查看服务状态
show_status() {
    print_info "服务状态:"
    cd "$SCRIPT_DIR"
    $DOCKER_COMPOSE ps
}

# 查看日志
show_logs() {
    local service=$1
    if [ -z "$service" ]; then
        print_info "查看所有服务日志（最近50行，按Ctrl+C退出）..."
        cd "$SCRIPT_DIR"
        $DOCKER_COMPOSE logs -f --tail=50
    else
        print_info "查看服务 $service 的日志（最近50行，按Ctrl+C退出）..."
        cd "$SCRIPT_DIR"
        $DOCKER_COMPOSE logs -f --tail=50 "$service"
    fi
}

# 查看特定服务的日志（最近50行）
show_logs_tail() {
    local service=$1
    if [ -z "$service" ]; then
        print_info "查看所有服务最近50行日志..."
        cd "$SCRIPT_DIR"
        $DOCKER_COMPOSE logs --tail=50
    else
        print_info "查看服务 $service 最近50行日志..."
        cd "$SCRIPT_DIR"
        $DOCKER_COMPOSE logs --tail=50 "$service"
    fi
}

# 重启特定服务
restart_service() {
    local service=$1
    if [ -z "$service" ]; then
        print_error "请指定要重启的服务名称"
        echo "可用服务:"
        cd "$SCRIPT_DIR"
        $DOCKER_COMPOSE config --services
        exit 1
    fi
    print_info "重启服务: $service"
    cd "$SCRIPT_DIR"
    $DOCKER_COMPOSE restart "$service"
    print_success "服务 $service 重启完成"
}

# 停止特定服务
stop_service() {
    local service=$1
    if [ -z "$service" ]; then
        print_error "请指定要停止的服务名称"
        echo "可用服务:"
        cd "$SCRIPT_DIR"
        $DOCKER_COMPOSE config --services
        exit 1
    fi
    print_info "停止服务: $service"
    cd "$SCRIPT_DIR"
    $DOCKER_COMPOSE stop "$service"
    print_success "服务 $service 已停止"
}

# 启动特定服务
start_service() {
    local service=$1
    if [ -z "$service" ]; then
        print_error "请指定要启动的服务名称"
        echo "可用服务:"
        cd "$SCRIPT_DIR"
        $DOCKER_COMPOSE config --services
        exit 1
    fi
    print_info "启动服务: $service"
    cd "$SCRIPT_DIR"
    compose_up_detached "$service"
    print_success "服务 $service 启动完成"
}

# 清理（停止并删除容器）
clean() {
    if [ "${EASYAIOT_AUTO_YES:-}" != "1" ]; then
        print_warning "这将停止并删除所有容器，但保留镜像"
        local response
        while true; do
            read -r -p "确认继续? [y/n] " response
            case "$(echo "$response" | tr '[:upper:]' '[:lower:]')" in
                y|yes) break ;;
                n|no|'')
                    print_info "操作已取消"
                    return
                    ;;
                *) echo "请输入 y/yes 或 n/no" ;;
            esac
        done
    fi
    cd "$SCRIPT_DIR"
    $DOCKER_COMPOSE down
    print_success "容器清理完成"

    print_info "清理各模块 target 目录下的 .jar 包..."
    local modules=(
        "iot-dataset"
        "iot-node"
        "iot-device"
        "iot-file"
        "iot-gateway"
        "iot-gb28181"
        "iot-infra"
        "iot-message"
        "iot-sink"
        "iot-system"
        "iot-tdengine"
    )

    local jar_count=0
    for module in "${modules[@]}"; do
        local module_path="${SCRIPT_DIR}/${module}"
        if [ -d "$module_path" ]; then
            local found_jars
            found_jars=$(find "$module_path" -type f -name "*.jar" -path "*/target/*" 2>/dev/null || true)
            if [ -n "$found_jars" ]; then
                while IFS= read -r jar_file; do
                    if [ -f "$jar_file" ]; then
                        rm -f "$jar_file"
                        jar_count=$((jar_count + 1))
                        print_info "已删除: $jar_file"
                    fi
                done <<< "$found_jars"
            fi
        fi
    done

    if [ "$jar_count" -gt 0 ]; then
        print_success "已清理 $jar_count 个 .jar 文件"
    else
        print_info "未找到需要清理的 .jar 文件"
    fi

    stop_mvnd_builder
    print_success "清理完成"
}

# 完全清理（包括镜像）
clean_all() {
    if [ "${EASYAIOT_AUTO_YES:-}" != "1" ]; then
        print_warning "这将停止并删除所有容器和镜像"
        local response
        while true; do
            read -r -p "确认继续? [y/n] " response
            case "$(echo "$response" | tr '[:upper:]' '[:lower:]')" in
                y|yes) break ;;
                n|no|'')
                    print_info "操作已取消"
                    return
                    ;;
                *) echo "请输入 y/yes 或 n/no" ;;
            esac
        done
    fi
    cd "$SCRIPT_DIR"
    $DOCKER_COMPOSE down --rmi all
    stop_mvnd_builder
    print_success "完全清理完成"
}

# 更新服务（重新构建并重启）
update_services() {
    local _t_all=$SECONDS
    print_info "========== 更新所有服务 =========="

    # 确保权限正确
    check_compose_file
    check_docker_daemon

    build_images_incremental

    # 重启所有服务
    print_info "重启所有服务..."
    local exit_code

    # 仅重建镜像/配置发生变化的服务（去掉 --force-recreate，避免无谓重启全部容器，最小化停机）
    set +e  # 暂时关闭错误退出，以便捕获退出码（否则 set -e 会在失败时直接 abort，下方友好报错不可达）
    compose_up_detached
    exit_code=$?
    set -e  # 重新开启错误退出

    # 检查命令是否成功
    if [ $exit_code -ne 0 ]; then
        print_error "服务更新失败（退出码: $exit_code）"
        show_unhealthy_containers
        exit 1
    fi
    
    # 验证容器是否真的创建了
    local container_count
    container_count=$($DOCKER_COMPOSE ps -q 2>/dev/null | wc -l)
    if [ "$container_count" -eq 0 ]; then
        print_error "警告：没有检测到运行的容器"
        print_info "请检查 docker-compose.yml 配置和依赖服务（如 Nacos、PostgreSQL、Redis 等）"
        print_info "尝试查看服务状态："
        $DOCKER_COMPOSE ps
        exit 1
    fi
    
    print_success "========== 服务更新完成（共 $container_count 个容器，总耗时 $((SECONDS - _t_all))s）=========="
}

# 显示帮助信息
show_help() {
    cat << EOF
DEVICE模块 Docker Compose 管理脚本

用法: $0 [命令] [选项]

构建流程（两阶段）:
    1) docker run 卷挂载编译：源码与 m2 直接挂载进 maven 镜像跑 mvn install，产物落到各模块 target/ → 收集到 target/jars
       （增量：仅改动模块及其依赖方参与编译 -pl … -amd；m2 与 target 持久在宿主机，无需 docker cp 搬运）
    2) 各模块 Dockerfile：仅从 target/jars 打运行时镜像，不再执行 Maven

命令:
    build-base          仅第一阶段（Maven 编译 + 收集 Jar）
    build               两阶段（Jar 已存在则跳过第一阶段）
    start               启动所有服务
    stop                停止所有服务
    restart             重启所有服务
    status              查看服务状态
    logs [服务名]       查看日志（所有服务或指定服务，最近50行）
    logs-tail [服务名]  查看最近50行日志
    restart-service     重启指定服务
    stop-service        停止指定服务
    start-service       启动指定服务
    clean               清理（停止并删除容器，保留镜像；并停止 mvnd builder）
    clean-all           完全清理（停止并删除容器和镜像；并停止 mvnd builder）
    builder-stop        停止常驻 mvnd builder 容器（回收 daemon 内存）
    update              更新服务（重新构建并重启）
    install             安装（构建并启动所有服务）
    help                显示此帮助信息

环境变量:
    USE_MVND=1          启用 C2 常驻 mvnd 容器编译（守护进程跨次复用，更快）；不可用时自动回退 C1。
                        默认 0 走 C1（一次性 docker run 卷挂载，无常驻进程）。
                        注意：C2 会常驻一个 mvnd 容器（约 1–2GB 内存），用 builder-stop / clean 回收。
    MVND_VERSION        mvnd 版本（默认 1.0.6）；MVND_IMAGE/MVND_CONTAINER 可覆盖镜像/容器名。
    MVND_IDLE_TIMEOUT   mvnd daemon 空闲多久自动退出释放内存（默认 30m，容器保留，下次自动重生）。
    FORCE_REBUILD=1     强制全量重建（绕过增量与哈希跳过）。

示例:
    $0 install                    # 构建并启动所有服务
    $0 build                      # 仅构建运行时镜像
    USE_MVND=1 $0 update          # 用常驻 mvnd 守护进程编译并更新（C2）
    $0 builder-stop               # 停止 mvnd 常驻容器
    $0 logs iot-gateway           # 查看iot-gateway的日志
    $0 status                     # 查看所有服务状态

可用服务:
    - iot-gateway
    - iot-system
    - iot-infra
    - iot-device
    - iot-dataset
    - iot-node
    - iot-tdengine
    - iot-file
    - iot-message
    - iot-sink
    - iot-gb28181

EOF
}

# 主函数
main() {
    check_compose_file
    
    case "${1:-}" in
        build-base)
            build_base_jars 1
            ;;
        build)
            build_images_incremental
            ;;
        start)
            start_services
            ;;
        stop)
            stop_services
            ;;
        restart)
            restart_services
            ;;
        status)
            show_status
            ;;
        logs)
            show_logs "$2"
            ;;
        logs-tail)
            show_logs_tail "$2"
            ;;
        restart-service)
            restart_service "$2"
            ;;
        stop-service)
            stop_service "$2"
            ;;
        start-service)
            start_service "$2"
            ;;
        clean)
            clean
            ;;
        clean-all)
            clean_all
            ;;
        builder-stop)
            stop_mvnd_builder
            print_success "mvnd 常驻 builder 容器已停止（如存在）"
            ;;
        update)
            update_services
            ;;
        install|build-and-start)
            build_and_start
            ;;
        help|--help|-h)
            show_help
            ;;
        "")
            # 如果没有参数，显示交互式菜单
            show_interactive_menu
            ;;
        *)
            print_error "未知命令: $1"
            echo
            show_help
            exit 1
            ;;
    esac
}

# 交互式菜单
show_interactive_menu() {
    while true; do
        echo
        echo -e "${BLUE}========================================${NC}"
        echo -e "${BLUE}  DEVICE模块 Docker Compose 管理${NC}"
        echo -e "${BLUE}========================================${NC}"
        echo "1) 安装/构建并启动所有服务"
        echo "2) 构建所有运行时镜像"
        echo "3) 启动所有服务"
        echo "4) 停止所有服务"
        echo "5) 重启所有服务"
        echo "6) 查看服务状态"
        echo "7) 查看日志（所有服务）"
        echo "8) 查看日志（指定服务）"
        echo "9) 重启指定服务"
        echo "10) 停止指定服务"
        echo "11) 启动指定服务"
        echo "12) 更新服务（重新构建并重启）"
        echo "13) 清理（删除容器，保留镜像）"
        echo "14) 完全清理（删除容器和镜像）"
        echo "15) 停止 mvnd 常驻 builder 容器"
        echo "0) 退出"
        echo
        read -p "请选择操作 [0-15]: " choice
        
        case $choice in
            1)
                build_and_start
                ;;
            2)
                build_images_incremental
                ;;
            3)
                start_services
                ;;
            4)
                stop_services
                ;;
            5)
                restart_services
                ;;
            6)
                show_status
                ;;
            7)
                show_logs
                ;;
            8)
                echo "可用服务:"
                cd "$SCRIPT_DIR"
                $DOCKER_COMPOSE config --services
                read -p "请输入服务名称: " service_name
                show_logs "$service_name"
                ;;
            9)
                echo "可用服务:"
                cd "$SCRIPT_DIR"
                $DOCKER_COMPOSE config --services
                read -p "请输入服务名称: " service_name
                restart_service "$service_name"
                ;;
            10)
                echo "可用服务:"
                cd "$SCRIPT_DIR"
                $DOCKER_COMPOSE config --services
                read -p "请输入服务名称: " service_name
                stop_service "$service_name"
                ;;
            11)
                echo "可用服务:"
                cd "$SCRIPT_DIR"
                $DOCKER_COMPOSE config --services
                read -p "请输入服务名称: " service_name
                start_service "$service_name"
                ;;
            12)
                update_services
                ;;
            13)
                clean
                ;;
            14)
                clean_all
                ;;
            15)
                stop_mvnd_builder
                print_success "mvnd 常驻 builder 容器已停止（如存在）"
                ;;
            0)
                print_info "退出"
                exit 0
                ;;
            *)
                print_error "无效选择，请重新输入"
                ;;
        esac
    done
}

# 执行主函数
main "$@"
