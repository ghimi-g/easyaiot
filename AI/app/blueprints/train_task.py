"""
@author 翱翔的雄库鲁
@email andywebjava@163.com
@wechat EasyAIoT2025
"""
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import requests
from flask import Blueprint, request, jsonify
from sqlalchemy import desc, or_
from sqlalchemy.exc import IntegrityError

from app.services.minio_service import ModelService
from app.utils.image_utils import download_default_model_image
from app.utils.model_class_utils import (
    dump_class_names_json,
    extract_class_names_from_model,
)
from db_models import db, Model, TrainTask

train_task_bp = Blueprint('train_task', __name__)
logger = logging.getLogger(__name__)

TASK_NAME_MAX_LEN = 200
DEFAULT_TASK_BASE_NAME = 'train'
LEGACY_TIMESTAMP_BASE = re.compile(r'^train_task_\d{8}_\d{6}$')


def _strip_task_id_suffix(name: str, task_id: int | None) -> str:
    if not name or task_id is None:
        return (name or '').strip()
    suffix = f'_{task_id}'
    if name.endswith(suffix):
        return name[:-len(suffix)].strip()
    return name.strip()


def resolve_task_base_name(task: TrainTask) -> str:
    """解析用户填写的任务名前缀，避免把整段历史拼接名当作 base。"""
    if task.hyperparameters:
        try:
            hp = json.loads(task.hyperparameters)
            for key in ('task_base_name', 'taskName', 'task_name'):
                val = (hp.get(key) or '').strip()
                if val:
                    return val
        except (json.JSONDecodeError, TypeError):
            pass

    stored = _strip_task_id_suffix((task.name or '').strip(), task.id)
    ds = (task.dataset_name or '').strip()
    dv = (task.dataset_version or '').strip()
    for extra in (dv, ds):
        if extra and stored.endswith(f'_{extra}'):
            stored = stored[: -(len(extra) + 1)]

    if LEGACY_TIMESTAMP_BASE.match(stored) or stored.startswith('train_task_'):
        return DEFAULT_TASK_BASE_NAME

    return stored or DEFAULT_TASK_BASE_NAME


def build_train_task_name(
    base_name=None,
    dataset_name=None,
    dataset_version=None,
    task_id=None,
) -> str:
    """格式: {用户任务名}_{数据集名}_{版本}_{任务ID}，例如 train_人_v1.0.0_19"""
    base = _strip_task_id_suffix((base_name or '').strip(), task_id)
    if LEGACY_TIMESTAMP_BASE.match(base) or base.startswith('train_task_'):
        base = DEFAULT_TASK_BASE_NAME
    if not base:
        base = DEFAULT_TASK_BASE_NAME

    ds = (dataset_name or '').strip()
    dv = (dataset_version or '').strip()
    for extra in (dv, ds):
        if extra and base.endswith(f'_{extra}'):
            base = base[: -(len(extra) + 1)]

    parts = [base]
    if ds:
        parts.append(ds)
    if dv:
        parts.append(dv)
    if task_id is not None:
        parts.append(str(task_id))

    return '_'.join(parts)[:TASK_NAME_MAX_LEN]


def _dataset_path_key(dataset_path: str) -> str:
    if not dataset_path:
        return ''
    parsed = urlparse(dataset_path)
    prefix_list = parse_qs(parsed.query).get('prefix')
    if prefix_list and prefix_list[0]:
        return prefix_list[0]
    return dataset_path.rstrip('/').split('/')[-1]


def _build_dataset_zip_map(items) -> dict:
    """zipUrl / 路径前缀 -> {name, version}"""
    dataset_map = {}
    for item in items or []:
        name = (item.get('name') or '').strip()
        version = (item.get('version') or '').strip()
        zip_url = (item.get('zipUrl') or '').strip()
        if not zip_url:
            continue
        info = {'name': name, 'version': version}
        dataset_map[zip_url] = info
        path_key = _dataset_path_key(zip_url)
        if path_key:
            dataset_map[path_key] = info
    return dataset_map


