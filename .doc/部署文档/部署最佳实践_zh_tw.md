# EasyAIoT 部署指南

> 本文檔基於專案原始碼分析產生，適用於 Linux 環境一鍵部署。

---

## 一、環境要求

### 1.1 硬體要求

| 資源 | 最低配置 | 推薦配置 |
|------|---------|---------|
| CPU | 4 核 | 8 核+ |
| 記憶體 | 8 GB | 16 GB+ |
| 磁碟 | 100 GB | 500 GB+ SSD |
| GPU | 無（CPU 可運行） | NVIDIA GPU（CUDA 12.8） |

### 1.2 軟體要求

| 軟體 | 最低版本 | 說明 |
|------|---------|------|
| 作業系統 | Ubuntu 20.04 / CentOS 7 | 推薦 Ubuntu 22.04 LTS |
| Docker | 20.10+ | 需支援 `docker compose` v2 |
| Docker Compose | v2 | 隨 Docker Desktop 自動安裝，或獨立安裝 |
| NVIDIA Driver | 525+ | 僅 GPU 場景需要 |
| NVIDIA Container Toolkit | 最新版 | 僅 GPU 場景需要 |

### 1.3 連接埠要求

部署前確保以下連接埠未被佔用：

| 連接埠 | 服務 | 說明 |
|------|------|------|
| 1880 | Node-RED | 規則引擎 |
| 1883 | EMQX | MQTT Broker |
| 1935 | SRS | 串流媒體 RTMP |
| 5432 | PostgreSQL | 主資料庫 |
| 6000 | VIDEO 服务 | 影片處理 |
| 6030 | TDengine | 時序資料庫 |
| 6080 | ZLMediaKit | 媒體伺服器 |
| 6379 | Redis | 快取 |
| 8848 | Nacos | 註冊/設定中心 |
| 8888 | WEB 前端 | 管理介面 |
| 9000 | MinIO API | 物件儲存 |
| 9001 | MinIO Console | 物件儲存主控台 |
| 9092 | Kafka | 訊息佇列 |
| 10180 | GPUStack | GPU 管理 |
| 10190 | Dify | LLM 應用平台 |
| 19530 | Milvus | 向量資料庫 |
| 48080 | API Gateway | 後端閘道 |
| 5000 | AI 服务 | AI 推理 |

---

## 二、快速部署（一鍵安裝）

### 2.1 取得原始碼

```bash
git clone https://gitee.com/volara/easyaiot.git
cd easyaiot
```

### 2.2 一鍵安裝

```bash
# 需要 root 权限（用于配置 Docker 镜像源、RTP 端口预留等）
sudo .scripts/docker/install_linux.sh install
```

該指令會自動執行以下流程：

