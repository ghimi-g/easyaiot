# Guide de déploiement EasyAIoT

> Ce document est généré à partir de l'analyse du code source du projet et s'applique au déploiement en un clic sur un environnement Linux.

---

## I. Exigences d'environnement

### 1.1 Exigences matérielles

| Ressource | Configuration minimale | Configuration recommandée |
|------|---------|---------|
| CPU | 4 cœurs | 8 cœurs+ |
| Mémoire | 8 GB | 16 GB+ |
| Disque | 100 GB | 500 GB+ SSD |
| GPU | Aucun (exécution possible en CPU) | GPU NVIDIA (CUDA 12.8) |

### 1.2 Exigences logicielles

| Logiciel | Version minimale | Description |
|------|---------|------|
| Système d'exploitation | Ubuntu 20.04 / CentOS 7 | Ubuntu 22.04 LTS recommandé |
| Docker | 20.10+ | Doit prendre en charge `docker compose` v2 |
| Docker Compose | v2 | Installé automatiquement avec Docker Desktop, ou installation indépendante |
| NVIDIA Driver | 525+ | Requis uniquement pour les scénarios GPU |
| NVIDIA Container Toolkit | Dernière version | Requis uniquement pour les scénarios GPU |

### 1.3 Exigences de ports

Avant le déploiement, assurez-vous que les ports suivants ne sont pas occupés :

| Port | Service | Description |
|------|------|------|
| 1880 | Node-RED | Moteur de règles |
| 1883 | EMQX | MQTT Broker |
| 1935 | SRS | Streaming RTMP |
| 5432 | PostgreSQL | Base de données principale |
| 6000 | Service VIDEO | Traitement vidéo |
| 6030 | TDengine | Base de données temporelle |
| 6080 | ZLMediaKit | Serveur média |
| 6379 | Redis | Cache |
| 8848 | Nacos | Centre d'enregistrement/configuration |
| 8888 | Frontend WEB | Interface de gestion |
| 9000 | MinIO API | Stockage d'objets |
| 9001 | MinIO Console | Console de stockage d'objets |
| 9092 | Kafka | File de messages |
| 10180 | GPUStack | Gestion GPU |
| 10190 | Dify | Plateforme d'applications LLM |
| 19530 | Milvus | Base de données vectorielle |
| 48080 | API Gateway | Passerelle backend |
| 5000 | Service AI | Inférence IA |

---

## II. Déploiement rapide (installation en un clic)

### 2.1 Obtenir le code source

```bash
git clone https://gitee.com/volara/easyaiot.git
cd easyaiot
```

### 2.2 Installation en un clic

```bash
# Nécessite les privilèges root (pour configurer le miroir Docker, la réservation des ports RTP, etc.)
sudo .scripts/docker/install_linux.sh install
```

Cette commande exécute automatiquement le flux suivant :

