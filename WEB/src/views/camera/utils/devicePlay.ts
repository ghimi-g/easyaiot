import type { DeviceInfo, MonitorTreeDeviceNode } from '@/api/device/camera';
import { getDeviceInfo } from '@/api/device/camera';
import { playByDeviceAndChannel } from '@/api/device/gb28181';
import {
  formatCameraDeviceLabel,
  gb28181VirtualDeviceId,
  getGb28181PlayIds,
  isGb28181Device,
  shouldPlayViaGb28181,
} from './deviceLabel';
import { isProtectedStreamUrl, signStreamUrl } from './streamTicket';

export type DevicePlayModalOpener = (visible: boolean, data: Record<string, any>) => void;

export function isGb28181DeviceRecord(record: { source?: string | null; device_kind?: string }) {
  return isGb28181Device(record.source, record.device_kind);
}

export function hasDirectPlayStream(record: DeviceInfo, ai = false): boolean {
  if (isGb28181DeviceRecord(record)) return false;
  if ((record as { device_kind?: string }).device_kind === 'gb28181_sip') return false;
  if (ai) {
    return !!(record.ai_http_stream || record.ai_rtmp_stream);
  }
  return !!(record.http_stream || record.rtmp_stream);
}

type DirectStreamFields = Pick<
  DeviceInfo,
  'http_stream' | 'rtmp_stream' | 'ai_http_stream' | 'ai_rtmp_stream'
>;

export interface DirectPlayUrlResult {
  url: string | null;
  /** 启用 AI 时，AI 地址不可播则回退原始流 */
  fallbackUrl?: string | null;
  /** 已探测到 AI 流在推流，播放器超时后再回退原始流 */
  preferAi?: boolean;
}

/** 探测 AI 流是否在 ZLM 上就绪（毫秒） */
export const AI_STREAM_PROBE_MS = 2000;
/** AI 流播放超时后回退原始流（毫秒，仅 preferAi 时生效） */
export const AI_PLAY_FALLBACK_MS = 6000;

const LOCAL_STREAM_HOSTS = new Set(['localhost', '127.0.0.1', '0.0.0.0']);

/** 将服务端生成的 127.0.0.1/localhost 流地址改写为当前页面主机名，便于浏览器拉流 */
export function rewriteStreamUrlForBrowser(url: string): string {
  const trimmed = url?.trim();
  if (!trimmed || typeof window === 'undefined') return trimmed;

  try {
    const parsed = new URL(trimmed);
    const pageHost = window.location.hostname;
    if (!pageHost || LOCAL_STREAM_HOSTS.has(pageHost)) return trimmed;
    if (!LOCAL_STREAM_HOSTS.has(parsed.hostname)) return trimmed;

    parsed.hostname = pageHost;
    return parsed.toString();
  } catch {
    return trimmed;
  }
}

/**
 * 将流地址的主机名+端口改写为当前页面的 host（hostname:port），便于浏览器拉流。
 * 例如页面在 http://localhost:8888 打开时，
 * http://33.150.1.104:8080/ai/xxx.flv -> http://localhost:8888/ai/xxx.flv
 * 仅替换 host，协议与路径保持不变。
 */
export function rewriteStreamHostToPageHost(url: string): string {
  const trimmed = url?.trim();
  if (!trimmed || typeof window === 'undefined') return trimmed;

  try {
    const parsed = new URL(trimmed);
    const pageHost = window.location.host;
    if (!pageHost) return trimmed;

    parsed.host = pageHost;
    return parsed.toString();
  } catch {
    return trimmed;
  }
}

