"""
@author 翱翔的雄库鲁
@email andywebjava@163.com
@wechat EasyAIoT2025
"""
import json
import os
import shutil
import threading
import traceback
import uuid
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import torch
import yaml
from flask import current_app, jsonify, Blueprint, request
from ultralytics import YOLO

from app.blueprints.train_task import build_train_task_name, resolve_task_base_name
from app.services.minio_service import ModelService
from app.utils.gpu_utils import (
    check_gpu_status,
    format_device_for_log,
    normalize_request_gpu_ids,
    resolve_yolo_train_device,
)
from db_models import db, TrainTask

train_bp = Blueprint('train', __name__)

# 本地数据集 zip 上传上限（与前端一致，5GB）
MAX_LOCAL_DATASET_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024

# 全局训练状态和进程
train_status = {}
train_processes = {}

# 数据库中表示「进行中」的状态（容器重启后需 recover_stale_train_tasks 清理）
ACTIVE_TRAIN_STATUSES = ('preparing', 'train', 'Train', 'running', 'stopping')


def _build_train_hyperparameters(
    epochs,
    model_arch,
    img_size,
    batch_size,
    use_gpu,
    task_base_name,
    gpu_ids=None,
    dataset_source=None,
):
    base = (task_base_name or 'train').strip() or 'train'
    hp = {
        'epochs': epochs,
        'model_arch': model_arch,
        'img_size': img_size,
        'batch_size': batch_size,
        'use_gpu': use_gpu,
        'task_base_name': base,
        'dataset_source': _normalize_dataset_source(dataset_source),
    }
    if gpu_ids is not None:
        hp['gpu_ids'] = gpu_ids
    return json.dumps(hp)


def _normalize_dataset_source(value) -> str:
    source = (value or 'local').strip().lower()
    return source if source in ('local', 'cloud') else 'local'


def _is_cloud_dataset_path(dataset_path: str) -> bool:
    if not dataset_path:
        return False
    if dataset_path.startswith('/api/v1/buckets/'):
        return True
    return '://' in dataset_path and not dataset_path.startswith('file://')


def _resolve_split_path(raw_path, split_name, yaml_dir, dataset_root):
    if not raw_path:
        return None

    normalized_raw = str(raw_path).replace('\\', '/')
    candidate_bases = [
        yaml_dir,
        dataset_root,
        os.path.dirname(dataset_root),
    ]

    for base in candidate_bases:
        candidate = os.path.normpath(os.path.join(base, normalized_raw))
        if os.path.exists(candidate):
            return os.path.abspath(candidate)

    split_alias = {
        'train': ['train'],
        'val': ['val', 'valid', 'validation'],
        'test': ['test'],
    }
    for alias in split_alias.get(split_name, [split_name]):
        for base in candidate_bases:
            img_candidate = os.path.join(base, alias, 'images')
            if os.path.exists(img_candidate):
                return os.path.abspath(img_candidate)
            alt_candidate = os.path.join(base, 'images', alias)
            if os.path.exists(alt_candidate):
                return os.path.abspath(alt_candidate)

    return None


def _find_first_data_yaml(root_dir):
    for root, _, files in os.walk(root_dir):
        for file_name in files:
            if file_name.lower() == 'data.yaml':
                return os.path.join(root, file_name)
    return None