def _load_dataset_zip_map() -> dict:
    java_url = os.getenv('JAVA_BACKEND_URL', 'http://localhost:8080').rstrip('/')
    headers = {}
    auth = request.headers.get('Authorization') or request.headers.get('X-Authorization')
    if auth:
        headers['Authorization'] = auth

    try:
        resp = requests.get(
            f'{java_url}/admin-api/dataset/page',
            params={'pageNo': 1, 'pageSize': 500, 'page': 1, 'size': 500},
            headers=headers,
            timeout=8,
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get('data')
        if isinstance(data, dict):
            items = data.get('list') or data.get('records') or []
        elif isinstance(data, list):
            items = data
        else:
            items = body.get('list') or []
        return _build_dataset_zip_map(items)
    except Exception as e:
        logger.warning('加载数据集列表失败，训练任务名将无法补全数据集信息: %s', e)
        return {}


def _lookup_dataset_info(dataset_map: dict, dataset_path: str):
    if not dataset_path or not dataset_map:
        return None
    if dataset_path in dataset_map:
        return dataset_map[dataset_path]
    path_key = _dataset_path_key(dataset_path)
    if path_key and path_key in dataset_map:
        return dataset_map[path_key]
    return None


def _is_local_filesystem_dataset_path(dataset_path: str) -> bool:
    """已落盘的本地 zip/目录，不应再用云端数据集映射覆盖名称。"""
    if not dataset_path:
        return False
    if dataset_path.startswith('/api/v1/buckets/'):
        return False
    if '://' in dataset_path and not dataset_path.startswith('file://'):
        return False
    return os.path.exists(dataset_path)


def _enrich_task_metadata(task: TrainTask, dataset_map: dict) -> bool:
    """补全缺失的数据集字段与任务名，返回是否有字段变更。"""
    changed = False
    info = None
    if not _is_local_filesystem_dataset_path(task.dataset_path):
        info = _lookup_dataset_info(dataset_map, task.dataset_path)
    if info:
        if not task.dataset_name and info.get('name'):
            task.dataset_name = info['name']
            changed = True
        if task.dataset_version in (None, '') and info.get('version'):
            task.dataset_version = info['version']
            changed = True

    new_name = build_train_task_name(
        resolve_task_base_name(task),
        task.dataset_name,
        task.dataset_version,
        task.id,
    )
    if (task.name or '') != new_name:
        task.name = new_name
        changed = True
    return changed


def _task_display_name(task: TrainTask) -> str:
    if (task.name or '').strip():
        return task.name.strip()
    return build_train_task_name(
        resolve_task_base_name(task),
        task.dataset_name,
        task.dataset_version,
        task.id,
    )


def _apply_task_name_filter(query, keyword: str):
    """按任务名、数据集名称、版本及数据集路径模糊搜索。"""
    pattern = f'%{keyword}%'
    return query.filter(
        or_(
            TrainTask.name.ilike(pattern),
            TrainTask.dataset_name.ilike(pattern),
            TrainTask.dataset_version.ilike(pattern),
            TrainTask.dataset_path.ilike(pattern),
        )
    )


def _apply_progress_filter(query, progress_filter: str):
    if progress_filter == 'not_started':
        return query.filter(or_(TrainTask.progress.is_(None), TrainTask.progress <= 0))
    if progress_filter == 'in_progress':
        return query.filter(TrainTask.progress > 0, TrainTask.progress < 100)
    if progress_filter == 'completed':
        return query.filter(TrainTask.progress >= 100)
    return query


def _get_project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))


def _safe_remove_path(path: str) -> None:
    """删除本地文件或目录；路径不存在时静默跳过。"""
    if not path or not os.path.exists(path):
        return
    if os.path.isfile(path) or os.path.islink(path):
        os.remove(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)


def _cleanup_train_task_artifacts(record: TrainTask) -> None:
    """清理训练任务关联的本地文件（数据集工作区、断点权重等）。"""
    model_dir = os.path.join(_get_project_root(), 'data', 'datasets', f'train_{record.id}')
    _safe_remove_path(model_dir)

    # checkpoint_dir 实际存的是 last.pt 文件路径，不是目录
    _safe_remove_path((record.checkpoint_dir or '').strip())

    for extra in (record.train_log, record.metrics_path):
        if not extra:
            continue
        extra = extra.strip()
        if os.path.isabs(extra) and os.path.exists(extra):
            _safe_remove_path(extra)


def _parse_train_hyperparameters(hp_text: str) -> dict:
    if not hp_text:
        return {}
    try:
        return json.loads(hp_text)
    except (json.JSONDecodeError, TypeError):
        return {}


def _get_completed_epochs(hp_text: str) -> int:
    return int(_parse_train_hyperparameters(hp_text).get('completed_epochs') or 0)