/** RTMP 转 HTTP-FLV（Jessibuca 浏览器端需 HTTP/WS 地址） */
export function convertRtmpToHttp(rtmpUrl: string): string | null {
  const trimmed = rtmpUrl?.trim();
  if (!trimmed || !trimmed.startsWith('rtmp://')) {
    return null;
  }
  try {
    const url = new URL(trimmed);
    const server = url.hostname;
    let path = url.pathname.replace(/^\//, '');
    if (!path) path = 'live';
    if (!path.endsWith('.flv')) path = `${path}.flv`;
    return rewriteStreamUrlForBrowser(`http://${server}:8080/${path}`);
  } catch {
    return null;
  }
}

function toBrowserPlayUrl(stream?: string | null): string | null {
  const trimmed = stream?.trim();
  if (!trimmed) return null;
  const httpUrl = trimmed.startsWith('rtmp://') ? convertRtmpToHttp(trimmed) : trimmed;
  if (!httpUrl) return null;
  // 所有播放地址统一走当前页面 host:port，便于不同环境下浏览器直接拉流
  return rewriteStreamHostToPageHost(httpUrl);
}

/** 是否为算法任务输出的 AI 流（检测框烧录在此路流上） */
export function isAiStreamPlayUrl(url?: string | null): boolean {
  if (!url) return false;
  return /\/ai\//i.test(url);
}

function pickVideoPlayUrl(device: DirectStreamFields): string | null {
  return toBrowserPlayUrl(device.http_stream) || toBrowserPlayUrl(device.rtmp_stream);
}

function pickAiPlayUrl(device: DirectStreamFields): string | null {
  return toBrowserPlayUrl(device.ai_http_stream) || toBrowserPlayUrl(device.ai_rtmp_stream);
}

/** 探测时判定"真有推流"所需的最小媒体字节数（FLV 头仅 13B，无推流方时只回头部就停） */
const PROBE_MIN_MEDIA_BYTES = 1024;

/**
 * 快速探测流是否可播（避免无算法任务时长时间等待空 AI 地址）。
 * 仅返回 200/FLV 头不足为据：SRS 对任何 FLV 请求都会临时创建空源并回头部，
 * 因此必须确认在超时窗口内确有媒体数据流过，才认定 AI 流已就绪。
 * 探测失败时返回 false，调用方应直接播原始流。
 */
export async function probeStreamPlayable(
  url: string,
  timeoutMs = AI_STREAM_PROBE_MS,
): Promise<boolean> {
  let target = url?.trim();
  if (!target || typeof window === 'undefined') return false;
  // 探测直连 fetch /ai 地址，受 secure_link 保护，需先签名（开启强制校验时未签名恒 403）。
  // 签发失败则降级探测未签名地址：强制校验关闭时仍能正常探测，开启时会 403 -> 探测返回 false -> 回退原始流。
  if (isProtectedStreamUrl(target)) {
    try {
      target = await signStreamUrl(target);
    } catch {
      /* 降级：保留未签名地址继续探测 */
    }
  }
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(target, {
      method: 'GET',
      signal: controller.signal,
      cache: 'no-store',
    });
    if (res.status === 404 || res.status === 403) return false;
    if (!res.ok && res.status !== 206) return false;
    if (!res.body) return false;

    const reader = res.body.getReader();
    let received = 0;
    try {
      while (received < PROBE_MIN_MEDIA_BYTES) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) received += value.length;
      }
    } finally {
      // 停止拉流，释放 SRS 上的临时消费连接
      try {
        await reader.cancel();
      } catch {
        /* ignore */
      }
    }
    return received >= PROBE_MIN_MEDIA_BYTES;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timer);
  }
}

/** 直连设备播放地址：启用 AI 时优先 AI 流，无 AI 地址则回退原始流；未启用时仅原始流 */
export async function pickDirectPlayUrl(
  device: DirectStreamFields,
  enableAi = false,
): Promise<string | null> {
  return (await pickDirectPlayUrls(device, enableAi)).url;
}

export async function pickDirectPlayUrls(
  device: DirectStreamFields,
  enableAi = false,
): Promise<DirectPlayUrlResult> {
  const videoUrl = pickVideoPlayUrl(device);
  if (!enableAi) {
    return { url: videoUrl };
  }

  const aiUrl = pickAiPlayUrl(device);
  if (!aiUrl) {
    return { url: videoUrl };
  }
  if (aiUrl === videoUrl) {
    return { url: aiUrl };
  }

  // ai_http_stream 在库中常为预置占位地址（国标同步即有），须探测 ZLM 是否在推流
  const aiReady = await probeStreamPlayable(aiUrl);
  if (!aiReady) {
    return { url: videoUrl };
  }
  if (!videoUrl) {
    return { url: aiUrl };
  }
  return { url: aiUrl, fallbackUrl: videoUrl, preferAi: true };
}

export function supportsRtspForward(record: DeviceInfo): boolean {
  return !isGb28181DeviceRecord(record);
}

/** 从 WVP 点播结果中选取浏览器可播地址（HTTPS 页优先 wss/https，并做 localhost 改写） */
export function pickWvpPlayUrl(streamContent: Record<string, any> | null | undefined): string | null {
  if (!streamContent) return null;
  const isHttps =
    typeof window !== 'undefined' && window.location.protocol === 'https:';
  const candidates = isHttps
    ? [
        streamContent.wss_flv,
        streamContent.https_flv,
        streamContent.wss_fmp4,
        streamContent.https_fmp4,
        streamContent.ws_flv,
        streamContent.flv,
        streamContent.fmp4,
      ]
    : [
        streamContent.ws_flv,
        streamContent.flv,
        streamContent.ws_fmp4,
        streamContent.fmp4,
        streamContent.https_flv,
        streamContent.wss_flv,
      ];
  for (const raw of candidates) {
    const url = toBrowserPlayUrl(raw);
    if (url) return url;
  }
  return toBrowserPlayUrl(streamContent.rtmp);
}

