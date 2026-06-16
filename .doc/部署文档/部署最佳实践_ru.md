# Руководство по развёртыванию EasyAIoT

> Документ сформирован на основе анализа исходного кода проекта; подходит для развёртывания в один клик в среде Linux.

---

## 1. Требования к окружению

### 1.1 Аппаратные требования

| Ресурс | Минимальная конфигурация | Рекомендуемая конфигурация |
|------|---------|---------|
| CPU | 4 ядра | 8 ядер+ |
| Память | 8 GB | 16 GB+ |
| Диск | 100 GB | 500 GB+ SSD |
| GPU | Нет (можно на CPU) | NVIDIA GPU (CUDA 12.8) |

### 1.2 Программные требования

| ПО | Минимальная версия | Примечание |
|------|---------|------|
| ОС | Ubuntu 20.04 / CentOS 7 | Рекомендуется Ubuntu 22.04 LTS |
| Docker | 20.10+ | Требуется поддержка `docker compose` v2 |
| Docker Compose | v2 | Устанавливается с Docker Desktop или отдельно |
| NVIDIA Driver | 525+ | Только для сценариев с GPU |
| NVIDIA Container Toolkit | Последняя версия | Только для сценариев с GPU |

### 1.3 Требования к портам

Перед развёртыванием убедитесь, что следующие порты свободны:

| Порт | Сервис | Примечание |
|------|------|------|
| 1880 | Node-RED | Движок правил |
| 1883 | EMQX | MQTT Broker |
| 1935 | SRS | Потоковое RTMP |
| 5432 | PostgreSQL | Основная БД |
| 6000 | VIDEO 服务 | Обработка видео |
| 6030 | TDengine | Временная БД |
| 6080 | ZLMediaKit | Медиасервер |
| 6379 | Redis | Кэш |
| 8848 | Nacos | Регистрация/конфигурация |
| 8888 | WEB 前端 | Веб-интерфейс |
| 9000 | MinIO API | Объектное хранилище |
| 9001 | MinIO Console | Консоль объектного хранилища |
| 9092 | Kafka | Очередь сообщений |
| 10180 | GPUStack | Управление GPU |
| 10190 | Dify | Платформа LLM-приложений |
| 19530 | Milvus | Векторная БД |
| 48080 | API Gateway | Шлюз бэкенда |
| 5000 | AI 服务 | AI-инференс |

---

## 2. Быстрое развёртывание (установка в один клик)

### 2.1 Получение исходного кода

```bash
git clone https://gitee.com/volara/easyaiot.git
cd easyaiot
```

### 2.2 Установка в один клик

```bash
# 需要 root 权限（用于配置 Docker 镜像源、RTP 端口预留等）
sudo .scripts/docker/install_linux.sh install
```

Эта команда автоматически выполняет следующие шаги:

1. **Проверка окружения** — проверка установки Docker / Docker Compose
2. **Определение IP** — автоматическое определение IP хоста (для инъекции медиа-адресов GB28181/ZLMediaKit)
3. **Резервирование RTP-портов** — настройка ядра Linux: зарезервированы порты 30000-30500 (чтобы не занимались временными портами)
4. **Настройка зеркала Docker** — автоматическая настройка ускорения образов `docker.m.daocloud.io` ([публичное зеркало DaoCloud](https://github.com/DaoCloud/public-image-mirror))
5. **Создание сети Docker** — единая сеть `easyaiot-network`
6. **Развёртывание middleware** — последовательный запуск Nacos, PostgreSQL, Redis, Kafka, MinIO, TDengine, Milvus, SRS, EMQX, ZLMediaKit, GPUStack, Dify, Node-RED
7. **Ожидание готовности базовых сервисов** — автоматическое ожидание прохождения health check PostgreSQL / Nacos / Redis
8. **Развёртывание DEVICE** — сборка и запуск кластера Java-микросервисов (шлюз + 8 бизнес-сервисов)
9. **Развёртывание AI** — сборка и запуск Python-сервиса AI-инференса
10. **Развёртывание VIDEO** — сборка и запуск Python-сервиса обработки видео и 6 подсервисов
11. **Развёртывание WEB** — сборка и запуск фронтенда Vue 3

### 2.3 Проверка развёртывания

```bash
# 验证所有服务是否启动成功
.scripts/docker/install_linux.sh verify
```

При успехе отображаются адреса доступа ко всем сервисам:

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

### 2.4 Доступ к системе

Откройте в браузере `http://<服务器IP>:8888` для доступа к платформе управления EasyAIoT.

---

## 3. Пошаговое развёртывание (ручные операции)

При необходимости более тонкого контроля можно разворачивать по модулям.

### 3.1 Шаг 1: развёртывание middleware

```bash
cd .scripts/docker
./install_middleware_linux.sh install
```

**Список middleware:**

| Middleware | Образ | Порт | Назначение |
|--------|------|------|------|
| Nacos | nacos/nacos-server:v2.5.1 | 8848, 9848, 9849 | Регистрация сервисов и центр конфигурации |
| PostgreSQL | postgres:18 | 5432 | Основная БД (6 бизнес-баз) |
| TDengine | tdengine/tsdb:3.3.8.4 | 6030, 6041, 6060 | Временная БД |
| Redis | redis:7.4.8 | 6379 | Кэш и распределённые блокировки |
| Kafka | apache/kafka:3.8.0 | 9092, 9093, 9094 | Очередь сообщений |
| MinIO | minio/minio | 9000, 9001 | Объектное хранилище |
| Milvus | milvusdb/milvus:v2.6.0 | 19530, 9091 | Векторная БД (распознавание лиц) |
| SRS | ossrs/srs:5 | 1935, 1985 | Потоковый сервер |
| EMQX | emqx/emqx:5.8.7 | 1883, 8083, 18083 | MQTT Broker |
| ZLMediaKit | zlmediakit/zlmediakit:master | 6080, 5540, 10935 | Медиасервер |
| GPUStack | gpustack/gpustack:v2.1.2 | 10180 | Управление ресурсами GPU |
| Dify | dify-api / dify-web / ... | 10190 | Платформа LLM-приложений |
| Node-RED | nodered/node-red:latest | 1880 | Движок правил |

Ожидание готовности middleware:

```bash
# 检查 PostgreSQL
docker exec postgres-server pg_isready -U postgres

# 检查 Nacos
curl -s http://localhost:8848/nacos/actuator/health

# 检查 Redis
docker exec redis-server redis-cli -a basiclab@iot975248395 ping
```

### 3.2 Шаг 2: развёртывание DEVICE

```bash
cd DEVICE
./install_linux.sh install
```

**Список сервисов DEVICE:**

| Сервис | Порт | Примечание |
|------|------|------|
| iot-gateway | 48080 | API-шлюз (Spring Cloud Gateway) |
| iot-system | 48099 | Управление системой |
| iot-infra | 48066 | Инфраструктура |
| iot-device | 48055 | Управление устройствами |
| iot-dataset | 48077 | Управление наборами данных |
| iot-message | 48033 | Push-уведомления |
| iot-file | 48022 | Файловый сервис |
| iot-sink | 48011 | Адаптация протоколов (MQTT/TCP/HTTP/EMQX) |
| iot-gb28181 | 5060 | Протокол видеонаблюдения GB28181 |

**Способ сборки:**
- Двухэтапная сборка: `Dockerfile.base` (кэш зависимостей Maven) → `Dockerfile` каждого модуля
- Java 21 + Spring Boot 2.7.18
- Каталог кэша сборки: `.build-cache/device/m2/repository`

### 3.3 Шаг 3: развёртывание AI

```bash
cd AI
./install_linux.sh install
```

**Описание AI-сервиса:**
- Порт: 5000
- Стек: Flask + PyTorch 2.9+ (CUDA 12.8)
- Функции: обучение моделей, инференс, развёртывание, OCR, речь, LLM
- GPU: автоматическое обнаружение GPU и включение NVIDIA Container Runtime
- Кэш сборки: `.build-cache/ai/pip-cache`、`.build-cache/ai/pip-wheels`
- Базовый образ: `pytorch/pytorch:2.9.0-cuda12.8-cudnn9-devel`

### 3.4 Шаг 4: развёртывание VIDEO

```bash
cd VIDEO
./install_linux.sh install
```

**Описание VIDEO-сервиса:**
- Порт: 6000
- Стек: Flask + OpenCV + FFmpeg
- Функции: обработка видеопотоков, анализ в реальном времени/по снимкам, запись, оповещения, распознавание лиц
- Подсервисы: 6 независимых микросервисов (алгоритм в реальном времени, по снимкам, извлечение кадров, сортировка, push потока, пересылка потока)
- Очередь сообщений: Kafka (события оповещений)
- Векторная БД: Milvus (распознавание лиц)

### 3.5 Шаг 5: развёртывание WEB

```bash
cd WEB
./install_linux.sh install
```

**Описание WEB-фронтенда:**
- Порт: 8888
- Стек: Vue 3.4 + TypeScript + Vite
- UI: Ant Design Vue 4.0
- Сборка: Node.js 18+ / 20+，pnpm 11.3+

---

## 4. Управление отдельными модулями

Каждый модуль поддерживает следующие команды:

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

**Отдельное управление middleware:**

```bash
cd .scripts/docker
./install_middleware_linux.sh install    # 安装所有中间件
./install_middleware_linux.sh start      # 启动
./install_middleware_linux.sh stop       # 停止
./install_middleware_linux.sh status     # 状态
./install_middleware_linux.sh logs       # 日志
```

---

## 5. Настройка GPU

### 5.1 Установка драйвера NVIDIA

```bash
# 检查 GPU 是否可用
nvidia-smi

# 安装 NVIDIA Container Toolkit
# 参考：https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

# 验证 Docker GPU 支持
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi
```

### 5.2 Автоопределение GPU

Скрипт установки автоматически определяет GPU:
- GPU обнаружен → автоматически включается `runtime: nvidia`, задаётся `NVIDIA_VISIBLE_DEVICES=all`
- GPU не обнаружен → работа в режиме CPU

### 5.3 Конфигурация нескольких GPU

AI-сервис поддерживает параллельный инференс на нескольких GPU через переменные окружения:

```bash
# 指定使用 GPU 0 和 1
export CUDA_VISIBLE_DEVICES=0,1
```

---

## 6. Адаптация для отечественных платформ

### 6.1 Kylin OS

```bash
.scripts/docker/install_linux_kylin.sh install
```

### 6.2 Архитектура ARM64

```bash
# 中间件
.scripts/docker/install_linux_arm.sh install

# AI 服务（ARM 版 Dockerfile）
cd AI
./install_linux.sh install  # 脚本会自动选择 ARM Dockerfile
```

---

## 7. Описание баз данных

### 7.1 Бизнес-базы PostgreSQL

При запуске PostgreSQL автоматически создаются следующие 6 бизнес-баз:

| Имя БД | SQL-файл | Назначение |
|------|---------|------|
| ruoyi-vue-pro20 | ruoyi-vue-pro10.sql | Основная БД управления системой |
| iot-ai20 | iot-ai10.sql | БД AI-сервиса |
| iot-device10 | iot-device10.sql | БД управления устройствами |
| iot-gb2818110 | iot-gb2818110.sql | БД видеонаблюдения |
| iot-message10 | iot-message10.sql | БД push-сообщений |
| iot-video10 | iot-video10.sql | БД обработки видео |

Скрипты инициализации в каталоге `.scripts/postgresql/`; при запуске Docker выполняются через `docker-entrypoint-initdb.d`.

### 7.2 Временная БД TDengine

После запуска TDengine автоматически инициализируются супертаблицы; SQL-файл: `.scripts/tdengine/tdengine_super_tables.sql`.

### 7.3 Резервное копирование БД

```bash
# 备份所有数据库
.scripts/postgresql/backup_databases.sh
```

---

## 8. Учётные данные middleware по умолчанию

| Middleware | Имя пользователя | Пароль | Адрес консоли |
|--------|--------|------|-----------|
| Nacos | nacos | nacos | http://<IP>:8848/nacos |
| PostgreSQL | postgres | iot45722414822 | — |
| Redis | — | basiclab@iot975248395 | — |
| MinIO | minioadmin | basiclab@iot975248395 | http://<IP>:9001 |
| EMQX | admin | basiclab@iot6874125784 | http://<IP>:18083 |
| GPUStack | admin | basiclab@iotp4JWmQSvzdh0z4mF | http://<IP>:10180 |
| Milvus | — | — | http://<IP>:9091 |

> ⚠️ **Предупреждение безопасности**: в production обязательно смените все пароли по умолчанию.

---

## 9. Устранение неполадок

### 9.1 Сбой запуска сервиса

```bash
# 查看具体服务日志
docker logs -f postgres-server
docker logs -f nacos-server
docker logs -f ai-service
docker logs -f video-service

# 查看所有服务状态
docker ps -a
```

### 9.2 Проблемы с сетью

```bash
# 检查 Docker 网络
docker network ls | grep easyaiot
docker network inspect easyaiot-network

# 重建网络（宿主机 IP 变化后）
docker network rm easyaiot-network
docker network create easyaiot-network
docker compose restart
```

### 9.3 Проблемы подключения к PostgreSQL

```bash
# 自动修复
.scripts/docker/fix_postgresql.sh

# 手动检查
docker exec postgres-server pg_isready -U postgres
docker exec postgres-server psql -U postgres -c "SELECT 1;"
```

### 9.4 Проблемы подключения к Redis

```bash
# 自动修复
.scripts/docker/fix_redis.sh

# 手动检查
docker exec redis-server redis-cli -a basiclab@iot975248395 ping
```

### 9.5 Проблемы сервиса Docker

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

### 9.6 Проблемы группы потребителей Kafka

```bash
# 修复 Kafka 消费组
cd VIDEO
python fix_kafka_consumer_group.py
```

### 9.7 Конфликт портов

```bash
# 检查端口占用
ss -tlnp | grep -E "8848|5432|6379|9092|5000|6000|8888"

# 如有冲突，修改对应 docker-compose.yml 中的端口映射
```

---

## 10. Расположение файлов логов

| Расположение | Примечание |
|------|------|
| `.scripts/docker/logs/` | Логи скриптов установки |
| `DEVICE/logs/` | Логи сервисов DEVICE |
| `AI/data/logs/` | Логи AI-сервиса |
| `VIDEO/data/logs/` | Логи VIDEO-сервиса |
| `docker logs <容器名>` | Логи контейнера в реальном времени |

---

## 11. Обновление и апгрейд

### 11.1 Обновление кода

```bash
cd easyaiot
git pull origin main
```

### 11.2 Обновление и перезапуск всех сервисов

```bash
sudo .scripts/docker/install_linux.sh update
```

### 11.3 Обновление одного модуля

```bash
# 例如只更新 AI 服务
cd AI
./install_linux.sh update
```

### 11.4 Пересборка образов

```bash
# 重新构建所有镜像
sudo .scripts/docker/install_linux.sh build

# 重新构建单个模块
cd DEVICE
./install_linux.sh build
```

---

## 12. Удаление

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

## 13. Справка по архитектуре

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
│  Обучение/инференс/развёртывание/OCR/LLM  │  Потоки/оповещения/запись/лица  │  Инференс на краю    │
├──────────────────────────┴───────────────────────┴──────────────┤
│                     Слой middleware                                     │
│  Nacos │ PostgreSQL │ Redis │ Kafka │ MinIO │ TDengine          │
│  Milvus │ SRS │ EMQX │ ZLMediaKit │ GPUStack │ Dify │ Node-RED  │
└─────────────────────────────────────────────────────────────────┘
```

---

*Дата создания документа: 2026-05-31 | Проект: https://gitee.com/volara/easyaiot*