def _resolve_train_checkpoint_path(model_dir: str) -> str | None:
    if not model_dir or not os.path.isdir(model_dir):
        return None
    candidates = []
    for name in os.listdir(model_dir):
        if not name.startswith('train_results'):
            continue
        path = os.path.join(model_dir, name)
        if os.path.isdir(path):
            candidates.append(name)
    for name in sorted(candidates, reverse=True):
        results_dir = os.path.join(model_dir, name)
        last_pt = os.path.join(results_dir, 'weights', 'last.pt')
        if os.path.isfile(last_pt):
            return os.path.abspath(last_pt)
    return None


def _task_can_resume(task: TrainTask) -> bool:
    if task.status != 'stopped':
        return False
    checkpoint = (task.checkpoint_dir or '').strip()
    if checkpoint and os.path.isfile(checkpoint):
        return True
    model_dir = os.path.join(_get_project_root(), 'data', 'datasets', f'train_{task.id}')
    return _resolve_train_checkpoint_path(model_dir) is not None


def _normalize_model_version(version) -> str:
    text = str(version or '').strip()
    if text.lower().startswith('v'):
        text = text[1:].lstrip()
    return text or '1.0.0'


def _parse_minio_url(url: str):
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
    except Exception as exc:
        logger.error('解析 MinIO URL 失败: %s, error=%s', url, exc)
        return None, None


def _get_published_model_id(hp_text: str) -> int | None:
    published_id = _parse_train_hyperparameters(hp_text).get('published_model_id')
    if published_id is None:
        return None
    try:
        return int(published_id)
    except (TypeError, ValueError):
        return None


_SEMVER_RE = re.compile(r'^(\d+)\.(\d+)\.(\d+)(?:[.-].*)?$')


def _parse_semver(version: str) -> tuple[int, int, int] | None:
    normalized = _normalize_model_version(version)
    match = _SEMVER_RE.match(normalized)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _format_semver(major: int, minor: int, patch: int) -> str:
    return f'{major}.{minor}.{patch}'


def _increment_patch_version(version: str) -> str:
    parsed = _parse_semver(version)
    if parsed:
        major, minor, patch = parsed
        return _format_semver(major, minor, patch + 1)
    return '1.0.0'


def _max_semver(versions: list[str]) -> str | None:
    parsed_versions: list[tuple[tuple[int, int, int], str]] = []
    for version in versions:
        parsed = _parse_semver(version)
        if parsed:
            parsed_versions.append((parsed, _normalize_model_version(version)))
    if not parsed_versions:
        return None
    parsed_versions.sort(key=lambda item: item[0])
    return parsed_versions[-1][1]


def _get_published_version(hp_text: str) -> str | None:
    published_version = _parse_train_hyperparameters(hp_text).get('published_version')
    if not published_version:
        return None
    normalized = _normalize_model_version(str(published_version))
    return normalized or None


def _resolve_next_publish_version(task: TrainTask, name: str) -> str:
    """根据任务历史与同名校模型的最高版本，计算下一次发布的递增版本号。"""
    candidate_versions: list[str] = []

    published_version = _get_published_version(task.hyperparameters)
    if published_version:
        candidate_versions.append(published_version)

    published_model_id = _get_published_model_id(task.hyperparameters)
    if published_model_id:
        published_model = Model.query.get(published_model_id)
        if published_model and published_model.version:
            candidate_versions.append(published_model.version)

    same_name_models = Model.query.filter(
        db.func.lower(Model.name) == db.func.lower(name),
    ).all()
    for model in same_name_models:
        if model.version:
            candidate_versions.append(model.version)

    latest_version = _max_semver(candidate_versions)
    if latest_version:
        return _increment_patch_version(latest_version)
    return '1.0.0'


def _set_published_model_id(task: TrainTask, model_id: int, version: str) -> None:
    hp = _parse_train_hyperparameters(task.hyperparameters)
    hp['published_model_id'] = model_id
    hp['published_version'] = _normalize_model_version(version)
    task.hyperparameters = json.dumps(hp)


def _default_publish_name(task: TrainTask) -> str:
    base = resolve_task_base_name(task)
    ds_name = (task.dataset_name or '').strip()
    if ds_name and base == DEFAULT_TASK_BASE_NAME:
        return ds_name
    return base or _task_display_name(task)


def _upload_default_model_image() -> str | None:
    temp_dir = 'temp_uploads'
    os.makedirs(temp_dir, exist_ok=True)
    default_image_filename = f'default_model_{uuid.uuid4().hex}.png'
    default_image_path = os.path.join(temp_dir, default_image_filename)
    try:
        if not download_default_model_image(default_image_path):
            return None
        bucket_name = 'models'
        image_object_key = f'images/{default_image_filename}'
        upload_success, _ = ModelService.upload_to_minio(
            bucket_name, image_object_key, default_image_path
        )
        if upload_success:
            return f'/api/v1/buckets/{bucket_name}/objects/download?prefix={image_object_key}'
    except Exception as exc:
        logger.warning('上传默认模型图片失败: %s', exc)
    finally:
        if os.path.exists(default_image_path):
            try:
                os.remove(default_image_path)
            except OSError:
                pass
    return None