export async function resolveGb28181StreamUrl(
  sipDeviceId: string,
  channelId: string,
): Promise<string | null> {
  const res = await playByDeviceAndChannel(sipDeviceId, channelId);
  const streamContent = (res as any)?.data?.data ?? (res as any)?.data;
  return pickWvpPlayUrl(streamContent);
}

export interface GbChannelPlayUrlResult {
  url: string | null;
  fallbackUrl?: string | null;
  preferAi?: boolean;
}

/** 加载国标通道对应的 device 表记录（含 ai_http_stream） */
export async function loadGbChannelSyncedDevice(
  sipDeviceId: string,
  channelId: string,
  synced?: MonitorTreeDeviceNode | null,
): Promise<MonitorTreeDeviceNode | null> {
  if (synced?.ai_http_stream?.trim() || synced?.ai_rtmp_stream?.trim()) {
    return synced;
  }
  // 目录树已有同步设备但无 AI 地址时，跳过详情请求，直接走 WVP 点播
  if (synced?.id) {
    return synced;
  }
  try {
    const res = await getDeviceInfo(gb28181VirtualDeviceId(sipDeviceId, channelId));
    const device = (res as any)?.data ?? res;
    return device?.id ? (device as MonitorTreeDeviceNode) : synced ?? null;
  } catch {
    return synced ?? null;
  }
}

/**
 * 国标通道播放地址：启用 AI 时优先 ai_http_stream（算法烧录检测框），否则 WVP 点播原始流。
 */
export async function resolveGbChannelPlayUrls(
  sipDeviceId: string,
  channelId: string,
  options?: {
    enableAi?: boolean;
    synced?: MonitorTreeDeviceNode | null;
    wvpUrl?: string | null;
  },
): Promise<GbChannelPlayUrlResult> {
  const enableAi = options?.enableAi ?? false;
  const wvpPromise =
    options?.wvpUrl != null
      ? Promise.resolve(options.wvpUrl)
      : resolveGb28181StreamUrl(sipDeviceId, channelId);

  if (!enableAi) {
    return { url: await wvpPromise };
  }

  const [wvpUrl, synced] = await Promise.all([
    wvpPromise,
    loadGbChannelSyncedDevice(sipDeviceId, channelId, options?.synced ?? null),
  ]);

  if (synced) {
    const { url, fallbackUrl, preferAi } = await pickDirectPlayUrls(
      synced as DirectStreamFields,
      true,
    );
    if (url) {
      return {
        url,
        fallbackUrl: fallbackUrl ?? wvpUrl,
        preferAi,
      };
    }
  }

  return { url: wvpUrl };
}

export function buildDialogPlayerPayload(
  record: DeviceInfo,
  options?: { ai?: boolean },
): Record<string, any> {
  const name = formatCameraDeviceLabel(record);

  if (options?.ai) {
    const aiUrl = pickAiPlayUrl(record);
    const videoUrl = pickVideoPlayUrl(record);
    return {
      ...record,
      name,
      http_stream: aiUrl || videoUrl || undefined,
    };
  }

  const gbIds = getGb28181PlayIds(record as Record<string, any>);
  if (gbIds) {
    return {
      ...record,
      name,
      deviceIdentification: gbIds.sipDeviceId,
      channelId: gbIds.channelId,
      http_stream: undefined,
    };
  }

  return { ...record, name };
}

export function openDeviceInDialogPlayer(
  openModal: DevicePlayModalOpener,
  record: DeviceInfo,
  options?: { ai?: boolean },
) {
  if (!hasDirectPlayStream(record, options?.ai) && !shouldPlayViaGb28181(record)) {
    return false;
  }
  openModal(true, buildDialogPlayerPayload(record, options));
  return true;
}

export async function resolveMonitorPlayUrl(
  device: DeviceInfo,
  streamType: 'video' | 'ai' = 'video',
): Promise<string | null> {
  if (streamType === 'ai') {
    return pickAiPlayUrl(device);
  }

  const gbIds = getGb28181PlayIds(device as Record<string, any>);
  if (gbIds) {
    return resolveGb28181StreamUrl(gbIds.sipDeviceId, gbIds.channelId);
  }

  return pickVideoPlayUrl(device);
}