1. **環境檢查** — 偵測 Docker / Docker Compose 是否已安裝
2. **IP 偵測** — 自動偵測宿主機 IP（用於 GB28181/ZLMediaKit 媒體位址注入）
3. **RTP 連接埠預留** — 設定 Linux 核心保留連接埠 30000-30500（避免被臨時連接埠佔用）
4. **Docker 映像來源設定** — 自動設定 `docker.m.daocloud.io` 加速映像（[DaoCloud 公共鏡像](https://github.com/DaoCloud/public-image-mirror)）
5. **建立 Docker 網路** — 建立統一網路 `easyaiot-network`
6. **部署中介軟體** — 依序啟動 Nacos、PostgreSQL、Redis、Kafka、MinIO、TDengine、Milvus、SRS、EMQX、ZLMediaKit、GPUStack、Dify、Node-RED
7. **等待基礎服務就緒** — 自動等待 PostgreSQL / Nacos / Redis 健康檢查通過
8. **部署 DEVICE 服務** — 建置並啟動 Java 微服務叢集（閘道 + 8 個業務服務）
9. **部署 AI 服務** — 建置並啟動 Python AI 推理服務
10. **部署 VIDEO 服務** — 建置並啟動 Python 影片處理服務及 6 個子服務
11. **部署 WEB 前端** — 建置並啟動 Vue 3 前端

### 2.3 驗證部署

```bash
# 验证所有服务是否启动成功
.scripts/docker/install_linux.sh verify
```

成功後會顯示所有服務的存取位址：

```
服务访问地址:
  基础服务 (Nacos):     http://localhost:8848/nacos
  基础服务 (MinIO):     http://localhost:9000 (API), http://localhost:9001 (Console)
  基础服务 (Milvus):    http://localhost:9091 (Health), localhost:19530 (gRPC)
  基础服务 (GPUStack):  http://localhost:10180  (用户 admin)
  Device服务 (Gateway): http://localhost:48080
  AI服务:               http://localhost:5000
  Video服务:            http://localhost:6000
  Web前端:              http://localhost:8888
```

### 2.4 存取系統

瀏覽器開啟 `http://<服务器IP>:8888`，即可存取 EasyAIoT 管理平台。

---

## 三、分步部署（手動操作）

若需要更精細的控制，可依模組分步部署。

### 3.1 第一步：部署中介軟體

```bash
cd .scripts/docker
./install_middleware_linux.sh install
```

**中介軟體清單：**

| 中介軟體 | 映像 | 連接埠 | 用途 |
|--------|------|------|------|
| Nacos | nacos/nacos-server:v2.5.1 | 8848, 9848, 9849 | 服務註冊與設定中心 |
| PostgreSQL | postgres:18 | 5432 | 主資料庫（6 個業務庫） |
| TDengine | tdengine/tsdb:3.3.8.4 | 6030, 6041, 6060 | 時序資料庫 |
| Redis | redis:7.4.8 | 6379 | 快取與分散式鎖 |
| Kafka | apache/kafka:3.8.0 | 9092, 9093, 9094 | 訊息佇列 |
| MinIO | minio/minio | 9000, 9001 | 物件儲存 |
| Milvus | milvusdb/milvus:v2.6.0 | 19530, 9091 | 向量資料庫（人臉辨識） |
| SRS | ossrs/srs:5 | 1935, 1985 | 串流媒體伺服器 |
| EMQX | emqx/emqx:5.8.7 | 1883, 8083, 18083 | MQTT Broker |
| ZLMediaKit | zlmediakit/zlmediakit:master | 6080, 5540, 10935 | 媒體伺服器 |
| GPUStack | gpustack/gpustack:v2.1.2 | 10180 | GPU 資源管理 |
| Dify | dify-api / dify-web / ... | 10190 | LLM 應用平台 |
| Node-RED | nodered/node-red:latest | 1880 | 規則引擎 |

等待中介軟體就緒：

```bash
# 检查 PostgreSQL
docker exec postgres-server pg_isready -U postgres

# 检查 Nacos
curl -s http://localhost:8848/nacos/actuator/health

# 检查 Redis
docker exec redis-server redis-cli -a basiclab@iot975248395 ping
```

### 3.2 第二步：部署 DEVICE 服務

```bash
cd DEVICE
./install_linux.sh install
```

**DEVICE 服務清單：**

| 服務 | 連接埠 | 說明 |
|------|------|------|
| iot-gateway | 48080 | API 閘道（Spring Cloud Gateway） |
| iot-system | 48099 | 系統管理 |
| iot-infra | 48066 | 基礎設施 |
| iot-device | 48055 | 裝置管理 |
| iot-dataset | 48077 | 資料集管理 |
| iot-message | 48033 | 訊息推送 |
| iot-file | 48022 | 檔案服務 |
| iot-sink | 48011 | 協定適配（MQTT/TCP/HTTP/EMQX） |
| iot-gb28181 | 5060 | GB28181 視訊監控協定 |

**建置方式：**
- 兩階段建置：`Dockerfile.base`（Maven 依賴快取）→ 各模組 `Dockerfile`
- Java 21 + Spring Boot 2.7.18
- 建置快取目錄：`.build-cache/device/m2/repository`

### 3.3 第三步：部署 AI 服務

```bash
cd AI
./install_linux.sh install
```

**AI 服務說明：**
- 連接埠：5000
- 框架：Flask + PyTorch 2.9+ (CUDA 12.8)
- 功能：模型訓練、推理、部署、OCR、語音、LLM
- GPU 支援：自動偵測 GPU 並啟用 NVIDIA Container Runtime
- 建置快取：`.build-cache/ai/pip-cache`、`.build-cache/ai/pip-wheels`
- 基礎映像：`pytorch/pytorch:2.9.0-cuda12.8-cudnn9-devel`

### 3.4 第四步：部署 VIDEO 服務

```bash
cd VIDEO
./install_linux.sh install
```

**VIDEO 服務說明：**
- 連接埠：6000
- 框架：Flask + OpenCV + FFmpeg
- 功能：影片串流處理、即時/快照演算法分析、錄影、告警、人臉辨識
- 子服務：6 個獨立微服務（即時演算法、快照演算法、擷取影格、排序、推流、串流轉發）
- 訊息佇列：Kafka（告警事件）
- 向量資料庫：Milvus（人臉辨識）

### 3.5 第五步：部署 WEB 前端

```bash
cd WEB
./install_linux.sh install
```

**WEB 前端說明：**
- 連接埠：8888
- 框架：Vue 3.4 + TypeScript + Vite
- UI 庫：Ant Design Vue 4.0
- 建置：Node.js 18+ / 20+，pnpm 11.3+

---

## 四、單模組管理

每個模組皆支援以下指令：

```bash
./install_linux.sh install    # 安装并启动（首次运行）
./install_linux.sh start      # 启动
./install_linux.sh stop       # 停止
./install_linux.sh restart    # 重启
./install_linux.sh status     # 查看状态
./install_linux.sh logs       # 查看日志
./install_linux.sh build      # 重新构建镜像
./install_linux.sh clean      # 清理容器和镜像
./install_linux.sh update     # 更新并重启
```

**中介軟體單獨管理：**

```bash
cd .scripts/docker
./install_middleware_linux.sh install    # 安装所有中间件
./install_middleware_linux.sh start      # 启动
./install_middleware_linux.sh stop       # 停止
./install_middleware_linux.sh status     # 状态
./install_middleware_linux.sh logs       # 日志
```

---

## 五、GPU 設定

### 5.1 安裝 NVIDIA 驅動

```bash
# 检查 GPU 是否可用
nvidia-smi

# 安装 NVIDIA Container Toolkit
# 参考：https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

# 验证 Docker GPU 支持
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi
```

### 5.2 GPU 自動偵測

安裝腳本會自動偵測 GPU：
- 偵測到 GPU → 自動啟用 `runtime: nvidia`、設定 `NVIDIA_VISIBLE_DEVICES=all`
- 未偵測到 GPU → 使用 CPU 模式運行

### 5.3 多 GPU 設定

AI 服務支援多 GPU 並行推理，透過環境變數控制：

```bash
# 指定使用 GPU 0 和 1
export CUDA_VISIBLE_DEVICES=0,1
```

---

## 六、國產化適配

### 6.1 銀河麒麟系統

```bash
.scripts/docker/install_linux_kylin.sh install
```

### 6.2 ARM64 架構

```bash
# 中间件
.scripts/docker/install_linux_arm.sh install

# AI 服务（ARM 版 Dockerfile）
cd AI
./install_linux.sh install  # 脚本会自动选择 ARM Dockerfile
```

---

## 七、資料庫說明

### 7.1 PostgreSQL 業務庫

PostgreSQL 啟動時會自動建立以下 6 個業務庫：

| 庫名 | SQL 檔案 | 用途 |
|------|---------|------|
| ruoyi-vue-pro20 | ruoyi-vue-pro10.sql | 系統管理主庫 |
| iot-ai20 | iot-ai10.sql | AI 服務庫 |
| iot-device10 | iot-device10.sql | 裝置管理庫 |
| iot-gb2818110 | iot-gb2818110.sql | 視訊監控庫 |
| iot-message10 | iot-message10.sql | 訊息推送庫 |
| iot-video10 | iot-video10.sql | 影片處理庫 |

初始化腳本位於 `.scripts/postgresql/` 目錄，Docker 啟動時透過 `docker-entrypoint-initdb.d` 自動執行。

### 7.2 TDengine 時序庫

TDengine 啟動後會自動初始化超級表，SQL 檔案位於 `.scripts/tdengine/tdengine_super_tables.sql`。

### 7.3 資料庫備份

```bash
# 备份所有数据库
.scripts/postgresql/backup_databases.sh
```

---

## 八、中介軟體預設帳號密碼

| 中介軟體 | 使用者名稱 | 密碼 | 主控台位址 |
|--------|--------|------|-----------|
| Nacos | nacos | nacos | http://<IP>:8848/nacos |
| PostgreSQL | postgres | iot45722414822 | — |
| Redis | — | basiclab@iot975248395 | — |
| MinIO | minioadmin | basiclab@iot975248395 | http://<IP>:9001 |
| EMQX | admin | basiclab@iot6874125784 | http://<IP>:18083 |
| GPUStack | admin | basiclab@iotp4JWmQSvzdh0z4mF | http://<IP>:10180 |
| Milvus | — | — | http://<IP>:9091 |

> ⚠️ **安全提示**：生產環境請務必修改所有預設密碼。

---

## 九、故障排查

### 9.1 服務啟動失敗

```bash
# 查看具体服务日志
docker logs -f postgres-server
docker logs -f nacos-server
docker logs -f ai-service
docker logs -f video-service

# 查看所有服务状态
docker ps -a
```

### 9.2 網路問題

```bash
# 检查 Docker 网络
docker network ls | grep easyaiot
docker network inspect easyaiot-network

# 重建网络（宿主机 IP 变化后）
docker network rm easyaiot-network
docker network create easyaiot-network
docker compose restart
```

### 9.3 PostgreSQL 連線問題

```bash
# 自动修复
.scripts/docker/fix_postgresql.sh

# 手动检查
docker exec postgres-server pg_isready -U postgres
docker exec postgres-server psql -U postgres -c "SELECT 1;"
```

### 9.4 Redis 連線問題

```bash
# 自动修复
.scripts/docker/fix_redis.sh

# 手动检查
docker exec redis-server redis-cli -a basiclab@iot975248395 ping
```

### 9.5 Docker 服務問題

```bash
# 诊断 Docker systemd 问题
sudo .scripts/docker/diagnose_docker_systemd.sh diagnose

# 修复 systemd 超时
sudo .scripts/docker/diagnose_docker_systemd.sh fix-all

# 检查磁盘空间
df -h
docker system df

# 清理 Docker 垃圾
.scripts/docker/cleanup_docker_space.sh
```

### 9.6 Kafka 消費群組問題

```bash
# 修复 Kafka 消费组
cd VIDEO
python fix_kafka_consumer_group.py
```

### 9.7 連接埠衝突

```bash
# 检查端口占用
ss -tlnp | grep -E "8848|5432|6379|9092|5000|6000|8888"

# 如有冲突，修改对应 docker-compose.yml 中的端口映射
```

---

## 十、日誌檔案位置

| 位置 | 說明 |
|------|------|
| `.scripts/docker/logs/` | 安裝腳本日誌 |
| `DEVICE/logs/` | DEVICE 服務日誌 |
| `AI/data/logs/` | AI 服務日誌 |
| `VIDEO/data/logs/` | VIDEO 服務日誌 |
| `docker logs <容器名>` | 容器即時日誌 |

---

## 十一、更新與升級

### 11.1 更新程式碼

```bash
cd easyaiot
git pull origin main
```

### 11.2 更新並重啟所有服務

```bash
sudo .scripts/docker/install_linux.sh update
```

### 11.3 更新單一模組

```bash
# 例如只更新 AI 服务
cd AI
./install_linux.sh update
```

### 11.4 重新建置映像

```bash
# 重新构建所有镜像
sudo .scripts/docker/install_linux.sh build

# 重新构建单个模块
cd DEVICE
./install_linux.sh build
```

---

## 十二、解除安裝

```bash
# 停止并删除所有容器、镜像和网络
sudo .scripts/docker/install_linux.sh clean

# 手动清理数据卷（可选）
rm -rf .scripts/docker/db_data
rm -rf .scripts/docker/redis_data
rm -rf .scripts/docker/minio_data
rm -rf .scripts/docker/mq_data
rm -rf .scripts/docker/taos_data
rm -rf .scripts/docker/milvus_data
rm -rf .scripts/docker/gpustack_data
```

---

## 十三、架構參考

```
┌─────────────────────────────────────────────────────────────────┐
│                    WEB 前端 (:8888)                              │
│              Vue 3 + Ant Design Vue + Vite                       │
├─────────────────────────────────────────────────────────────────┤
│                 API Gateway (:48080)                              │
│              Spring Cloud Gateway + Nacos                        │
├───────────┬───────────┬───────────┬───────────┬─────────────────┤
│ iot-system│ iot-infra │ iot-device│ iot-dataset│  iot-message   │
│ iot-file  │ iot-sink  │ iot-gb28181                        │
│           │           │           │           │                  │
│    Java 21 + Spring Boot 2.7 + MyBatis-Plus                     │
├───────────┴───────────┴───────────┴───────────┴─────────────────┤
│  AI 服务 (:5000)         │  VIDEO 服务 (:6000)    │  TASK (C++)  │
│  Flask + PyTorch + YOLO  │  Flask + OpenCV + FFmpeg│  ONNX Runtime│
│  訓練/推理/部署/OCR/LLM  │  串流處理/告警/錄影/人臉  │  邊緣推理    │
├──────────────────────────┴───────────────────────┴──────────────┤
│                     中介軟體層                                     │
│  Nacos │ PostgreSQL │ Redis │ Kafka │ MinIO │ TDengine          │
│  Milvus │ SRS │ EMQX │ ZLMediaKit │ GPUStack │ Dify │ Node-RED  │
└─────────────────────────────────────────────────────────────────┘
```

---

*文件生成時間：2026-05-31 | 專案地址：https://gitee.com/volara/easyaiot*