1. **Vérification de l'environnement** — Détecte si Docker / Docker Compose est installé
2. **Détection IP** — Détecte automatiquement l'IP de l'hôte (pour l'injection de l'adresse média GB28181/ZLMediaKit)
3. **Réservation des ports RTP** — Configure la réservation des ports 30000-30500 par le noyau Linux (évite l'occupation par les ports éphémères)
4. **Configuration du miroir Docker** — Configure automatiquement `docker.m.daocloud.io` pour accélérer les images ([miroir public DaoCloud](https://github.com/DaoCloud/public-image-mirror))
5. **Création du réseau Docker** — Crée le réseau unifié `easyaiot-network`
6. **Déploiement des middlewares** — Démarre successivement Nacos, PostgreSQL, Redis, Kafka, MinIO, TDengine, Milvus, SRS, EMQX, ZLMediaKit, GPUStack, Dify, Node-RED
7. **Attente de la disponibilité des services de base** — Attend automatiquement que les contrôles de santé PostgreSQL / Nacos / Redis réussissent
8. **Déploiement du service DEVICE** — Construit et démarre le cluster de microservices Java (passerelle + 8 services métier)
9. **Déploiement du service AI** — Construit et démarre le service d'inférence IA Python
10. **Déploiement du service VIDEO** — Construit et démarre le service de traitement vidéo Python et 6 sous-services
11. **Déploiement du frontend WEB** — Construit et démarre le frontend Vue 3

### 2.3 Vérification du déploiement

```bash
# Vérifier si tous les services ont démarré avec succès
.scripts/docker/install_linux.sh verify
```

En cas de succès, les adresses d'accès de tous les services seront affichées :

```
Adresses d'accès aux services :
  Services de base (Nacos) :     http://localhost:8848/nacos
  Services de base (MinIO) :     http://localhost:9000 (API), http://localhost:9001 (Console)
  Services de base (Milvus) :    http://localhost:9091 (Health), localhost:19530 (gRPC)
  Services de base (GPUStack) :  http://localhost:10180  (utilisateur admin)
  Service Device (Gateway) :     http://localhost:48080
  Service AI :                   http://localhost:5000
  Service Video :                http://localhost:6000
  Frontend Web :                 http://localhost:8888
```

### 2.4 Accéder au système

Ouvrez `http://<服务器IP>:8888` dans le navigateur pour accéder à la plateforme de gestion EasyAIoT.

---

## III. Déploiement par étapes (opération manuelle)

Si vous avez besoin d'un contrôle plus fin, vous pouvez déployer module par module.

### 3.1 Première étape : déployer les middlewares

```bash
cd .scripts/docker
./install_middleware_linux.sh install
```

**Liste des middlewares :**

| Middleware | Image | Port | Usage |
|--------|------|------|------|
| Nacos | nacos/nacos-server:v2.5.1 | 8848, 9848, 9849 | Centre d'enregistrement et de configuration des services |
| PostgreSQL | postgres:18 | 5432 | Base de données principale (6 bases métier) |
| TDengine | tdengine/tsdb:3.3.8.4 | 6030, 6041, 6060 | Base de données temporelle |
| Redis | redis:7.4.8 | 6379 | Cache et verrouillage distribué |
| Kafka | apache/kafka:3.8.0 | 9092, 9093, 9094 | File de messages |
| MinIO | minio/minio | 9000, 9001 | Stockage d'objets |
| Milvus | milvusdb/milvus:v2.6.0 | 19530, 9091 | Base de données vectorielle (reconnaissance faciale) |
| SRS | ossrs/srs:5 | 1935, 1985 | Serveur de streaming |
| EMQX | emqx/emqx:5.8.7 | 1883, 8083, 18083 | MQTT Broker |
| ZLMediaKit | zlmediakit/zlmediakit:master | 6080, 5540, 10935 | Serveur média |
| GPUStack | gpustack/gpustack:v2.1.2 | 10180 | Gestion des ressources GPU |
| Dify | dify-api / dify-web / ... | 10190 | Plateforme d'applications LLM |
| Node-RED | nodered/node-red:latest | 1880 | Moteur de règles |

Attendre que les middlewares soient prêts :

```bash
# Vérifier PostgreSQL
docker exec postgres-server pg_isready -U postgres

# Vérifier Nacos
curl -s http://localhost:8848/nacos/actuator/health

# Vérifier Redis
docker exec redis-server redis-cli -a basiclab@iot975248395 ping
```

### 3.2 Deuxième étape : déployer le service DEVICE

```bash
cd DEVICE
./install_linux.sh install
```

**Liste des services DEVICE :**

| Service | Port | Description |
|------|------|------|
| iot-gateway | 48080 | Passerelle API (Spring Cloud Gateway) |
| iot-system | 48099 | Gestion système |
| iot-infra | 48066 | Infrastructure |
| iot-device | 48055 | Gestion des appareils |
| iot-dataset | 48077 | Gestion des jeux de données |
| iot-message | 48033 | Push de messages |
| iot-file | 48022 | Service de fichiers |
| iot-sink | 48011 | Adaptation de protocole (MQTT/TCP/HTTP/EMQX) |
| iot-gb28181 | 5060 | Protocole de surveillance vidéo GB28181 |

**Méthode de construction :**
- Construction en deux étapes : `Dockerfile.base` (cache des dépendances Maven) → `Dockerfile` de chaque module
- Java 21 + Spring Boot 2.7.18
- Répertoire de cache de construction : `.build-cache/device/m2/repository`

### 3.3 Troisième étape : déployer le service AI

```bash
cd AI
./install_linux.sh install
```

**Description du service AI :**
- Port : 5000
- Framework : Flask + PyTorch 2.9+ (CUDA 12.8)
- Fonctionnalités : entraînement de modèles, inférence, déploiement, OCR, voix, LLM
- Support GPU : détection automatique du GPU et activation de NVIDIA Container Runtime
- Cache de construction : `.build-cache/ai/pip-cache`、`.build-cache/ai/pip-wheels`
- Image de base : `pytorch/pytorch:2.9.0-cuda12.8-cudnn9-devel`

### 3.4 Quatrième étape : déployer le service VIDEO

```bash
cd VIDEO
./install_linux.sh install
```

**Description du service VIDEO :**
- Port : 6000
- Framework : Flask + OpenCV + FFmpeg
- Fonctionnalités : traitement de flux vidéo, analyse d'algorithmes en temps réel/snapshot, enregistrement, alertes, reconnaissance faciale
- Sous-services : 6 microservices indépendants (algorithme temps réel, algorithme snapshot, extraction de frames, tri, push de flux, redirection de flux)
- File de messages : Kafka (événements d'alerte)
- Base de données vectorielle : Milvus (reconnaissance faciale)

### 3.5 Cinquième étape : déployer le frontend WEB

```bash
cd WEB
./install_linux.sh install
```

**Description du frontend WEB :**
- Port : 8888
- Framework : Vue 3.4 + TypeScript + Vite
- Bibliothèque UI : Ant Design Vue 4.0
- Construction : Node.js 18+ / 20+，pnpm 11.3+

---

## IV. Gestion par module

Chaque module prend en charge les commandes suivantes :

```bash
./install_linux.sh install    # Installer et démarrer (première exécution)
./install_linux.sh start      # Démarrer
./install_linux.sh stop       # Arrêter
./install_linux.sh restart    # Redémarrer
./install_linux.sh status     # Afficher l'état
./install_linux.sh logs       # Afficher les journaux
./install_linux.sh build      # Reconstruire les images
./install_linux.sh clean      # Nettoyer conteneurs et images
./install_linux.sh update     # Mettre à jour et redémarrer
```

**Gestion individuelle des middlewares :**

```bash
cd .scripts/docker
./install_middleware_linux.sh install    # Installer tous les middlewares
./install_middleware_linux.sh start      # Démarrer
./install_middleware_linux.sh stop       # Arrêter
./install_middleware_linux.sh status     # État
./install_middleware_linux.sh logs       # Journaux
```

---

## V. Configuration GPU

### 5.1 Installer le pilote NVIDIA

```bash
# Vérifier si le GPU est disponible
nvidia-smi

# Installer NVIDIA Container Toolkit
# Référence : https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

# Vérifier la prise en charge GPU par Docker
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi
```

### 5.2 Détection automatique GPU

Le script d'installation détecte automatiquement le GPU :
- GPU détecté → active automatiquement `runtime: nvidia`, définit `NVIDIA_VISIBLE_DEVICES=all`
- Aucun GPU détecté → exécution en mode CPU

### 5.3 Configuration multi-GPU

Le service AI prend en charge l'inférence parallèle multi-GPU, contrôlée par des variables d'environnement :

```bash
# Spécifier l'utilisation des GPU 0 et 1
export CUDA_VISIBLE_DEVICES=0,1
```

---

## VI. Adaptation à l'écosystème national chinois

### 6.1 Système Kylin

```bash
.scripts/docker/install_linux_kylin.sh install
```

### 6.2 Architecture ARM64

```bash
# Middlewares
.scripts/docker/install_linux_arm.sh install

# Service AI (Dockerfile version ARM)
cd AI
./install_linux.sh install  # Le script sélectionne automatiquement le Dockerfile ARM
```

---

## VII. Description des bases de données

### 7.1 Bases métier PostgreSQL

PostgreSQL crée automatiquement les 6 bases métier suivantes au démarrage :

| Nom de la base | Fichier SQL | Usage |
|------|---------|------|
| ruoyi-vue-pro20 | ruoyi-vue-pro10.sql | Base principale de gestion système |
| iot-ai20 | iot-ai10.sql | Base du service AI |
| iot-device10 | iot-device10.sql | Base de gestion des appareils |
| iot-gb2818110 | iot-gb2818110.sql | Base de surveillance vidéo |
| iot-message10 | iot-message10.sql | Base de push de messages |
| iot-video10 | iot-video10.sql | Base de traitement vidéo |

Les scripts d'initialisation se trouvent dans le répertoire `.scripts/postgresql/` et sont exécutés automatiquement au démarrage Docker via `docker-entrypoint-initdb.d`.

### 7.2 Base temporelle TDengine

TDengine initialise automatiquement les super tables au démarrage ; le fichier SQL se trouve dans `.scripts/tdengine/tdengine_super_tables.sql`.

### 7.3 Sauvegarde des bases de données

```bash
# Sauvegarder toutes les bases de données
.scripts/postgresql/backup_databases.sh
```

---

## VIII. Comptes et mots de passe par défaut des middlewares

| Middleware | Nom d'utilisateur | Mot de passe | Adresse de la console |
|--------|--------|------|-----------|
| Nacos | nacos | nacos | http://<IP>:8848/nacos |
| PostgreSQL | postgres | iot45722414822 | — |
| Redis | — | basiclab@iot975248395 | — |
| MinIO | minioadmin | basiclab@iot975248395 | http://<IP>:9001 |
| EMQX | admin | basiclab@iot6874125784 | http://<IP>:18083 |
| GPUStack | admin | basiclab@iotp4JWmQSvzdh0z4mF | http://<IP>:10180 |
| Milvus | — | — | http://<IP>:9091 |

> ⚠️ **Avertissement de sécurité** : en environnement de production, modifiez impérativement tous les mots de passe par défaut.

---

## IX. Dépannage

### 9.1 Échec du démarrage des services

```bash
# Afficher les journaux d'un service spécifique
docker logs -f postgres-server
docker logs -f nacos-server
docker logs -f ai-service
docker logs -f video-service

# Afficher l'état de tous les services
docker ps -a
```

### 9.2 Problèmes réseau

```bash
# Vérifier le réseau Docker
docker network ls | grep easyaiot
docker network inspect easyaiot-network

# Recréer le réseau (après changement d'IP de l'hôte)
docker network rm easyaiot-network
docker network create easyaiot-network
docker compose restart
```

### 9.3 Problèmes de connexion PostgreSQL

```bash
# Réparation automatique
.scripts/docker/fix_postgresql.sh

# Vérification manuelle
docker exec postgres-server pg_isready -U postgres
docker exec postgres-server psql -U postgres -c "SELECT 1;"
```

### 9.4 Problèmes de connexion Redis

```bash
# Réparation automatique
.scripts/docker/fix_redis.sh

# Vérification manuelle
docker exec redis-server redis-cli -a basiclab@iot975248395 ping
```

### 9.5 Problèmes du service Docker

```bash
# Diagnostiquer les problèmes Docker systemd
sudo .scripts/docker/diagnose_docker_systemd.sh diagnose

# Corriger le timeout systemd
sudo .scripts/docker/diagnose_docker_systemd.sh fix-all

# Vérifier l'espace disque
df -h
docker system df

# Nettoyer les fichiers inutiles Docker
.scripts/docker/cleanup_docker_space.sh
```

### 9.6 Problèmes de groupe de consommation Kafka

```bash
# Réparer le groupe de consommation Kafka
cd VIDEO
python fix_kafka_consumer_group.py
```

### 9.7 Conflits de ports

```bash
# Vérifier l'occupation des ports
ss -tlnp | grep -E "8848|5432|6379|9092|5000|6000|8888"

# En cas de conflit, modifier le mappage de ports dans le docker-compose.yml correspondant
```

---

## X. Emplacement des fichiers journaux

| Emplacement | Description |
|------|------|
| `.scripts/docker/logs/` | Journaux du script d'installation |
| `DEVICE/logs/` | Journaux du service DEVICE |
| `AI/data/logs/` | Journaux du service AI |
| `VIDEO/data/logs/` | Journaux du service VIDEO |
| `docker logs <nom-du-conteneur>` | Journaux en temps réel du conteneur |

---

## XI. Mise à jour et upgrade

### 11.1 Mettre à jour le code

```bash
cd easyaiot
git pull origin main
```

### 11.2 Mettre à jour et redémarrer tous les services

```bash
sudo .scripts/docker/install_linux.sh update
```

### 11.3 Mettre à jour un module unique

```bash
# Par exemple, mettre à jour uniquement le service AI
cd AI
./install_linux.sh update
```

### 11.4 Reconstruire les images

```bash
# Reconstruire toutes les images
sudo .scripts/docker/install_linux.sh build

# Reconstruire un module unique
cd DEVICE
./install_linux.sh build
```

---

## XII. Désinstallation

```bash
# Arrêter et supprimer tous les conteneurs, images et réseaux
sudo .scripts/docker/install_linux.sh clean

# Nettoyage manuel des volumes de données (optionnel)
rm -rf .scripts/docker/db_data
rm -rf .scripts/docker/redis_data
rm -rf .scripts/docker/minio_data
rm -rf .scripts/docker/mq_data
rm -rf .scripts/docker/taos_data
rm -rf .scripts/docker/milvus_data
rm -rf .scripts/docker/gpustack_data
```

---

## XIII. Référence d'architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend WEB (:8888)                          │
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
│  Service AI (:5000)      │  Service VIDEO (:6000) │  TASK (C++)  │
│  Flask + PyTorch + YOLO  │  Flask + OpenCV + FFmpeg│  ONNX Runtime│
│  Entraîn./Infér./Dépl./OCR/LLM │ Flux/Alertes/Enreg./Visage │ Infér. edge │
├──────────────────────────┴───────────────────────┴──────────────┤
│                     Couche middleware                            │
│  Nacos │ PostgreSQL │ Redis │ Kafka │ MinIO │ TDengine          │
│  Milvus │ SRS │ EMQX │ ZLMediaKit │ GPUStack │ Dify │ Node-RED  │
└─────────────────────────────────────────────────────────────────┘
```

---

*Document généré le : 2026-05-31 | Projet : https://gitee.com/volara/easyaiot*
