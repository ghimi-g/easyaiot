# EasyAIoT Deployment Guide

> This document is generated from project source code analysis and applies to one-click deployment on Linux.

---

## 1. Environment Requirements

### 1.1 Hardware Requirements

| Resource | Minimum | Recommended |
|------|---------|---------|
| CPU | 4 cores | 8 cores+ |
| Memory | 8 GB | 16 GB+ |
| Disk | 100 GB | 500 GB+ SSD |
| GPU | None (CPU mode supported) | NVIDIA GPU (CUDA 12.8) |

### 1.2 Software Requirements

| Software | Minimum Version | Notes |
|------|---------|------|
| Operating System | Ubuntu 20.04 / CentOS 7 | Ubuntu 22.04 LTS recommended |
| Docker | 20.10+ | Must support `docker compose` v2 |
| Docker Compose | v2 | Installed automatically with Docker Desktop, or install separately |
| NVIDIA Driver | 525+ | Required only for GPU scenarios |
| NVIDIA Container Toolkit | Latest | Required only for GPU scenarios |

### 1.3 Port Requirements

Ensure the following ports are not in use before deployment:

| Port | Service | Description |
|------|------|------|
| 1880 | Node-RED | Rule engine |
| 1883 | EMQX | MQTT Broker |
| 1935 | SRS | Streaming media RTMP |
| 5432 | PostgreSQL | Primary database |
| 6000 | VIDEO Service | Video processing |
| 6030 | TDengine | Time-series database |
| 6080 | ZLMediaKit | Media server |
| 6379 | Redis | Cache |
| 8848 | Nacos | Registry / configuration center |
| 8888 | WEB Frontend | Management UI |
| 9000 | MinIO API | Object storage |
| 9001 | MinIO Console | Object storage console |
| 9092 | Kafka | Message queue |
| 10180 | GPUStack | GPU management |
| 10190 | Dify | LLM application platform |
| 19530 | Milvus | Vector database |
| 48080 | API Gateway | Backend gateway |
| 5000 | AI Service | AI inference |

---

## 2. Quick Deployment (One-Click Install)

### 2.1 Obtain Source Code

```bash
git clone https://gitee.com/volara/easyaiot.git
cd easyaiot
```

### 2.2 One-Click Install

```bash
# Requires root privileges (for configuring Docker mirror, RTP port reservation, etc.)
sudo .scripts/docker/install_linux.sh install
```

This command automatically performs the following steps:

1. **Environment check** — Verifies Docker and Docker Compose are installed
2. **IP detection** — Automatically detects host IP (used for GB28181/ZLMediaKit media address injection)
3. **RTP port reservation** — Configures Linux kernel reserved ports 30000-30500 (prevents ephemeral port allocation conflicts)
4. **Docker mirror configuration** — Automatically configures `docker.m.daocloud.io` for image acceleration ([DaoCloud public image mirror](https://github.com/DaoCloud/public-image-mirror))
5. **Create Docker network** — Creates unified network `easyaiot-network`
6. **Deploy middleware** — Starts Nacos, PostgreSQL, Redis, Kafka, MinIO, TDengine, Milvus, SRS, EMQX, ZLMediaKit, GPUStack, Dify, and Node-RED in sequence
7. **Wait for base services** — Automatically waits for PostgreSQL / Nacos / Redis health checks to pass
8. **Deploy DEVICE services** — Builds and starts Java microservice cluster (gateway + 8 business services)
9. **Deploy AI service** — Builds and starts Python AI inference service
10. **Deploy VIDEO service** — Builds and starts Python video processing service and 6 sub-services
11. **Deploy WEB frontend** — Builds and starts Vue 3 frontend

### 2.3 Verify Deployment

```bash
# Verify all services started successfully
.scripts/docker/install_linux.sh verify
```

On success, access URLs for all services are displayed:

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

### 2.4 Access the System

Open `http://<server-IP>:8888` in a browser to access the EasyAIoT management platform.

---

## 3. Step-by-Step Deployment (Manual Operations)

For finer-grained control, deploy by module step by step.

### 3.1 Step 1: Deploy Middleware

```bash
cd .scripts/docker
./install_middleware_linux.sh install
```

**Middleware inventory:**

| Middleware | Image | Port | Purpose |
|--------|------|------|------|
| Nacos | nacos/nacos-server:v2.5.1 | 8848, 9848, 9849 | Service registry and configuration center |
| PostgreSQL | postgres:18 | 5432 | Primary database (6 business databases) |
| TDengine | tdengine/tsdb:3.3.8.4 | 6030, 6041, 6060 | Time-series database |
| Redis | redis:7.4.8 | 6379 | Cache and distributed locks |
| Kafka | apache/kafka:3.8.0 | 9092, 9093, 9094 | Message queue |
| MinIO | minio/minio | 9000, 9001 | Object storage |
| Milvus | milvusdb/milvus:v2.6.0 | 19530, 9091 | Vector database (face recognition) |
| SRS | ossrs/srs:5 | 1935, 1985 | Streaming media server |
| EMQX | emqx/emqx:5.8.7 | 1883, 8083, 18083 | MQTT Broker |
| ZLMediaKit | zlmediakit/zlmediakit:master | 6080, 5540, 10935 | Media server |
| GPUStack | gpustack/gpustack:v2.1.2 | 10180 | GPU resource management |
| Dify | dify-api / dify-web / ... | 10190 | LLM application platform |
| Node-RED | nodered/node-red:latest | 1880 | Rule engine |

Wait for middleware to become ready:

```bash
# Check PostgreSQL
docker exec postgres-server pg_isready -U postgres

# Check Nacos
curl -s http://localhost:8848/nacos/actuator/health

# Check Redis
docker exec redis-server redis-cli -a basiclab@iot975248395 ping
```

### 3.2 Step 2: Deploy DEVICE Services

```bash
cd DEVICE
./install_linux.sh install
```

**DEVICE service inventory:**

| Service | Port | Description |
|------|------|------|
| iot-gateway | 48080 | API gateway (Spring Cloud Gateway) |
| iot-system | 48099 | System management |
| iot-infra | 48066 | Infrastructure |
| iot-device | 48055 | Device management |
| iot-dataset | 48077 | Dataset management |
| iot-message | 48033 | Message push |
| iot-file | 48022 | File service |
| iot-sink | 48011 | Protocol adapter (MQTT/TCP/HTTP/EMQX) |
| iot-gb28181 | 5060 | GB28181 video surveillance protocol |

**Build approach:**
- Two-stage build: `Dockerfile.base` (Maven dependency cache) → per-module `Dockerfile`
- Java 21 + Spring Boot 2.7.18
- Build cache directory: `.build-cache/device/m2/repository`

### 3.3 Step 3: Deploy AI Service

```bash
cd AI
./install_linux.sh install
```

**AI service overview:**
- Port: 5000
- Framework: Flask + PyTorch 2.9+ (CUDA 12.8)
- Features: Model training, inference, deployment, OCR, speech, LLM
- GPU support: Automatically detects GPU and enables NVIDIA Container Runtime
- Build cache: `.build-cache/ai/pip-cache`, `.build-cache/ai/pip-wheels`
- Base image: `pytorch/pytorch:2.9.0-cuda12.8-cudnn9-devel`

### 3.4 Step 4: Deploy VIDEO Service

```bash
cd VIDEO
./install_linux.sh install
```

**VIDEO service overview:**
- Port: 6000
- Framework: Flask + OpenCV + FFmpeg
- Features: Video stream processing, real-time/snapshot algorithm analysis, recording, alerts, face recognition
- Sub-services: 6 independent microservices (real-time algorithm, snapshot algorithm, frame extraction, sorting, push stream, stream forwarding)
- Message queue: Kafka (alert events)
- Vector database: Milvus (face recognition)

### 3.5 Step 5: Deploy WEB Frontend

```bash
cd WEB
./install_linux.sh install
```

**WEB frontend overview:**
- Port: 8888
- Framework: Vue 3.4 + TypeScript + Vite
- UI library: Ant Design Vue 4.0
- Build: Node.js 18+ / 20+, pnpm 11.3+

---

## 4. Single-Module Management

Each module supports the following commands:

```bash
./install_linux.sh install    # Install and start (first run)
./install_linux.sh start      # Start
./install_linux.sh stop       # Stop
./install_linux.sh restart    # Restart
./install_linux.sh status     # View status
./install_linux.sh logs       # View logs
./install_linux.sh build      # Rebuild images
./install_linux.sh clean      # Clean up containers and images
./install_linux.sh update     # Update and restart
```

**Middleware management:**

```bash
cd .scripts/docker
./install_middleware_linux.sh install    # Install all middleware
./install_middleware_linux.sh start      # Start
./install_middleware_linux.sh stop       # Stop
./install_middleware_linux.sh status     # Status
./install_middleware_linux.sh logs       # Logs
```

---

## 5. GPU Configuration

### 5.1 Install NVIDIA Driver

```bash
# Check GPU availability
nvidia-smi

# Install NVIDIA Container Toolkit
# Reference: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

# Verify Docker GPU support
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi
```

### 5.2 Automatic GPU Detection

The install script automatically detects GPU:
- GPU detected → Automatically enables `runtime: nvidia`, sets `NVIDIA_VISIBLE_DEVICES=all`
- No GPU detected → Runs in CPU mode

### 5.3 Multi-GPU Configuration

The AI service supports multi-GPU parallel inference, controlled via environment variables:

```bash
# Use GPU 0 and 1
export CUDA_VISIBLE_DEVICES=0,1
```

---

## 6. Domestic Platform Adaptation

### 6.1 Kylin Operating System

```bash
.scripts/docker/install_linux_kylin.sh install
```

### 6.2 ARM64 Architecture

```bash
# Middleware
.scripts/docker/install_linux_arm.sh install

# AI service (ARM Dockerfile)
cd AI
./install_linux.sh install  # Script automatically selects ARM Dockerfile
```

---

## 7. Database Overview

### 7.1 PostgreSQL Business Databases

PostgreSQL automatically creates the following 6 business databases on startup:

| Database | SQL File | Purpose |
|------|---------|------|
| ruoyi-vue-pro20 | ruoyi-vue-pro10.sql | System management primary database |
| iot-ai20 | iot-ai10.sql | AI service database |
| iot-device10 | iot-device10.sql | Device management database |
| iot-gb2818110 | iot-gb2818110.sql | Video surveillance database |
| iot-message10 | iot-message10.sql | Message push database |
| iot-video10 | iot-video10.sql | Video processing database |

Initialization scripts are located in `.scripts/postgresql/` and are executed automatically via `docker-entrypoint-initdb.d` on Docker startup.

### 7.2 TDengine Time-Series Database

TDengine automatically initializes super tables on startup. SQL files are located at `.scripts/tdengine/tdengine_super_tables.sql`.

### 7.3 Database Backup

```bash
# Back up all databases
.scripts/postgresql/backup_databases.sh
```

---

## 8. Middleware Default Credentials

| Middleware | Username | Password | Console URL |
|--------|--------|------|-----------|
| Nacos | nacos | nacos | http://<IP>:8848/nacos |
| PostgreSQL | postgres | iot45722414822 | — |
| Redis | — | basiclab@iot975248395 | — |
| MinIO | minioadmin | basiclab@iot975248395 | http://<IP>:9001 |
| EMQX | admin | basiclab@iot6874125784 | http://<IP>:18083 |
| GPUStack | admin | basiclab@iotp4JWmQSvzdh0z4mF | http://<IP>:10180 |
| Milvus | — | — | http://<IP>:9091 |

> ⚠️ **Security notice**: Change all default passwords in production environments.

---

## 9. Troubleshooting

### 9.1 Service Startup Failures

```bash
# View logs for a specific service
docker logs -f postgres-server
docker logs -f nacos-server
docker logs -f ai-service
docker logs -f video-service

# View status of all services
docker ps -a
```

### 9.2 Network Issues

```bash
# Check Docker network
docker network ls | grep easyaiot
docker network inspect easyaiot-network

# Recreate network (after host IP changes)
docker network rm easyaiot-network
docker network create easyaiot-network
docker compose restart
```

### 9.3 PostgreSQL Connection Issues

```bash
# Automatic fix
.scripts/docker/fix_postgresql.sh

# Manual check
docker exec postgres-server pg_isready -U postgres
docker exec postgres-server psql -U postgres -c "SELECT 1;"
```

### 9.4 Redis Connection Issues

```bash
# Automatic fix
.scripts/docker/fix_redis.sh

# Manual check
docker exec redis-server redis-cli -a basiclab@iot975248395 ping
```

### 9.5 Docker Service Issues

```bash
# Diagnose Docker systemd issues
sudo .scripts/docker/diagnose_docker_systemd.sh diagnose

# Fix systemd timeout
sudo .scripts/docker/diagnose_docker_systemd.sh fix-all

# Check disk space
df -h
docker system df

# Clean up Docker artifacts
.scripts/docker/cleanup_docker_space.sh
```

### 9.6 Kafka Consumer Group Issues

```bash
# Fix Kafka consumer group
cd VIDEO
python fix_kafka_consumer_group.py
```

### 9.7 Port Conflicts

```bash
# Check port usage
ss -tlnp | grep -E "8848|5432|6379|9092|5000|6000|8888"

# If conflicts exist, modify port mappings in the corresponding docker-compose.yml
```

---

## 10. Log File Locations

| Location | Description |
|------|------|
| `.scripts/docker/logs/` | Install script logs |
| `DEVICE/logs/` | DEVICE service logs |
| `AI/data/logs/` | AI service logs |
| `VIDEO/data/logs/` | VIDEO service logs |
| `docker logs <container-name>` | Container live logs |

---

## 11. Updates and Upgrades

### 11.1 Update Source Code

```bash
cd easyaiot
git pull origin main
```

### 11.2 Update and Restart All Services

```bash
sudo .scripts/docker/install_linux.sh update
```

### 11.3 Update a Single Module

```bash
# Example: update AI service only
cd AI
./install_linux.sh update
```

### 11.4 Rebuild Images

```bash
# Rebuild all images
sudo .scripts/docker/install_linux.sh build

# Rebuild a single module
cd DEVICE
./install_linux.sh build
```

---

## 12. Uninstall

```bash
# Stop and remove all containers, images, and networks
sudo .scripts/docker/install_linux.sh clean

# Manually clean data volumes (optional)
rm -rf .scripts/docker/db_data
rm -rf .scripts/docker/redis_data
rm -rf .scripts/docker/minio_data
rm -rf .scripts/docker/mq_data
rm -rf .scripts/docker/taos_data
rm -rf .scripts/docker/milvus_data
rm -rf .scripts/docker/gpustack_data
```

---

## 13. Architecture Reference

```
┌─────────────────────────────────────────────────────────────────┐
│                    WEB Frontend (:8888)                          │
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
│  AI Service (:5000)      │  VIDEO Service (:6000) │  TASK (C++)  │
│  Flask + PyTorch + YOLO  │  Flask + OpenCV + FFmpeg│  ONNX Runtime│
│  Train/Infer/Deploy/OCR/LLM│ Stream/Alert/Record/Face│ Edge inference│
├──────────────────────────┴───────────────────────┴──────────────┤
│                     Middleware Layer                               │
│  Nacos │ PostgreSQL │ Redis │ Kafka │ MinIO │ TDengine          │
│  Milvus │ SRS │ EMQX │ ZLMediaKit │ GPUStack │ Dify │ Node-RED  │
└─────────────────────────────────────────────────────────────────┘
```

---

*Document generated: 2026-05-31 | Project: https://gitee.com/volara/easyaiot*
