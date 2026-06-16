# EasyAIoT 배포 가이드

> 본 문서는 프로젝트 소스 코드 분석을 기반으로 생성되었으며, Linux 환경에서 원클릭 배포에 적용됩니다.

---

## 1. 환경 요구사항

### 1.1 하드웨어 요구사항

| 리소스 | 최소 구성 | 권장 구성 |
|------|---------|---------|
| CPU | 4코어 | 8코어+ |
| 메모리 | 8 GB | 16 GB+ |
| 디스크 | 100 GB | 500 GB+ SSD |
| GPU | 없음 (CPU로 실행 가능) | NVIDIA GPU (CUDA 12.8) |

### 1.2 소프트웨어 요구사항

| 소프트웨어 | 최소 버전 | 설명 |
|------|---------|------|
| 운영체제 | Ubuntu 20.04 / CentOS 7 | Ubuntu 22.04 LTS 권장 |
| Docker | 20.10+ | `docker compose` v2 지원 필요 |
| Docker Compose | v2 | Docker Desktop과 함께 자동 설치 또는 별도 설치 |
| NVIDIA Driver | 525+ | GPU 환경에서만 필요 |
| NVIDIA Container Toolkit | 최신 버전 | GPU 환경에서만 필요 |

### 1.3 포트 요구사항

배포 전 다음 포트가 사용 중이 아닌지 확인하세요:

| 포트 | 서비스 | 설명 |
|------|------|------|
| 1880 | Node-RED | 규칙 엔진 |
| 1883 | EMQX | MQTT Broker |
| 1935 | SRS | 스트리밍 RTMP |
| 5432 | PostgreSQL | 주 데이터베이스 |
| 6000 | VIDEO 서비스 | 비디오 처리 |
| 6030 | TDengine | 시계열 데이터베이스 |
| 6080 | ZLMediaKit | 미디어 서버 |
| 6379 | Redis | 캐시 |
| 8848 | Nacos | 등록/설정 센터 |
| 8888 | WEB 프론트엔드 | 관리 인터페이스 |
| 9000 | MinIO API | 객체 스토리지 |
| 9001 | MinIO Console | 객체 스토리지 콘솔 |
| 9092 | Kafka | 메시지 큐 |
| 10180 | GPUStack | GPU 관리 |
| 10190 | Dify | LLM 애플리케이션 플랫폼 |
| 19530 | Milvus | 벡터 데이터베이스 |
| 48080 | API Gateway | 백엔드 게이트웨이 |
| 5000 | AI 서비스 | AI 추론 |

---

## 2. 빠른 배포 (원클릭 설치)

### 2.1 소스 코드 가져오기

```bash
git clone https://gitee.com/volara/easyaiot.git
cd easyaiot
```

### 2.2 원클릭 설치

```bash
# root 권한 필요 (Docker 미러 소스 구성, RTP 포트 예약 등)
sudo .scripts/docker/install_linux.sh install
```

이 명령은 다음 절차를 자동으로 실행합니다:

1. **환경 검사** — Docker / Docker Compose 설치 여부 확인
2. **IP 감지** — 호스트 IP 자동 감지 (GB28181/ZLMediaKit 미디어 주소 주입용)
3. **RTP 포트 예약** — Linux 커널 예약 포트 30000-30500 구성 (임시 포트 점유 방지)
4. **Docker 미러 소스 구성** — `docker.m.daocloud.io` 자동 구성으로 이미지 가속 ([DaoCloud 공개 미러](https://github.com/DaoCloud/public-image-mirror))
5. **Docker 네트워크 생성** — 통합 네트워크 `easyaiot-network` 생성
6. **미들웨어 배포** — Nacos, PostgreSQL, Redis, Kafka, MinIO, TDengine, Milvus, SRS, EMQX, ZLMediaKit, GPUStack, Dify, Node-RED 순차 기동
7. **기본 서비스 준비 대기** — PostgreSQL / Nacos / Redis 헬스 체크 통과 자동 대기
8. **DEVICE 서비스 배포** — Java 마이크로서비스 클러스터 빌드 및 기동 (게이트웨이 + 8개 비즈니스 서비스)
9. **AI 서비스 배포** — Python AI 추론 서비스 빌드 및 기동
10. **VIDEO 서비스 배포** — Python 비디오 처리 서비스 및 6개 하위 서비스 빌드 및 기동
11. **WEB 프론트엔드 배포** — Vue 3 프론트엔드 빌드 및 기동

### 2.3 배포 검증

```bash
# 모든 서비스가 성공적으로 시작되었는지 확인
.scripts/docker/install_linux.sh verify
```

성공 시 모든 서비스의 접속 주소가 표시됩니다:

```
서비스 접속 주소:
  기본 서비스 (Nacos):     http://localhost:8848/nacos
  기본 서비스 (MinIO):     http://localhost:9000 (API), http://localhost:9001 (Console)
  기본 서비스 (Milvus):    http://localhost:9091 (Health), localhost:19530 (gRPC)
  기본 서비스 (GPUStack):  http://localhost:10180  (사용자 admin)
  Device 서비스 (Gateway): http://localhost:48080
  AI 서비스:               http://localhost:5000
  Video 서비스:            http://localhost:6000
  Web 프론트엔드:          http://localhost:8888
```

### 2.4 시스템 접속

브라우저에서 `http://<服务器IP>:8888`을 열면 EasyAIoT 관리 플랫폼에 접속할 수 있습니다.

---

## 3. 단계별 배포 (수동 작업)

더 세밀한 제어가 필요한 경우 모듈별로 단계적으로 배포할 수 있습니다.

### 3.1 1단계: 미들웨어 배포

```bash
cd .scripts/docker
./install_middleware_linux.sh install
```

**미들웨어 목록:**

| 미들웨어 | 이미지 | 포트 | 용도 |
|--------|------|------|------|
| Nacos | nacos/nacos-server:v2.5.1 | 8848, 9848, 9849 | 서비스 등록 및 설정 센터 |
| PostgreSQL | postgres:18 | 5432 | 주 데이터베이스 (6개 비즈니스 DB) |
| TDengine | tdengine/tsdb:3.3.8.4 | 6030, 6041, 6060 | 시계열 데이터베이스 |
| Redis | redis:7.4.8 | 6379 | 캐시 및 분산 잠금 |
| Kafka | apache/kafka:3.8.0 | 9092, 9093, 9094 | 메시지 큐 |
| MinIO | minio/minio | 9000, 9001 | 객체 스토리지 |
| Milvus | milvusdb/milvus:v2.6.0 | 19530, 9091 | 벡터 데이터베이스 (얼굴 인식) |
| SRS | ossrs/srs:5 | 1935, 1985 | 스트리밍 서버 |
| EMQX | emqx/emqx:5.8.7 | 1883, 8083, 18083 | MQTT Broker |
| ZLMediaKit | zlmediakit/zlmediakit:master | 6080, 5540, 10935 | 미디어 서버 |
| GPUStack | gpustack/gpustack:v2.1.2 | 10180 | GPU 리소스 관리 |
| Dify | dify-api / dify-web / ... | 10190 | LLM 애플리케이션 플랫폼 |
| Node-RED | nodered/node-red:latest | 1880 | 규칙 엔진 |

미들웨어 준비 완료 대기:

```bash
# PostgreSQL 확인
docker exec postgres-server pg_isready -U postgres

# Nacos 확인
curl -s http://localhost:8848/nacos/actuator/health

# Redis 확인
docker exec redis-server redis-cli -a basiclab@iot975248395 ping
```

### 3.2 2단계: DEVICE 서비스 배포

```bash
cd DEVICE
./install_linux.sh install
```

**DEVICE 서비스 목록:**

| 서비스 | 포트 | 설명 |
|------|------|------|
| iot-gateway | 48080 | API 게이트웨이 (Spring Cloud Gateway) |
| iot-system | 48099 | 시스템 관리 |
| iot-infra | 48066 | 인프라 |
| iot-device | 48055 | 디바이스 관리 |
| iot-dataset | 48077 | 데이터셋 관리 |
| iot-message | 48033 | 메시지 푸시 |
| iot-file | 48022 | 파일 서비스 |
| iot-sink | 48011 | 프로토콜 어댑터 (MQTT/TCP/HTTP/EMQX) |
| iot-gb28181 | 5060 | GB28181 비디오 감시 프로토콜 |

**빌드 방식:**
- 2단계 빌드: `Dockerfile.base` (Maven 의존성 캐시) → 각 모듈 `Dockerfile`
- Java 21 + Spring Boot 2.7.18
- 빌드 캐시 디렉터리: `.build-cache/device/m2/repository`

### 3.3 3단계: AI 서비스 배포

```bash
cd AI
./install_linux.sh install
```

**AI 서비스 설명:**
- 포트: 5000
- 프레임워크: Flask + PyTorch 2.9+ (CUDA 12.8)
- 기능: 모델 학습, 추론, 배포, OCR, 음성, LLM
- GPU 지원: GPU 자동 감지 및 NVIDIA Container Runtime 활성화
- 빌드 캐시: `.build-cache/ai/pip-cache`、`.build-cache/ai/pip-wheels`
- 기본 이미지: `pytorch/pytorch:2.9.0-cuda12.8-cudnn9-devel`

### 3.4 4단계: VIDEO 서비스 배포

```bash
cd VIDEO
./install_linux.sh install
```

**VIDEO 서비스 설명:**
- 포트: 6000
- 프레임워크: Flask + OpenCV + FFmpeg
- 기능: 비디오 스트림 처리, 실시간/스냅샷 알고리즘 분석, 녹화, 알람, 얼굴 인식
- 하위 서비스: 6개 독립 마이크로서비스 (실시간 알고리즘, 스냅샷 알고리즘, 프레임 추출, 정렬, 스트림 푸시, 스트림 포워딩)
- 메시지 큐: Kafka (알람 이벤트)
- 벡터 데이터베이스: Milvus (얼굴 인식)

### 3.5 5단계: WEB 프론트엔드 배포

```bash
cd WEB
./install_linux.sh install
```

**WEB 프론트엔드 설명:**
- 포트: 8888
- 프레임워크: Vue 3.4 + TypeScript + Vite
- UI 라이브러리: Ant Design Vue 4.0
- 빌드: Node.js 18+ / 20+，pnpm 11.3+

---

## 4. 단일 모듈 관리

각 모듈은 다음 명령을 지원합니다:

```bash
./install_linux.sh install    # 설치 및 시작 (최초 실행)
./install_linux.sh start      # 시작
./install_linux.sh stop       # 중지
./install_linux.sh restart    # 재시작
./install_linux.sh status     # 상태 확인
./install_linux.sh logs       # 로그 확인
./install_linux.sh build      # 이미지 재빌드
./install_linux.sh clean      # 컨테이너 및 이미지 정리
./install_linux.sh update     # 업데이트 및 재시작
```

**미들웨어 개별 관리:**

```bash
cd .scripts/docker
./install_middleware_linux.sh install    # 모든 미들웨어 설치
./install_middleware_linux.sh start      # 시작
./install_middleware_linux.sh stop       # 중지
./install_middleware_linux.sh status     # 상태
./install_middleware_linux.sh logs       # 로그
```

---

## 5. GPU 구성

### 5.1 NVIDIA 드라이버 설치

```bash
# GPU 사용 가능 여부 확인
nvidia-smi

# NVIDIA Container Toolkit 설치
# 참고: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

# Docker GPU 지원 확인
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi
```

### 5.2 GPU 자동 감지

설치 스크립트가 GPU를 자동으로 감지합니다:
- GPU 감지됨 → `runtime: nvidia` 자동 활성화, `NVIDIA_VISIBLE_DEVICES=all` 설정
- GPU 미감지 → CPU 모드로 실행

### 5.3 다중 GPU 구성

AI 서비스는 환경 변수로 제어하는 다중 GPU 병렬 추론을 지원합니다:

```bash
# GPU 0과 1 사용 지정
export CUDA_VISIBLE_DEVICES=0,1
```

---

## 6. 국산화 적응

### 6.1 Kylin(은하기린) 운영체제

```bash
.scripts/docker/install_linux_kylin.sh install
```

### 6.2 ARM64 아키텍처

```bash
# 미들웨어
.scripts/docker/install_linux_arm.sh install

# AI 서비스 (ARM 버전 Dockerfile)
cd AI
./install_linux.sh install  # 스크립트가 ARM Dockerfile을 자동 선택
```

---

## 7. 데이터베이스 설명

### 7.1 PostgreSQL 비즈니스 DB

PostgreSQL 시작 시 다음 6개 비즈니스 DB가 자동으로 생성됩니다:

| DB명 | SQL 파일 | 용도 |
|------|---------|------|
| ruoyi-vue-pro20 | ruoyi-vue-pro10.sql | 시스템 관리 주 DB |
| iot-ai20 | iot-ai10.sql | AI 서비스 DB |
| iot-device10 | iot-device10.sql | 디바이스 관리 DB |
| iot-gb2818110 | iot-gb2818110.sql | 비디오 감시 DB |
| iot-message10 | iot-message10.sql | 메시지 푸시 DB |
| iot-video10 | iot-video10.sql | 비디오 처리 DB |

초기화 스크립트는 `.scripts/postgresql/` 디렉터리에 있으며, Docker 시작 시 `docker-entrypoint-initdb.d`를 통해 자동 실행됩니다.

### 7.2 TDengine 시계열 DB

TDengine 시작 후 슈퍼 테이블이 자동으로 초기화되며, SQL 파일은 `.scripts/tdengine/tdengine_super_tables.sql`에 있습니다.

### 7.3 데이터베이스 백업

```bash
# 모든 데이터베이스 백업
.scripts/postgresql/backup_databases.sh
```

---

## 8. 미들웨어 기본 계정 및 비밀번호

| 미들웨어 | 사용자명 | 비밀번호 | 콘솔 주소 |
|--------|--------|------|-----------|
| Nacos | nacos | nacos | http://<IP>:8848/nacos |
| PostgreSQL | postgres | iot45722414822 | — |
| Redis | — | basiclab@iot975248395 | — |
| MinIO | minioadmin | basiclab@iot975248395 | http://<IP>:9001 |
| EMQX | admin | basiclab@iot6874125784 | http://<IP>:18083 |
| GPUStack | admin | basiclab@iotp4JWmQSvzdh0z4mF | http://<IP>:10180 |
| Milvus | — | — | http://<IP>:9091 |

> ⚠️ **보안 안내**: 운영 환경에서는 반드시 모든 기본 비밀번호를 변경하세요.

---

## 9. 문제 해결

### 9.1 서비스 시작 실패

```bash
# 특정 서비스 로그 확인
docker logs -f postgres-server
docker logs -f nacos-server
docker logs -f ai-service
docker logs -f video-service

# 모든 서비스 상태 확인
docker ps -a
```

### 9.2 네트워크 문제

```bash
# Docker 네트워크 확인
docker network ls | grep easyaiot
docker network inspect easyaiot-network

# 네트워크 재생성 (호스트 IP 변경 후)
docker network rm easyaiot-network
docker network create easyaiot-network
docker compose restart
```

### 9.3 PostgreSQL 연결 문제

```bash
# 자동 복구
.scripts/docker/fix_postgresql.sh

# 수동 확인
docker exec postgres-server pg_isready -U postgres
docker exec postgres-server psql -U postgres -c "SELECT 1;"
```

### 9.4 Redis 연결 문제

```bash
# 자동 복구
.scripts/docker/fix_redis.sh

# 수동 확인
docker exec redis-server redis-cli -a basiclab@iot975248395 ping
```

### 9.5 Docker 서비스 문제

```bash
# Docker systemd 문제 진단
sudo .scripts/docker/diagnose_docker_systemd.sh diagnose

# systemd 타임아웃 복구
sudo .scripts/docker/diagnose_docker_systemd.sh fix-all

# 디스크 공간 확인
df -h
docker system df

# Docker 불필요 파일 정리
.scripts/docker/cleanup_docker_space.sh
```

### 9.6 Kafka 컨슈머 그룹 문제

```bash
# Kafka 컨슈머 그룹 복구
cd VIDEO
python fix_kafka_consumer_group.py
```

### 9.7 포트 충돌

```bash
# 포트 사용 여부 확인
ss -tlnp | grep -E "8848|5432|6379|9092|5000|6000|8888"

# 충돌 시 해당 docker-compose.yml의 포트 매핑 수정
```

---

## 10. 로그 파일 위치

| 위치 | 설명 |
|------|------|
| `.scripts/docker/logs/` | 설치 스크립트 로그 |
| `DEVICE/logs/` | DEVICE 서비스 로그 |
| `AI/data/logs/` | AI 서비스 로그 |
| `VIDEO/data/logs/` | VIDEO 서비스 로그 |
| `docker logs <컨테이너명>` | 컨테이너 실시간 로그 |

---

## 11. 업데이트 및 업그레이드

### 11.1 코드 업데이트

```bash
cd easyaiot
git pull origin main
```

### 11.2 모든 서비스 업데이트 및 재시작

```bash
sudo .scripts/docker/install_linux.sh update
```

### 11.3 단일 모듈 업데이트

```bash
# 예: AI 서비스만 업데이트
cd AI
./install_linux.sh update
```

### 11.4 이미지 재빌드

```bash
# 모든 이미지 재빌드
sudo .scripts/docker/install_linux.sh build

# 단일 모듈 재빌드
cd DEVICE
./install_linux.sh build
```

---

## 12. 제거

```bash
# 모든 컨테이너, 이미지 및 네트워크 중지 및 삭제
sudo .scripts/docker/install_linux.sh clean

# 데이터 볼륨 수동 정리 (선택)
rm -rf .scripts/docker/db_data
rm -rf .scripts/docker/redis_data
rm -rf .scripts/docker/minio_data
rm -rf .scripts/docker/mq_data
rm -rf .scripts/docker/taos_data
rm -rf .scripts/docker/milvus_data
rm -rf .scripts/docker/gpustack_data
```

---

## 13. 아키텍처 참고

```
┌─────────────────────────────────────────────────────────────────┐
│                    WEB 프론트엔드 (:8888)                        │
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
│  AI 서비스 (:5000)        │  VIDEO 서비스 (:6000)  │  TASK (C++)  │
│  Flask + PyTorch + YOLO  │  Flask + OpenCV + FFmpeg│  ONNX Runtime│
│  학습/추론/배포/OCR/LLM  │  스트림/알람/녹화/얼굴  │  엣지 추론   │
├──────────────────────────┴───────────────────────┴──────────────┤
│                     미들웨어 계층                                │
│  Nacos │ PostgreSQL │ Redis │ Kafka │ MinIO │ TDengine          │
│  Milvus │ SRS │ EMQX │ ZLMediaKit │ GPUStack │ Dify │ Node-RED  │
└─────────────────────────────────────────────────────────────────┘
```

---

*문서 생성일: 2026-05-31 | 프로젝트: https://gitee.com/volara/easyaiot*