def _extract_class_names_from_minio_model(model_url: str) -> list[str]:
    bucket_name, object_key = _parse_minio_url(model_url)
    if not bucket_name or not object_key:
        return []

    ext = os.path.splitext(object_key)[1] or '.pt'
    temp_fd, temp_path = tempfile.mkstemp(suffix=ext)
    os.close(temp_fd)
    try:
        success, error_msg = ModelService.download_from_minio(bucket_name, object_key, temp_path)
        if not success:
            logger.warning('下载训练权重失败，无法提取类别: %s', error_msg)
            return []
        return extract_class_names_from_model(temp_path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _serialize_task(task: TrainTask) -> dict:
    completed_epochs = _get_completed_epochs(task.hyperparameters)
    can_resume = _task_can_resume(task)
    published_model_id = _get_published_model_id(task.hyperparameters)
    suggested_publish_version = None
    if task.status == 'completed' and (task.minio_model_path or '').strip():
        suggested_publish_version = _resolve_next_publish_version(
            task, _default_publish_name(task),
        )
    return {
        'id': task.id,
        'name': _task_display_name(task),
        'task_name': task.name,
        'dataset_path': task.dataset_path,
        'dataset_name': task.dataset_name,
        'dataset_version': task.dataset_version,
        'hyperparameters': task.hyperparameters,
        'start_time': task.start_time.isoformat() if task.start_time else None,
        'progress': task.progress,
        'end_time': task.end_time.isoformat() if task.end_time else None,
        'status': task.status,
        'metrics_path': task.metrics_path,
        'train_results_path': task.train_results_path,
        'minio_model_path': task.minio_model_path,
        'checkpoint_dir': task.checkpoint_dir,
        'completed_epochs': completed_epochs,
        'can_resume': can_resume,
        'published_model_id': published_model_id,
        'published_version': _get_published_version(task.hyperparameters),
        'suggested_publish_version': suggested_publish_version,
    }


@train_task_bp.route('/list', methods=['GET'])
def train_tasks():
    try:
        page_no = int(request.args.get('pageNo', 1))
        page_size = int(request.args.get('pageSize', 10))
        task_name = (
            request.args.get('task_name')
            or request.args.get('taskName')
            or request.args.get('model_name')
            or ''
        ).strip()
        progress_filter = (
            request.args.get('progress_filter')
            or request.args.get('progressFilter')
            or ''
        ).strip()

        if page_no < 1 or page_size < 1:
            return jsonify({
                'code': 400,
                'msg': '参数错误：pageNo和pageSize必须为正整数'
            }), 400

        query = TrainTask.query
        if task_name:
            query = _apply_task_name_filter(query, task_name)

        if progress_filter:
            query = _apply_progress_filter(query, progress_filter)

        query = query.order_by(desc(TrainTask.start_time))
        pagination = query.paginate(page=page_no, per_page=page_size, error_out=False)

        dataset_map = _load_dataset_zip_map()
        records = []
        dirty_tasks = []
        for task in pagination.items:
            if _enrich_task_metadata(task, dataset_map):
                dirty_tasks.append(task)
            records.append(_serialize_task(task))

        if dirty_tasks:
            try:
                db.session.commit()
            except Exception as e:
                logger.warning('补全训练任务元数据失败: %s', e)
                db.session.rollback()

        return jsonify({
            'code': 0,
            'msg': 'success',
            'data': records,
            'total': pagination.total
        })

    except ValueError:
        return jsonify({
            'code': 400,
            'msg': '参数类型错误：pageNo和pageSize需为整数'
        }), 400
    except Exception as e:
        logger.error(f'训练记录查询失败: {str(e)}')
        return jsonify({
            'code': 500,
            'msg': '服务器内部错误'
        }), 500


@train_task_bp.route('/<int:record_id>')
def train_detail(record_id):
    try:
        record = TrainTask.query.get(record_id)
        if not record:
            return jsonify({
                'code': 404,
                'msg': f'训练记录ID {record_id} 不存在'
            }), 404

        data = _serialize_task(record)
        data['train_log'] = record.train_log
        data['checkpoint_dir'] = record.checkpoint_dir

        return jsonify({
            'code': 0,
            'msg': 'success',
            'data': data
        })

    except Exception as e:
        logger.error(f'获取训练记录详情失败: {str(e)}')
        return jsonify({
            'code': 500,
            'msg': '服务器内部错误'
        }), 500


@train_task_bp.route('/<int:record_id>/publish', methods=['POST'])
def publish_train_task(record_id):
    """将已完成训练任务的权重发布到模型管理，供推理与算法任务使用。"""
    temp_path = None
    try:
        task = TrainTask.query.get(record_id)
        if not task:
            return jsonify({'code': 404, 'msg': f'训练记录ID {record_id} 不存在'}), 404

        if task.status != 'completed':
            return jsonify({'code': 400, 'msg': '仅已完成训练的任务可发布到模型管理'}), 400

        model_url = (task.minio_model_path or '').strip()
        if not model_url:
            return jsonify({'code': 400, 'msg': '训练权重尚未上传，无法发布'}), 400

        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip() or _default_publish_name(task)
        description = (data.get('description') or '').strip()
        if not description:
            description = f'从训练任务「{_task_display_name(task)}」发布'

        explicit_version = (data.get('version') or '').strip()
        auto_increment = data.get('auto_increment')
        if auto_increment is None:
            auto_increment = not explicit_version
        if auto_increment or not explicit_version:
            version = _resolve_next_publish_version(task, name)
        else:
            version = _normalize_model_version(explicit_version)

        class_names = _extract_class_names_from_minio_model(model_url)
        image_url = _upload_default_model_image()

        published_model_id = _get_published_model_id(task.hyperparameters)
        existing_model = None
        if published_model_id:
            existing_model = Model.query.get(published_model_id)

        if existing_model:
            conflict = Model.query.filter(
                db.func.lower(Model.name) == db.func.lower(name),
                Model.version == version,
                Model.id != existing_model.id,
            ).first()
            if conflict:
                return jsonify({
                    'code': 400,
                    'msg': f'模型"{name}"版本"{version}"已存在，请使用其他名称或版本号',
                }), 400

            existing_model.name = name
            existing_model.description = description
            existing_model.version = version
            existing_model.model_path = model_url
            existing_model.status = 0
            existing_model.updated_at = datetime.utcnow()
            if image_url and not existing_model.image_url:
                existing_model.image_url = image_url
            if class_names:
                existing_model.class_names = dump_class_names_json(class_names)
                existing_model.selected_class_names = dump_class_names_json(class_names)
            model = existing_model
            action_msg = '模型已更新发布'
        else:
            conflict = Model.query.filter(
                db.func.lower(Model.name) == db.func.lower(name),
                Model.version == version,
            ).first()
            if conflict:
                return jsonify({
                    'code': 400,
                    'msg': f'模型"{name}"版本"{version}"已存在，请使用其他名称或版本号',
                }), 400

            model = Model(
                name=name,
                description=description,
                model_path=model_url,
                image_url=image_url,
                version=version,
                status=0,
                class_names=dump_class_names_json(class_names) if class_names else None,
                selected_class_names=dump_class_names_json(class_names) if class_names else None,
            )
            db.session.add(model)
            action_msg = '模型发布成功'

        db.session.flush()
        _set_published_model_id(task, model.id, version)
        db.session.commit()

        return jsonify({
            'code': 0,
            'msg': action_msg,
            'data': {
                'model_id': model.id,
                'name': model.name,
                'version': model.version,
                'model_path': model.model_path,
                'published_model_id': model.id,
            },
        })
    except IntegrityError as exc:
        db.session.rollback()
        logger.error('发布训练模型失败（名称冲突）: %s', exc)
        return jsonify({'code': 400, 'msg': '模型名称或版本已存在，请修改后重试'}), 400
    except Exception as exc:
        db.session.rollback()
        logger.error('发布训练模型失败: %s', exc, exc_info=True)
        return jsonify({'code': 500, 'msg': f'发布失败: {exc}'}), 500
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


@train_task_bp.route('/delete/<int:record_id>', methods=['DELETE'])
def delete_train(record_id):
    try:
        record = TrainTask.query.get_or_404(record_id)

        _cleanup_train_task_artifacts(record)

        db.session.delete(record)
        db.session.commit()

        return jsonify({
            'code': 0,
            'msg': '训练记录删除成功'
        })

    except Exception as e:
        logger.error(f'删除训练记录失败: {str(e)}')
        db.session.rollback()
        return jsonify({
            'code': 500,
            'msg': '服务器内部错误'
        }), 500
