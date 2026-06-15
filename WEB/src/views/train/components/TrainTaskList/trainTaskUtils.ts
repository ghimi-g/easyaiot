import { incrementPatchVersion } from '../../utils/modelVersionUtils';

export const ACTIVE_TRAIN_STATUSES = ['preparing', 'Train', 'train', 'running', 'stopping'];

export const RETRAINABLE_STATUSES = ['stopped', 'completed', 'error', 'failed'];

export function isTrainTaskActive(status?: string): boolean {
  return ACTIVE_TRAIN_STATUSES.includes(String(status || ''));
}

export function canRetrainTrainTask(status?: string): boolean {
  return RETRAINABLE_STATUSES.includes(String(status || ''));
}

export function canPublishTrainTask(record?: {
  status?: string;
  minio_model_path?: string;
}): boolean {
  return String(record?.status || '') === 'completed' && !!(record?.minio_model_path || '').trim();
}

export function getPublishedModelId(record?: {
  published_model_id?: number | string | null;
  hyperparameters?: unknown;
}): number | null {
  if (record?.published_model_id != null) {
    const id = Number(record.published_model_id);
    return Number.isNaN(id) ? null : id;
  }
  const hp = parseTrainHyperparameters(record?.hyperparameters);
  if (hp.published_model_id != null) {
    const id = Number(hp.published_model_id);
    return Number.isNaN(id) ? null : id;
  }
  return null;
}

export function getSuggestedPublishVersion(record?: {
  suggested_publish_version?: string | null;
  published_version?: string | null;
  hyperparameters?: unknown;
}): string {
  if (record?.suggested_publish_version) {
    return String(record.suggested_publish_version);
  }
  const hp = parseTrainHyperparameters(record?.hyperparameters);
  if (hp.published_version) {
    return incrementPatchVersion(String(hp.published_version));
  }
  if (record?.published_version) {
    return incrementPatchVersion(String(record.published_version));
  }
  return '1.0.0';
}

export function canResumeTrainTask(record?: {
  status?: string;
  can_resume?: boolean;
  checkpoint_dir?: string;
}): boolean {
  if (String(record?.status || '') !== 'stopped') return false;
  if (record?.can_resume === true) return true;
  return !!(record?.checkpoint_dir || '').trim();
}

export function getCompletedEpochs(record?: {
  completed_epochs?: number;
  hyperparameters?: unknown;
}): number {
  if (record?.completed_epochs != null) {
    return Number(record.completed_epochs) || 0;
  }
  const hp = parseTrainHyperparameters(record?.hyperparameters);
  return Number(hp.completed_epochs) || 0;
}

export function isCloudDatasetPath(path?: string): boolean {
  if (!path) return false;
  if (path.startsWith('/api/v1/buckets/')) return true;
  return path.includes('://') && !path.startsWith('file://');
}

export function parseTrainHyperparameters(raw: unknown) {
  try {
    const hp = typeof raw === 'string' ? JSON.parse(raw) : raw;
    if (!hp || typeof hp !== 'object') return {};
    return {
      epochs: hp.epochs ?? 100,
      batch_size: hp.batch_size ?? 16,
      imgsz: hp.img_size ?? hp.imgsz ?? 640,
      modelPath: hp.model_arch ?? 'yolov8n.pt',
      use_gpu: hp.use_gpu !== false,
      gpu_ids: hp.gpu_ids,
      taskName: hp.task_base_name ?? '',
      datasetSource: hp.dataset_source ?? 'local',
      completed_epochs: hp.completed_epochs ?? 0,
      published_model_id: hp.published_model_id ?? null,
      published_version: hp.published_version ?? null,
    };
  } catch {
    return {};
  }
}

export function resolveTaskBaseNameFromRecord(record: Record<string, unknown>): string {
  const hp = parseTrainHyperparameters(record.hyperparameters);
  if (hp.taskName) return hp.taskName;

  let base = String(record.name || record.task_name || '').trim();
  const taskId = record.id as number | undefined;
  if (taskId != null && base.endsWith(`_${taskId}`)) {
    base = base.slice(0, -(`_${taskId}`).length);
  }
  const dsName = String(record.dataset_name || '').trim();
  const dsVersion = String(record.dataset_version || '').trim();
  for (const part of [dsVersion, dsName]) {
    if (part && base.endsWith(`_${part}`)) {
      base = base.slice(0, -(part.length + 1));
    }
  }
  if (/^train_task_\d{8}_\d{6}$/.test(base) || base.startsWith('train_task_')) {
    return 'train';
  }
  return base || 'train';
}