def _normalize_dataset_yaml(dataset_root, output_dir=None):
    """
    将 data.yaml 中的 train/val/test 转为绝对路径，避免 path: . 导致 Ultralytics 解析到错误目录。
    兼容本地导出（train/images）与 MinIO 同步（images/train）两种目录结构。
    """
    data_yaml = _find_first_data_yaml(dataset_root)
    if not data_yaml:
        raise ValueError('未找到 data.yaml，无法开始训练')

    with open(data_yaml, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}

    yaml_dir = os.path.dirname(data_yaml)
    train_path = _resolve_split_path(cfg.get('train'), 'train', yaml_dir, dataset_root)
    val_path = _resolve_split_path(cfg.get('val'), 'val', yaml_dir, dataset_root)
    test_path = (
        _resolve_split_path(cfg.get('test'), 'test', yaml_dir, dataset_root)
        if cfg.get('test') else None
    )

    if not train_path:
        raise ValueError('数据集 train 路径无效，请检查 data.yaml 或目录结构')
    if not val_path:
        raise ValueError('数据集 val/valid 路径无效，请检查 data.yaml 或目录结构')

    normalized_cfg = {
        'train': train_path,
        'val': val_path,
        'nc': cfg.get('nc', 1),
        'names': cfg.get('names', ['object']),
    }
    if test_path:
        normalized_cfg['test'] = test_path

    target_dir = output_dir or dataset_root
    os.makedirs(target_dir, exist_ok=True)
    normalized_yaml_path = os.path.join(target_dir, 'data.yaml')
    with open(normalized_yaml_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(normalized_cfg, f, allow_unicode=True, sort_keys=False)

    return normalized_yaml_path


def _prepare_train_dataset_in_dir(dataset_path: str, model_dir: str, log_fn):
    """将本地路径/zip 或云端 MinIO 数据集准备到 model_dir。"""
    os.makedirs(model_dir, exist_ok=True)

    if not _is_cloud_dataset_path(dataset_path):
        if not os.path.exists(dataset_path):
            raise RuntimeError(f'本地数据集不存在: {dataset_path}')
        source_abs = os.path.abspath(dataset_path)
        if os.path.isdir(source_abs):
            data_yaml = os.path.join(source_abs, 'data.yaml')
            if not os.path.exists(data_yaml):
                raise RuntimeError(f'本地数据集目录缺少 data.yaml: {source_abs}')
            if source_abs != os.path.abspath(model_dir):
                for name in os.listdir(source_abs):
                    src = os.path.join(source_abs, name)
                    dst = os.path.join(model_dir, name)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
            log_fn(f'已使用本地数据集目录: {source_abs}')
            return
        if source_abs.lower().endswith('.zip'):
            log_fn(f'正在解压本地数据集: {source_abs}')
            if not ModelService.extract_zip(source_abs, model_dir):
                raise RuntimeError(f'本地数据集 zip 解压失败: {source_abs}')
            log_fn('本地数据集解压成功')
            return
        raise RuntimeError('本地数据集路径仅支持目录或 zip 文件')

    parsed_url = urlparse(dataset_path)
    query_params = parse_qs(parsed_url.query)
    object_key = query_params.get('prefix', [None])[0]
    path_parts = parsed_url.path.split('/')
    if len(path_parts) >= 5 and path_parts[3] == 'buckets':
        bucket_name = path_parts[4]
    else:
        bucket_name = 'datasets'

    local_zip_path = os.path.join(model_dir, 'dataset.zip')
    log_fn(f'从 MinIO 下载数据集: bucket={bucket_name}, object={object_key}')
    success, error_msg = ModelService.download_from_minio(
        bucket_name=bucket_name,
        object_name=object_key,
        destination_path=local_zip_path,
    )
    if not success:
        raise RuntimeError(f'数据集下载失败: {error_msg or "未知错误"}')
    log_fn('数据集下载成功，开始解压...')
    if not ModelService.extract_zip(local_zip_path, model_dir):
        raise RuntimeError('数据集解压失败')
    if os.path.exists(local_zip_path):
        os.remove(local_zip_path)
    log_fn('云端数据集解压成功')


TRAIN_ARTIFACTS_BUCKET = 'models'


def _train_artifact_object_key(model_id, task_id, filename):
    """与历史 best.pt 路径一致：models/model_{model_id}/train_{task_id}/{filename}"""
    return f"models/model_{model_id}/train_{task_id}/{filename}"


def _build_minio_download_url(bucket_name, object_key):
    return f"/api/v1/buckets/{bucket_name}/objects/download?prefix={object_key}"


def _resolve_train_results_dir(model_dir):
    """定位 YOLO 训练输出目录（exist_ok 时可能为 train_results2 等）。"""
    parent = model_dir
    if not os.path.isdir(parent):
        return os.path.join(model_dir, 'train_results')
    candidates = []
    for name in os.listdir(parent):
        if not name.startswith('train_results'):
            continue
        path = os.path.join(parent, name)
        if os.path.isdir(path):
            candidates.append(name)
    for name in sorted(candidates, reverse=True):
        path = os.path.join(parent, name)
        if os.path.isfile(os.path.join(path, 'results.png')) or os.path.isfile(
            os.path.join(path, 'results.csv')
        ) or os.path.isfile(os.path.join(path, 'weights', 'last.pt')):
            return path
    if candidates:
        return os.path.join(parent, sorted(candidates, reverse=True)[0])
    return os.path.join(model_dir, 'train_results')


def _parse_train_hyperparameters(hp_text):
    if not hp_text:
        return {}
    try:
        return json.loads(hp_text)
    except (json.JSONDecodeError, TypeError):
        return {}


def _get_completed_epochs(hp_text):
    return int(_parse_train_hyperparameters(hp_text).get('completed_epochs') or 0)


def _get_total_epochs_from_hp(hp_text, default=20):
    return int(_parse_train_hyperparameters(hp_text).get('epochs') or default)


def _update_hyperparameters_field(hp_text, **fields):
    hp = _parse_train_hyperparameters(hp_text)
    hp.update(fields)
    return json.dumps(hp)


def _resolve_train_checkpoint_path(model_dir):
    """定位 YOLO 断点权重 last.pt。"""
    results_dir = _resolve_train_results_dir(model_dir)
    last_pt = os.path.join(results_dir, 'weights', 'last.pt')
    if os.path.isfile(last_pt):
        return os.path.abspath(last_pt)
    return None


def _clear_train_results_dirs(model_dir, log_fn=None):
    """重新训练前清理历史 YOLO 输出目录。"""
    if not model_dir or not os.path.isdir(model_dir):
        return

    def _log(msg):
        if log_fn:
            log_fn(msg)

    for name in os.listdir(model_dir):
        if not name.startswith('train_results'):
            continue
        path = os.path.join(model_dir, name)
        if os.path.isdir(path):
            try:
                shutil.rmtree(path)
                _log(f'已清理历史训练输出: {name}')
            except OSError as e:
                _log(f'清理 {name} 失败: {e}')


def _download_checkpoint_from_minio(train_task, dest_path, log_fn):
    """本地断点缺失时尝试从 MinIO 拉取 last.pt。"""
    model_id = train_task.model_id
    minio_path = _train_artifact_object_key(model_id, train_task.id, 'last.pt')
    success, error_msg = ModelService.download_from_minio(
        bucket_name=TRAIN_ARTIFACTS_BUCKET,
        object_name=minio_path,
        destination_path=dest_path,
    )
    if success and os.path.isfile(dest_path):
        log_fn(f'已从 MinIO 恢复断点权重: {dest_path}')
        return dest_path
    if error_msg:
        log_fn(f'从 MinIO 恢复断点失败: {error_msg}')
    return None


def _resolve_resume_checkpoint(train_task, model_dir, log_fn=None):
    """解析可用于续训的断点路径（本地优先，MinIO 兜底）。"""
    def _log(msg):
        if log_fn:
            log_fn(msg)

    checkpoint = (train_task.checkpoint_dir or '').strip()
    if checkpoint and os.path.isfile(checkpoint):
        return os.path.abspath(checkpoint)

    checkpoint = _resolve_train_checkpoint_path(model_dir)
    if checkpoint:
        return checkpoint

    results_dir = _resolve_train_results_dir(model_dir)
    weights_dir = os.path.join(results_dir, 'weights')
    os.makedirs(weights_dir, exist_ok=True)
    dest = os.path.join(weights_dir, 'last.pt')
    return _download_checkpoint_from_minio(train_task, dest, _log)


def _persist_stop_checkpoint(train_task, model_dir, completed_epochs, update_log_fn):
    """停止训练时记录断点路径并上传 last.pt。"""
    checkpoint_path = _resolve_train_checkpoint_path(model_dir)
    if not checkpoint_path:
        update_log_fn('未找到 last.pt，无法保存断点（需至少完成 1 个 epoch）')
        return

    train_task.checkpoint_dir = checkpoint_path
    train_task.hyperparameters = _update_hyperparameters_field(
        train_task.hyperparameters,
        completed_epochs=completed_epochs,
    )
    total_epochs = _get_total_epochs_from_hp(train_task.hyperparameters)
    update_log_fn(
        f'已保存训练断点: epoch {completed_epochs}/{total_epochs}, 权重={checkpoint_path}'
    )

    model_id = train_task.model_id
    minio_path = _train_artifact_object_key(model_id, train_task.id, 'last.pt')
    success, error = ModelService.upload_to_minio(
        bucket_name=TRAIN_ARTIFACTS_BUCKET,
        object_name=minio_path,
        file_path=checkpoint_path,
    )
    if success:
        update_log_fn(
            f'断点权重已上传至 MinIO: '
            f'{_build_minio_download_url(TRAIN_ARTIFACTS_BUCKET, minio_path)}'
        )
    else:
        update_log_fn(f'断点权重上传 MinIO 失败: {error or "未知错误"}')


def _is_uploaded_dataset_zip(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    uploads_root = os.path.join(get_project_root(), 'data', 'datasets', 'uploads')
    try:
        return os.path.commonpath([
            os.path.abspath(path),
            os.path.abspath(uploads_root),
        ]) == os.path.abspath(uploads_root)
    except ValueError:
        return False


def _cleanup_train_dataset_artifacts(model_dir, dataset_zip_path, log_fn=None):
    """训练结束后删除本地数据集文件，保留 train_results 与已导出的权重。"""
    def _log(msg):
        if log_fn:
            log_fn(msg)

    freed = []

    if dataset_zip_path and _is_uploaded_dataset_zip(dataset_zip_path):
        try:
            os.remove(dataset_zip_path)
            freed.append(f'上传压缩包: {dataset_zip_path}')
        except OSError as e:
            _log(f'删除上传压缩包失败: {e}')

    if not model_dir or not os.path.isdir(model_dir):
        if freed:
            _log(f'已清理训练数据集: {"; ".join(freed)}')
        return

    train_results_dir = os.path.join(model_dir, 'train_results')
    for name in ('images', 'labels', 'train', 'val', 'test'):
        target = os.path.join(model_dir, name)
        if os.path.isdir(target):
            try:
                shutil.rmtree(target)
                freed.append(name + '/')
            except OSError as e:
                _log(f'删除 {name}/ 失败: {e}')

    for name in ('data.yaml', 'dataset.zip'):
        target = os.path.join(model_dir, name)
        if os.path.isfile(target):
            try:
                os.remove(target)
                freed.append(name)
            except OSError as e:
                _log(f'删除 {name} 失败: {e}')

    # 清理 train_results 内可能残留的中间缓存，保留 weights 与结果文件
    if os.path.isdir(train_results_dir):
        for sub in ('images', 'labels'):
            target = os.path.join(train_results_dir, sub)
            if os.path.isdir(target):
                try:
                    shutil.rmtree(target)
                    freed.append(f'train_results/{sub}/')
                except OSError:
                    pass

    if freed:
        _log(f'已清理训练数据集以释放磁盘: {", ".join(freed)}')
    else:
        _log('未发现需清理的本地数据集文件')


@train_bp.route('/dataset/upload', methods=['POST'])
def api_upload_train_dataset():
    """上传本地 YOLO 数据集压缩包（zip），供训练使用。"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'code': 400, 'msg': '未找到文件'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'success': False, 'code': 400, 'msg': '未选择文件'}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext != '.zip':
        return jsonify({'success': False, 'code': 400, 'msg': '仅支持 ZIP 格式数据集'}), 400

    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    if file_size > MAX_LOCAL_DATASET_UPLOAD_BYTES:
        return jsonify({
            'success': False,
            'code': 400,
            'msg': '数据集压缩包不能超过 5GB',
        }), 400

    upload_dir = os.path.join(get_project_root(), 'data', 'datasets', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    unique_name = f'{uuid.uuid4().hex}.zip'
    local_path = os.path.join(upload_dir, unique_name)
    file.save(local_path)

    return jsonify({
        'success': True,
        'code': 0,
        'msg': '上传成功',
        'data': {
            'path': local_path,
            'fileName': file.filename,
        },
    }), 200


@train_bp.route('/start', methods=['POST'])
def api_start_train():
    train_task = None
    is_new_record = False  # 标记是否是新创建的记录
    try:
        # 获取训练参数
        data = request.get_json() or {}

        record_id = data.get('taskId')
        is_resume = bool(data.get('resume'))
        task_name = (data.get('taskName') or data.get('task_name') or '').strip()
        epochs = data.get('epochs', 20)
        batch_size = data.get('batch_size', 16)
        img_size = data.get('imgsz', 640)
        model_arch = data.get('modelPath', 'yolov8n.pt')
        dataset_url = data.get('datasetPath') or data.get('dataset_path')
        dataset_zip_path = dataset_url
        dataset_source = _normalize_dataset_source(
            data.get('datasetSource') or data.get('dataset_source')
        )
        if dataset_source == 'local' and dataset_zip_path and _is_cloud_dataset_path(dataset_zip_path):
            dataset_source = 'cloud'
        elif dataset_source == 'cloud' and dataset_zip_path and not _is_cloud_dataset_path(dataset_zip_path):
            dataset_source = 'local'
        dataset_name = (data.get('datasetName') or data.get('dataset_name') or '').strip() or None
        dataset_version = (data.get('datasetVersion') or data.get('dataset_version') or '').strip() or None
        use_gpu = data.get('use_gpu', True)
        request_gpu_ids = normalize_request_gpu_ids(data.get('gpu_ids'))

        if not dataset_zip_path:
            return jsonify({'success': False, 'code': 400, 'msg': '缺少数据集路径'}), 400
        if dataset_source == 'local' and not os.path.exists(dataset_zip_path):
            return jsonify({'success': False, 'code': 400, 'msg': '本地数据集文件不存在，请重新上传'}), 400

        if record_id:
            train_task = TrainTask.query.get(record_id)
            if train_task:
                in_memory = (
                    train_task.id in train_status
                    and train_status[train_task.id]['status'] in ['preparing', 'train']
                )
                in_db = train_task.status in ACTIVE_TRAIN_STATUSES
                if in_memory or in_db:
                    return jsonify({'success': False, 'code': 0, 'msg': '该训练任务已在进行中'}), 200

                task_base_name = task_name or resolve_task_base_name(train_task)
                model_dir = os.path.join(get_project_root(), 'data/datasets', f'train_{train_task.id}')

                if is_resume:
                    if train_task.status != 'stopped':
                        return jsonify({
                            'success': False,
                            'code': 400,
                            'msg': '仅已停止的任务可继续训练',
                        }), 400

                    completed_epochs = _get_completed_epochs(train_task.hyperparameters)
                    if int(epochs) <= completed_epochs:
                        return jsonify({
                            'success': False,
                            'code': 400,
                            'msg': (
                                f'总 epochs({epochs}) 必须大于已完成 epoch({completed_epochs})，'
                                '请增大迭代次数或使用重新训练'
                            ),
                        }), 400

                    checkpoint_path = _resolve_resume_checkpoint(train_task, model_dir)
                    if not checkpoint_path:
                        return jsonify({
                            'success': False,
                            'code': 400,
                            'msg': '未找到可用训练断点，请使用重新训练',
                        }), 400

                    train_task.checkpoint_dir = checkpoint_path
                    train_task.start_time = datetime.utcnow()
                    train_task.end_time = None
                    train_task.status = 'preparing'
                    train_task.hyperparameters = _update_hyperparameters_field(
                        _build_train_hyperparameters(
                            epochs, model_arch, img_size, batch_size, use_gpu, task_base_name,
                            request_gpu_ids, dataset_source,
                        ),
                        completed_epochs=completed_epochs,
                    )
                    train_task.name = build_train_task_name(
                        task_base_name,
                        train_task.dataset_name,
                        train_task.dataset_version,
                        train_task.id,
                    )
                    db.session.commit()
                else:
                    train_task.dataset_path = dataset_zip_path
                    if dataset_name:
                        train_task.dataset_name = dataset_name
                    if dataset_version is not None:
                        train_task.dataset_version = dataset_version
                    train_task.start_time = datetime.utcnow()
                    train_task.status = 'preparing'
                    train_task.train_log = ''
                    train_task.progress = 0
                    train_task.checkpoint_dir = ''
                    train_task.hyperparameters = _update_hyperparameters_field(
                        _build_train_hyperparameters(
                            epochs, model_arch, img_size, batch_size, use_gpu, task_base_name,
                            request_gpu_ids, dataset_source,
                        ),
                        completed_epochs=0,
                    )
                    train_task.name = build_train_task_name(
                        task_base_name,
                        train_task.dataset_name,
                        train_task.dataset_version,
                        train_task.id,
                    )
                    _clear_train_results_dirs(model_dir)
                    db.session.commit()
                is_new_record = False

        if not train_task:
            task_base_name = task_name or 'train'
            train_task = TrainTask(
                name='',
                dataset_path=dataset_zip_path,
                dataset_name=dataset_name,
                dataset_version=dataset_version,
                hyperparameters=_build_train_hyperparameters(
                    epochs, model_arch, img_size, batch_size, use_gpu, task_base_name,
                    request_gpu_ids, dataset_source,
                ),
                start_time=datetime.utcnow(),
                status='preparing',
                train_log='',
                checkpoint_dir=''
            )
            db.session.add(train_task)
            db.session.flush()
            train_task.name = build_train_task_name(
                task_base_name, dataset_name, dataset_version, train_task.id
            )
            db.session.commit()
            is_new_record = True

        task_id = train_task.id
        if task_id in train_status and train_status[task_id]['status'] in ['preparing', 'train']:
            return jsonify({'success': False, 'code': 0, 'msg': '训练已在进行中'}), 200

        if is_resume:
            dataset_zip_path = dataset_zip_path or train_task.dataset_path

        train_status[task_id] = {
            'status': 'preparing',
            'message': '准备训练数据...',
            'progress': 0,
            'log': '',
            'stop_requested': False
        }

        train_thread = threading.Thread(
            target=train_model,
            args=(task_id, epochs, model_arch, img_size, batch_size,
                  use_gpu, dataset_zip_path, train_task.id, request_gpu_ids, dataset_source,
                  is_resume)
        )
        train_thread.daemon = True
        train_thread.start()

        start_msg = '训练已继续' if is_resume else ('重新训练已启动' if record_id else '训练已启动')
        return jsonify({
            'success': True,
            'code': 0,
            'msg': start_msg,
            'record_id': train_task.id  # 返回记录ID给前端
        }), 200
    except Exception as e:
        # 如果创建了训练记录但在启动线程前失败，需要回滚或删除记录
        if train_task:
            try:
                if is_new_record:
                    # 如果是新创建的记录，删除它
                    db.session.delete(train_task)
                    db.session.commit()
                else:
                    # 如果是更新的记录，标记为错误状态
                    train_task.status = 'error'
                    train_task.error_log = f'启动训练失败: {str(e)}'
                    db.session.commit()
            except Exception as rollback_error:
                print(f'回滚训练记录失败: {str(rollback_error)}')
                db.session.rollback()
        
        return jsonify({'success': False, 'code': 400, 'msg': f'启动训练失败: {str(e)}'}), 400


def get_project_root():
    """获取项目根目录"""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))


def recover_stale_train_tasks(app=None):
    """
    服务重启后，将数据库中仍为进行中、但本进程无训练线程的任务标记为失败。
    避免进度长期卡在 15% 等中间态。
    """
    from run import create_app

    application = app or create_app()
    recovered = 0
    with application.app_context():
        stale_tasks = TrainTask.query.filter(
            TrainTask.status.in_(ACTIVE_TRAIN_STATUSES)
        ).all()
        if not stale_tasks:
            return 0

        interrupt_msg = (
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            "训练进程因服务重启或异常退出而中断。"
        )
        for task in stale_tasks:
            if task.id in train_status:
                continue
            model_dir = os.path.join(get_project_root(), 'data/datasets', f'train_{task.id}')
            checkpoint_path = _resolve_resume_checkpoint(task, model_dir)
            if checkpoint_path:
                completed_epochs = _get_completed_epochs(task.hyperparameters)
                task.status = 'stopped'
                task.checkpoint_dir = checkpoint_path
                task.hyperparameters = _update_hyperparameters_field(
                    task.hyperparameters,
                    completed_epochs=completed_epochs,
                )
                resume_hint = '可点击「继续训练」从断点恢复。'
            else:
                task.status = 'error'
                resume_hint = '未找到可用断点，请重新训练。'
            task.end_time = datetime.utcnow()
            task.train_log = (task.train_log or '') + interrupt_msg + resume_hint + '\n'
            recovered += 1

        if recovered:
            db.session.commit()
    return recovered


def _parse_minio_download_url(url: str):
    """解析 MinIO 下载 URL，返回 (bucket_name, object_key)。"""
    try:
        parsed = urlparse(url)
        path_parts = parsed.path.split('/')
        if len(path_parts) >= 5 and path_parts[3] == 'buckets':
            bucket_name = path_parts[4]
        else:
            return None, None
        query_params = parse_qs(parsed.query)
        object_key = query_params.get('prefix', [None])[0]
        return bucket_name, object_key
    except Exception:
        return None, None


def _resolve_pretrained_model_path(model_arch: str, task_id: int):
    """
    将 model_arch 解析为 YOLO 可用的本地路径或标准权重名。
    返回 (resolved_path, error_message)，成功时 error_message 为 None。
    """
    model_arch = (model_arch or 'yolov8n.pt').strip()
    ai_root = get_project_root()

    if model_arch.startswith('/api/v1/buckets/'):
        bucket_name, object_key = _parse_minio_download_url(model_arch)
        if not bucket_name or not object_key:
            return None, f'预训练模型 URL 格式无效: {model_arch}'

        storage_dir = os.path.join(ai_root, 'data', 'pretrained', f'train_{task_id}')
        os.makedirs(storage_dir, exist_ok=True)
        filename = os.path.basename(object_key) or 'pretrained.pt'
        local_path = os.path.join(storage_dir, filename)

        if os.path.exists(local_path):
            return local_path, None

        success, error_msg = ModelService.download_from_minio(
            bucket_name=bucket_name,
            object_name=object_key,
            destination_path=local_path,
        )
        if success:
            return local_path, None
        return None, f'从 MinIO 下载预训练模型失败: {error_msg or "未知错误"}'

    if os.path.isabs(model_arch) and os.path.exists(model_arch):
        return model_arch, None

    for candidate in (
        os.path.join(ai_root, model_arch),
        os.path.join(ai_root, 'model', model_arch),
    ):
        if os.path.exists(candidate):
            return os.path.abspath(candidate), None

    # 标准 ultralytics 权重名（如 yolov8n.pt），由 YOLO 自行解析
    if '://' not in model_arch and not model_arch.startswith('/'):
        return model_arch, None

    return None, f'预训练模型路径不可用: {model_arch}'


@train_bp.route('/<int:task_id>/stop', methods=['POST'])
def api_stop_train(task_id):
    update_log(f"收到停止训练请求，任务ID: {task_id}", task_id)

    if task_id in train_status:
        train_status[task_id]['stop_requested'] = True
        train_status[task_id]['status'] = 'stopping'
        train_status[task_id]['message'] = '正在停止训练...'
        update_log("设置停止请求标志", task_id)

        if task_id in train_processes:
            pass

        return jsonify({'success': True, 'code': 0, 'msg': '停止请求已发送'}), 200

    train_task = TrainTask.query.get(task_id)
    if train_task and train_task.status in ACTIVE_TRAIN_STATUSES:
        stop_msg = (
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            "训练已停止（训练进程不在当前服务实例中）。"
        )
        train_task.status = 'stopped'
        train_task.end_time = datetime.utcnow()
        train_task.train_log = (train_task.train_log or '') + stop_msg + '\n'
        db.session.commit()
        return jsonify({'success': True, 'code': 0, 'msg': '训练任务已标记为停止'}), 200

    update_log("没有找到训练状态", task_id)
    return jsonify({'success': False, 'code': 0, 'msg': '没有正在进行的训练'}), 200


@train_bp.route('/<int:task_id>/status')
def api_train_status(task_id):
    status = train_status.get(task_id, {
        'status': 'idle',
        'message': '等待开始',
        'progress': 0
    })
    return jsonify({'status': status, 'code': 0, 'msg': 'success'}), 200


@train_bp.route('/gpu/status', methods=['GET'])
def api_gpu_status():
    """查询当前环境可见 GPU（与算法任务多卡探测逻辑一致）。"""
    return jsonify({
        'success': True,
        'code': 0,
        'msg': 'success',
        'data': check_gpu_status(),
    }), 200


@train_bp.route('/<int:task_id>/logs')
def api_train_log(task_id):
    """训练日志轮询接口，先返回内存中的日志数据，如果为空则查询数据库"""
    log_content = train_status.get(task_id, {}).get('log', '') if train_status.get(task_id) else ''

    # 如果缓存中日志为空，则从数据库查询最新训练记录
    if not log_content:
        try:
            train_task = TrainTask.query.filter_by(id=task_id).first()
            if train_task:
                log_content = train_task.train_log or ''

        except Exception as e:
            current_app.logger.error(f"查询训练记录失败: {str(e)}")

    # 返回日志数据
    return jsonify({
        'success': True,
        'code': 0,
        'data': log_content
    }), 200


def update_log(message, task_id=None, progress=None, train_task=None):
    """统一的日志记录函数"""
    log_message = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(log_message)

    if task_id is not None and task_id in train_status:
        train_status[task_id]['log'] += log_message + '\n'
        if progress is not None:
            train_status[task_id]['progress'] = progress

    # 如果提供了train_task，更新数据库记录
    if train_task is not None:
        train_task.train_log += log_message + '\n'
        if progress is not None:
            train_task.progress = progress
        try:
            db.session.commit()
        except Exception as e:
            print(f"数据库提交失败: {str(e)}")


def train_model(task_id, epochs=20, model_arch='yolov8n.pt',
                img_size=640, batch_size=16, use_gpu=True,
                dataset_zip_path=None, record_id=None, gpu_ids=None,
                dataset_source='local', resume_mode=False):
    """增强版训练函数，集成数据集下载和解压功能"""
    update_log(f"训练函数被调用，任务ID: {task_id}", task_id)
    train_task = None
    model_dir_for_cleanup = None
    dataset_path_for_cleanup = dataset_zip_path
    dataset_cleaned = False

    try:
        from run import create_app
        application = create_app()

        with application.app_context():
            # 在函数内部通过record_id获取训练记录
            train_task = TrainTask.query.get(record_id)
            
            # 重新获取train_task以确保在当前会话中
            db.session.refresh(train_task)

            # 更新日志函数
            def update_log_local(message, progress=None):
                update_log(message, task_id, progress, train_task)

            task_label = train_task.name if train_task and train_task.name else f'任务{task_id}'
            update_log_local(f"开始准备训练数据，任务: {task_label}")

            if train_status.get(task_id, {}).get('stop_requested'):
                log_msg = '训练已停止'
                train_status[task_id] = {
                    'status': 'stopped',
                    'message': log_msg,
                    'progress': 0,
                    'log': train_status[task_id].get('log', '') + log_msg + '\n'
                }
                update_log_local(log_msg)
                return

            # data/datasets/train_<id>/
            # ├── images /
            # │   ├── train /
            # │   └── val /
            # ├── labels /
            # │   ├── train /
            # │   └── val /
            # └── data.yaml
            # 检查数据集目录是否存在
            model_dir = os.path.join(get_project_root(), 'data/datasets', f'train_{task_id}')
            model_dir_for_cleanup = model_dir
            dataset_path_for_cleanup = dataset_zip_path
            data_yaml_path = os.path.join(model_dir, 'data.yaml')

            # 检查数据集目录结构完整性
            required_dirs = ['images/train', 'images/val', 'images/test', 'labels/train', 'labels/val', 'labels/test']
            all_dirs_exist = all(os.path.exists(os.path.join(model_dir, d)) for d in required_dirs)

            if os.path.exists(data_yaml_path) and all_dirs_exist:
                # 不再更新训练记录中的数据集路径，保持原始URL
                update_log_local(f"数据集验证成功，使用原始路径: {dataset_zip_path}")

            update_log_local(f"项目目录: {model_dir}")
            update_log_local(f"数据配置文件路径: {data_yaml_path}")
            update_log_local("检查数据集配置文件...")

            if not os.path.exists(data_yaml_path):
                source_label = '本地' if dataset_source == 'local' else '云端'
                log_msg = f'数据集配置文件不存在，正在准备{source_label}数据集...'
                train_status[task_id].update({
                    'message': '正在准备数据集...',
                    'progress': 5
                })
                update_log_local(log_msg, progress=5)

                if dataset_zip_path:
                    try:
                        _prepare_train_dataset_in_dir(
                            dataset_zip_path, model_dir, update_log_local
                        )
                    except Exception as prep_err:
                        update_log_local(f'数据集准备失败: {prep_err}')
                else:
                    update_log_local('未提供数据集路径，无法准备训练数据')

            # 检查是否应该停止训练
            if train_status.get(task_id, {}).get('stop_requested'):
                log_msg = '训练已停止'
                train_status[task_id] = {
                    'status': 'stopped',
                    'message': log_msg,
                    'progress': 0,
                    'log': train_status[task_id].get('log', '') + log_msg + '\n'
                }
                update_log_local(log_msg)
                return

            # 检查data.yaml文件是否存在
            if not os.path.exists(data_yaml_path):
                error_msg = "数据集配置文件不存在"
                update_log_local(error_msg)
                train_task.status = 'error'
                train_task.error_log = error_msg
                db.session.commit()
                raise Exception(error_msg)

            try:
                data_yaml_path = _normalize_dataset_yaml(model_dir, output_dir=model_dir)
                update_log_local(f'已标准化 data.yaml 路径: {data_yaml_path}')
            except Exception as norm_err:
                error_msg = f'data.yaml 路径标准化失败: {norm_err}'
                update_log_local(error_msg)
                train_task.status = 'error'
                train_task.error_log = error_msg
                db.session.commit()
                raise Exception(error_msg) from norm_err

            # 更新状态：开始加载模型
            train_status[task_id].update({
                'message': '加载预训练模型...',
                'progress': 10
            })
            update_log_local("加载预训练YOLOv8模型...", progress=10)

            resume_train = False
            if resume_mode:
                checkpoint_path = _resolve_resume_checkpoint(
                    train_task, model_dir, update_log_local
                )
                if not checkpoint_path:
                    error_msg = '找不到训练断点文件，无法继续训练'
                    update_log_local(error_msg)
                    train_task.status = 'error'
                    train_task.error_log = error_msg
                    db.session.commit()
                    raise Exception(error_msg)

                completed_epochs = _get_completed_epochs(train_task.hyperparameters)
                train_task.checkpoint_dir = checkpoint_path
                db.session.commit()
                update_log_local(
                    f'从断点恢复训练: {checkpoint_path} '
                    f'(已完成 {completed_epochs}/{epochs} epoch)'
                )
                try:
                    yolo_model = YOLO(checkpoint_path)
                    resume_train = True
                    update_log_local('断点权重加载成功，将从下一 epoch 继续训练')
                except Exception as e:
                    error_msg = f'断点权重加载失败: {str(e)}'
                    update_log_local(error_msg)
                    train_task.status = 'error'
                    train_task.error_log = error_msg
                    db.session.commit()
                    raise Exception(error_msg)
            else:
                update_log_local(f"尝试加载预训练模型: {model_arch}")
                local_model_arch, resolve_error = _resolve_pretrained_model_path(model_arch, task_id)
                if resolve_error:
                    update_log_local(resolve_error)
                    train_task.status = 'error'
                    train_task.error_log = resolve_error
                    db.session.commit()
                    raise Exception(resolve_error)
                if local_model_arch != model_arch:
                    update_log_local(f"预训练模型已解析为本地路径: {local_model_arch}")

                try:
                    yolo_model = YOLO(local_model_arch)
                    update_log_local("预训练模型加载成功!")
                except Exception as e:
                    error_msg = f"预训练模型加载失败: {str(e)}"
                    update_log_local(error_msg)
                    train_task.status = 'error'
                    train_task.error_log = error_msg
                    db.session.commit()
                    raise Exception(error_msg)

            # 保存模型引用以便可能的停止操作
            train_processes[task_id] = yolo_model

            # 更新状态：开始训练
            train_status[task_id].update({
                'status': 'train',
                'message': '正在训练模型...',
                'progress': 15
            })
            train_task.status = 'train'
            db.session.commit()
            if resume_mode:
                completed_epochs = _get_completed_epochs(train_task.hyperparameters)
                update_log_local(
                    f"继续训练模型，目标共 {epochs} 个 epochs（已完成 {completed_epochs}）...",
                    progress=15,
                )
            else:
                update_log_local(f"开始训练模型，共{epochs}个epochs...", progress=15)

            def on_train_epoch_end(trainer):
                if train_status.get(task_id, {}).get('stop_requested'):
                    raise RuntimeError('训练已被用户停止')
                total_epochs_count = max(1, int(getattr(trainer, 'epochs', epochs)))
                now_epoch = int(getattr(trainer, 'epoch', 0)) + 1
                progress = min(89, 15 + int(now_epoch * 74 / total_epochs_count))
                train_status[task_id].update({
                    'progress': progress,
                    'message': f'训练中 epoch {now_epoch}/{total_epochs_count}...',
                })
                train_task.progress = progress
                train_task.hyperparameters = _update_hyperparameters_field(
                    train_task.hyperparameters,
                    completed_epochs=now_epoch,
                )
                checkpoint_path = _resolve_train_checkpoint_path(model_dir)
                if checkpoint_path:
                    train_task.checkpoint_dir = checkpoint_path
                if now_epoch == 1 or now_epoch == total_epochs_count or now_epoch % 5 == 0:
                    update_log_local(
                        f'训练进度: epoch {now_epoch}/{total_epochs_count} ({progress}%)',
                        progress=progress,
                    )
                else:
                    try:
                        db.session.commit()
                    except Exception as commit_err:
                        print(f'更新训练进度失败: {commit_err}')

            yolo_model.add_callback('on_train_epoch_end', on_train_epoch_end)

            # 训练模型
            update_log_local(
                f"开始训练模型，配置: 数据文件={data_yaml_path}, epochs={epochs}, 图像尺寸={img_size}x{img_size}, 批次大小={batch_size}")

            gpu_status = check_gpu_status()
            update_log_local(f"GPU状态检查: {json.dumps(gpu_status, indent=2, ensure_ascii=False)}")

            device = resolve_yolo_train_device(use_gpu, gpu_ids)
            if device == 'cpu':
                if use_gpu:
                    update_log_local("警告: 请求使用GPU，但当前无可用 CUDA 设备，回退到 CPU 训练。")
                    update_log_local(
                        f"可能的原因: USE_GPU={gpu_status.get('use_gpu_env')}, "
                        f"PyTorch={torch.__version__}, CUDA={getattr(torch.version, 'cuda', '未知')}")
                else:
                    update_log_local("使用 CPU 进行训练")
            elif isinstance(device, list):
                names = []
                for idx in device:
                    try:
                        names.append(f"GPU{idx}({torch.cuda.get_device_name(idx)})")
                    except Exception:
                        names.append(f"GPU{idx}")
                update_log_local(
                    f"多卡并行训练 (DDP): {len(device)} 张 GPU [{format_device_for_log(device)}] — "
                    + ', '.join(names)
                )
                update_log_local(
                    f"提示: batch_size={batch_size} 为每张 GPU 的批次大小，有效总 batch≈{batch_size * len(device)}"
                )
            else:
                try:
                    gpu_name = torch.cuda.get_device_name(device)
                except Exception:
                    gpu_name = 'unknown'
                update_log_local(f"单卡 GPU 训练: GPU{device} ({gpu_name})")

            # 训练模型
            yolo_model.train(
                data=data_yaml_path,
                epochs=epochs,
                imgsz=img_size,
                batch=batch_size,
                project=model_dir,
                name='train_results',
                exist_ok=True,
                device=device,
                save_period=5,
                resume=resume_train,
            )

            train_output_dir = _resolve_train_results_dir(model_dir)
            model_id = train_task.model_id
            artifact_bucket = TRAIN_ARTIFACTS_BUCKET

            # 存储 results.csv（上传 Minio models 桶），路径写入 metrics_path
            results_csv_path = os.path.join(train_output_dir, 'results.csv')
            if os.path.exists(results_csv_path):
                minio_csv_path = _train_artifact_object_key(model_id, task_id, 'results.csv')
                csv_success, csv_error = ModelService.upload_to_minio(
                    bucket_name=artifact_bucket,
                    object_name=minio_csv_path,
                    file_path=results_csv_path,
                )
                if csv_success:
                    accessible_csv_url = _build_minio_download_url(artifact_bucket, minio_csv_path)
                    update_log_local(f"训练结果CSV已上传至Minio: {accessible_csv_url}")
                    train_task.metrics_path = accessible_csv_url
                else:
                    update_log_local(f"训练结果CSV上传Minio失败: {csv_error or '请检查日志'}")
            else:
                update_log_local(f"未找到训练结果CSV文件: {results_csv_path}")

            # 存储 results.png，路径写入 train_results_path
            results_png_path = os.path.join(train_output_dir, 'results.png')
            if os.path.exists(results_png_path):
                minio_png_path = _train_artifact_object_key(model_id, task_id, 'results.png')
                png_success, png_error = ModelService.upload_to_minio(
                    bucket_name=artifact_bucket,
                    object_name=minio_png_path,
                    file_path=results_png_path,
                )
                if png_success:
                    accessible_url = _build_minio_download_url(artifact_bucket, minio_png_path)
                    update_log_local(f"训练结果图表已上传至Minio: {accessible_url}")
                    train_task.train_results_path = accessible_url
                    db.session.commit()
                else:
                    update_log_local(f"训练结果图表上传Minio失败: {png_error or '请检查日志'}")
            else:
                update_log_local(f"未找到训练结果图表文件: {results_png_path}")

            # 检查是否应该停止训练
            if train_status.get(task_id, {}).get('stop_requested'):
                log_msg = '训练已停止'
                train_status[task_id] = {
                    'status': 'stopped',
                    'message': log_msg,
                    'progress': 0,
                    'log': train_status[task_id].get('log', '') + log_msg + '\n'
                }
                update_log_local(log_msg)
                return

            # 更新训练状态 - 训练完成
            train_status[task_id].update({
                'status': 'completed',
                'message': '训练完成，正在保存结果...',
                'progress': 90
            })
            update_log_local("训练完成，正在保存结果...", progress=90)

            update_log_local("模型训练完成!")
            update_log_local(f"训练结果保存路径: {train_output_dir}")

            # 保存最佳模型
            best_model_path = os.path.join(train_output_dir, 'weights', 'best.pt')
            update_log_local(f"检查最佳模型文件是否存在: {best_model_path}")

            if os.path.exists(best_model_path):
                update_log_local(f"找到最佳模型文件，开始复制到保存目录: {best_model_path}")

                # 将最佳模型复制到模型存储目录
                model_save_dir = os.path.join(current_app.root_path, 'static', 'train_tasks', str(task_id), 'weights')
                os.makedirs(model_save_dir, exist_ok=True)
                local_model_path = os.path.join(model_save_dir, 'best.pt')
                shutil.copy(best_model_path, local_model_path)

                update_log_local(f"模型文件已成功复制到保存目录: {model_save_dir}")

                # ================= Minio上传功能 =================
                update_log_local("开始上传最佳模型到Minio...", progress=95)

                # 上传最佳模型
                minio_model_path = _train_artifact_object_key(model_id, task_id, 'best.pt')
                model_success, model_error = ModelService.upload_to_minio(
                    bucket_name=artifact_bucket,
                    object_name=minio_model_path,
                    file_path=local_model_path
                )

                if model_success:
                    accessible_model_url = _build_minio_download_url(artifact_bucket, minio_model_path)
                    update_log_local(f"模型已成功上传至Minio: {accessible_model_url}")
                    train_task.minio_model_path = accessible_model_url
                    db.session.commit()
                else:
                    update_log_local("模型上传Minio失败，请检查日志")
                    train_task.best_model_path = local_model_path
                    db.session.commit()

                # 上传训练日志，参照results.png的写法
                log_content = train_task.train_log
                log_path = os.path.join(model_save_dir, f"train_log_{train_task.id}.txt")
                with open(log_path, 'w') as f:
                    f.write(log_content)

                minio_log_path = _train_artifact_object_key(model_id, task_id, 'train_log.txt')
                log_success, log_error = ModelService.upload_to_minio(
                    bucket_name=artifact_bucket,
                    object_name=minio_log_path,
                    file_path=log_path
                )

                if log_success:
                    accessible_log_url = _build_minio_download_url(artifact_bucket, minio_log_path)
                    update_log_local(f"训练日志已上传至Minio: {accessible_log_url}")
                    train_task.minio_log_path = accessible_log_url  # 保存URL而不是路径
                else:
                    update_log_local("训练日志上传Minio失败，请检查日志")
                # ================= Minio上传完成 =================

                # 更新训练记录中的本地模型路径
                train_task.best_model_path = local_model_path

            else:
                error_msg = "未找到训练完成的最佳模型文件"
                update_log_local(error_msg)
                train_task.status = 'error'
                train_task.error_log = error_msg
                db.session.commit()
                raise Exception(error_msg)

            # 更新训练状态 - 完成
            train_status[task_id].update({
                'status': 'completed',
                'message': '模型训练完成并已保存',
                'progress': 100
            })

            # 更新训练记录状态
            train_task.status = 'completed'
            train_task.end_time = datetime.utcnow()
            train_task.progress = 100
            train_task.checkpoint_dir = ''
            train_task.hyperparameters = _update_hyperparameters_field(
                train_task.hyperparameters,
                completed_epochs=epochs,
            )
            db.session.commit()
            update_log_local("模型训练完成并已保存", progress=100)

            _cleanup_train_dataset_artifacts(
                model_dir, dataset_zip_path, update_log_local
            )
            dataset_cleaned = True

    except Exception as e:
        from run import create_app
        user_stopped = (
            '训练已被用户停止' in str(e)
            or train_status.get(task_id, {}).get('stop_requested')
        )
        application = create_app()
        with application.app_context():
            task = TrainTask.query.get(record_id) if record_id else None
            error_msg = '训练已停止' if user_stopped else f'训练出错: {str(e)}'
            log_msg = f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {error_msg}'

            if task:
                task.status = 'stopped' if user_stopped else 'error'
                task.end_time = datetime.utcnow()
                if user_stopped:
                    task.train_log = (task.train_log or '') + log_msg + '\n'
                    model_dir = os.path.join(
                        get_project_root(), 'data/datasets', f'train_{task_id}'
                    )
                    completed_epochs = _get_completed_epochs(task.hyperparameters)
                    if completed_epochs <= 0 and task_id in train_status:
                        progress = train_status[task_id].get('progress', 0) or 0
                        total_epochs = _get_total_epochs_from_hp(task.hyperparameters, epochs)
                        if total_epochs > 0 and progress > 15:
                            completed_epochs = max(
                                1,
                                int((progress - 15) * total_epochs / 74),
                            )
                    _persist_stop_checkpoint(
                        task,
                        model_dir,
                        completed_epochs,
                        lambda msg: update_log(msg, task_id, train_task=task),
                    )
                else:
                    task.error_log = f"{str(e)}\n{traceback.format_exc()}"
                    task.train_log = (task.train_log or '') + log_msg + '\n'
                db.session.commit()

            update_log(error_msg, task_id, train_task=task)
            if not user_stopped:
                traceback.print_exc()

            if task_id in train_status:
                train_status[task_id].update({
                    'status': 'stopped' if user_stopped else 'error',
                    'message': error_msg,
                    'progress': train_status[task_id].get('progress', 0) if user_stopped else 0,
                    **({} if user_stopped else {
                        'error_details': str(e),
                        'traceback': traceback.format_exc(),
                    }),
                    'log': train_status[task_id].get('log', '') + log_msg + '\n'
                    + ('' if user_stopped else traceback.format_exc()),
                })
    finally:
        if task_id in train_processes:
            del train_processes[task_id]
        # 异常时清理已解压的数据集；停止状态保留数据集供断点续训
        if not dataset_cleaned and model_dir_for_cleanup:
            terminal = train_status.get(task_id, {}).get('status')
            if terminal == 'error':
                ds_path = dataset_path_for_cleanup
                if train_task and train_task.dataset_path:
                    ds_path = train_task.dataset_path

                def _log_cleanup(msg):
                    update_log(msg, task_id, train_task=train_task)

                try:
                    _cleanup_train_dataset_artifacts(
                        model_dir_for_cleanup, ds_path, _log_cleanup
                    )
                except Exception:
                    pass