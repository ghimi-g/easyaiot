<template>
  <div :class="['split-screen-container', { 'fullscreen-mode': state.isFull }]">
    <a-layout class="monitor-layout">
      <a-layout-sider :width="350" class="device-tree-sider" theme="light">
        <CollapseContainer :can-expan="true" class="tree-container">
          <template #title>
            <div class="tree-header-title">
              <span class="tree-header-title__icon">
                <Icon icon="ant-design:folder-outlined" :size="16" />
              </span>
              <span class="tree-header-title__text">设备目录</span>
            </div>
          </template>
          <template #action="{ expand, onClick }">
            <div class="tree-header-actions">
              <AButton :loading="treeLoading || treeRefreshing" @click.stop="handleRefresh">
                <template #icon>
                  <Icon icon="ant-design:reload-outlined" />
                </template>
                刷新
              </AButton>
              <BasicArrow up :expand="expand" @click="onClick" />
            </div>
          </template>
          <div class="tree-scroll">
            <BasicTree
              search
              :showIcon="true"
              :indent="12"
              v-model:selectedKeys="selectedKeys"
              :expanded-keys="expandedKeys"
              :tree-data="treeData"
              :load-data="onLoadGbDeviceChannels"
              :field-names="{ key: 'key', title: 'title' }"
              class="device-tree"
              @select="handleTreeSelect"
              @update:expanded-keys="expandedKeys = $event"
            />
          </div>
        </CollapseContainer>
      </a-layout-sider>

      <a-layout class="monitor-content-layout">
        <a-layout-header class="toolbar-header">
          <div class="toolbar-content">
            <div class="toolbar-section">
              <a-radio-group
                v-model:value="state.splitMode"
                size="middle"
                button-style="solid"
                class="split-mode-group"
                @change="handleSplitModeChange"
              >
                <a-radio-button :value="1">1分屏</a-radio-button>
                <a-radio-button :value="4">4分屏</a-radio-button>
                <a-radio-button :value="9">9分屏</a-radio-button>
                <a-radio-button :value="16">16分屏</a-radio-button>
              </a-radio-group>
            </div>

            <a-divider type="vertical" class="toolbar-divider" />

            <div class="toolbar-section">
              <a-checkbox v-model:checked="enableAi">启用 AI</a-checkbox>
            </div>

            <a-divider type="vertical" class="toolbar-divider" />

            <div class="toolbar-section patrol-section">
              <Space size="small" wrap>
                <span class="patrol-label">间隔(s)</span>
                <InputNumber
                  v-model:value="patrolIntervalSec"
                  :min="3"
                  :max="300"
                  size="middle"
                  style="width: 72px"
                  :disabled="patrolRunning"
                />
                <span class="patrol-label">模型</span>
                <Select
                  v-model:value="patrolModelId"
                  size="middle"
                  style="width: 140px"
                  :disabled="patrolRunning"
                  :loading="patrolModelsLoading"
                  :options="patrolModelOptions"
                  show-search
                  option-filter-prop="label"
                  placeholder="选择模型"
                />
                <Button
                  v-if="!patrolRunning"
                  type="primary"
                  size="middle"
                  :loading="patrolLoading"
                  :disabled="loadedCount === 0"
                  @click="handleStartPatrol"
                >
                  开始巡检
                </Button>
                <Button
                  v-if="!patrolRunning"
                  type="default"
                  size="middle"
                  :loading="patrolLoading"
                  :disabled="!selectedPatrolDirectoryId"
                  @click="handleStartDirectoryPatrol"
                >
                  目录巡检
                </Button>
                <Button
                  v-else
                  type="default"
                  danger
                  size="middle"
                  :loading="patrolLoading"
                  @click="handleStopPatrol"
                >
                  停止巡检
                </Button>
                <span v-if="patrolSessionId" class="status-text patrol-status">{{ patrolStatusText }}</span>
              </Space>
            </div>

            <a-divider type="vertical" class="toolbar-divider" />

            <div class="toolbar-section">
              <Space size="small">
                <Button
                  type="default"
                  danger
                  size="middle"
                  :disabled="!state.playCells[state.playerIdx]"
                  @click="handleGridDelete"
                >
                  删除选中
                </Button>
                <Button :type="state.isFull ? 'default' : 'primary'" size="middle" @click="handleGridFull">
                  {{ state.isFull ? '退出全屏' : '全屏展示' }}
                </Button>
                <Button type="default" size="middle" @click="handleClearAll">清空全部</Button>
              </Space>
            </div>

            <div class="toolbar-section toolbar-status">
              <span class="status-text">已加载: {{ loadedCount }}/{{ state.splitMode }}</span>
            </div>
          </div>
        </a-layout-header>

        <a-layout-content class="video-content">
          <div :class="['video-grid', `grid-${state.splitMode}`]" :style="gridStyle">
            <div
              v-for="i in state.splitMode"
              :key="i"
              :class="['video-cell', {
                'cell-selected': state.playerIdx === i - 1,
                'cell-empty': !state.playCells[i - 1],
                'cell-loading': state.loadingCells.includes(i - 1)}]"
              @click="state.playerIdx = i - 1"
            >
              <div v-if="!state.playCells[i - 1]" class="empty-cell">
                <Icon icon="ant-design:video-camera-add-outlined" class="empty-icon" />
                <span class="empty-text">通道 {{ i }}</span>
                <span class="empty-hint">点击左侧摄像头即可播放</span>
              </div>
              <div v-else class="player-wrapper">
                <Jessibuca
                  :key="`player-${i - 1}-${state.playCells[i - 1]!.deviceId}`"
                  :ref="(el) => setPlayerRef(el, i - 1)"
                  :play-url="state.playCells[i - 1]!.url"
                  :hasAudio="false"
                  @stream-error="handleCellStreamError(i - 1)"
                />
                <span class="cell-name" :title="state.playCells[i - 1]!.name">
                  {{ state.playCells[i - 1]!.name }}
                </span>
                <Button
                  type="text"
                  size="small"
                  danger
                  class="cell-close-btn"
                  @click.stop="handleCellDelete(i - 1)"
                >
                  <Icon icon="ant-design:close-outlined" />
                </Button>
              </div>
            </div>
          </div>
        </a-layout-content>
      </a-layout>
    </a-layout>

  </div>
</template>

<script lang="ts" setup>
import { computed, type CSSProperties, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import {
  Layout as ALayout,
  LayoutSider as ALayoutSider,
  LayoutHeader as ALayoutHeader,
  LayoutContent as ALayoutContent,
  Button as AButton,
  Space,
  Divider as ADivider,
  RadioGroup as ARadioGroup,
  RadioButton as ARadioButton,
  Checkbox as ACheckbox,
  Select,
  InputNumber,
} from 'ant-design-vue';
import { BasicTree, type TreeItem } from '@/components/Tree';
import { BasicArrow } from '@/components/Basic';
import { Icon } from '@/components/Icon';
import { CollapseContainer } from '@/components/Container';
import {
  syncGb28181Devices,
  type MonitorTreeDeviceNode} from '@/api/device/camera';
import { formatCameraDeviceLabel, isGb28181Device } from '@/views/camera/utils/deviceLabel';
import {
  AI_PLAY_FALLBACK_MS,
  pickDirectPlayUrls,
  resolveGbChannelPlayUrls} from '@/views/camera/utils/devicePlay';
import {
  collectMonitorTreeExpandedKeys,
  findMonitorDeviceById,
  findMonitorGbDeviceByChannel,
  findMonitorTreeNodeByKey,
  parseMonitorDirectoryId,
} from '@/views/camera/utils/monitorDeviceTree';
import {
  buildWvpChannelTreeNodes,
  parseGbChannelKey,
  type GbChannelRef} from '@/views/camera/utils/gb28181Tree';
import { getDeviceChannels } from '@/api/device/gb28181';
import { collectWvpGbChannelsForSync } from '@/views/camera/utils/wvpGbSync';
import {
  enrichWvpChannelTreeNodes,
  resolveMonitorGbChannelDisplayName} from '@/views/camera/utils/monitorGbDisplay';
import { getCachedMonitorDirectoryTreeBundle } from '@/views/camera/utils/monitorDirectoryTreeCache';
import {
  invalidateMonitorDirectoryTreeCache,
  loadMonitorDirectoryTreeWithCache,
  type MonitorDirectoryTreeBundle} from '@/views/camera/utils/monitorDirectoryTreeLoad';
import type { TreeProps } from 'ant-design-vue';
import { useMessage } from '@/hooks/web/useMessage';
import Jessibuca from '@/components/Player/module/jessibuca.vue';
import { Button } from '@/components/Button';
import {
  createPatrolSession,
  createPatrolProgressEventSource,
  getPatrolDirectoryDevices,
  getPatrolSessionStats,
  startPatrolSession,
  stopPatrolSession,
  type PatrolSession,
} from '@/api/device/patrol';
import { getModelPage } from '@/api/device/model';


interface PlayCell {
  deviceId: string;
  name: string;
  url: string;
  /** 播放中断时可回退的原始流地址（仅在播 AI 流且存在原始流时设置） */
  fallbackUrl?: string | null;
}

const { createMessage } = useMessage();

/** 勾选后点播 AI 流（检测框由算法任务烧录在此路流上） */
const enableAi = ref(true);

const patrolIntervalSec = ref(10);
const patrolModelId = ref<number | undefined>(undefined);
const patrolModelOptions = ref<{ label: string; value: number }[]>([]);
const patrolModelsLoading = ref(false);
const patrolSessionId = ref<number | null>(null);
const patrolRunning = ref(false);
const patrolLoading = ref(false);
const patrolStatusText = ref('');
const selectedPatrolDirectoryId = ref<number | null>(null);
const selectedPatrolDirectoryName = ref('');
let patrolEventSource: EventSource | null = null;
let patrolStatsTimer: number | undefined;

async function loadPatrolModelOptions() {
  patrolModelsLoading.value = true;
  try {
    const res = await getModelPage({ pageNo: 1, pageSize: 100 });
    const list = res?.list || res?.data?.list || res?.items || [];
    patrolModelOptions.value = list.map((m: { id: number; name?: string }) => ({
      label: m.name ? `${m.name} (#${m.id})` : `模型 #${m.id}`,
      value: m.id,
    }));
    if (!patrolModelId.value && patrolModelOptions.value.length) {
      patrolModelId.value = patrolModelOptions.value[0].value;
    }
  } catch {
    patrolModelOptions.value = [];
  } finally {
    patrolModelsLoading.value = false;
  }
}

function applyPatrolStats(data?: PatrolSession | null) {
  if (!data) return;
  patrolRunning.value = data.status === 'running';
  const done = data.completed_devices ?? 0;
  const total = data.total_devices ?? 0;
  const detections = data.total_detections ?? 0;
  patrolStatusText.value = `巡检 ${done}/${total} 路 · 检测 ${detections} 次`;
}

async function refreshPatrolStats() {
  if (!patrolSessionId.value) return;
  try {
    const res = await getPatrolSessionStats(patrolSessionId.value);
    const data = (res?.data ?? res) as PatrolSession;
    applyPatrolStats(data);
  } catch {
    // 忽略轮询失败
  }
}

function stopPatrolProgressStream() {
  if (patrolEventSource) {
    patrolEventSource.close();
    patrolEventSource = null;
  }
  stopPatrolStatsPolling();
}

function startPatrolProgressStream() {
  stopPatrolProgressStream();
  if (!patrolSessionId.value) return;
  void refreshPatrolStats();
  const es = createPatrolProgressEventSource(patrolSessionId.value);
  patrolEventSource = es;
  const onProgress = (ev: MessageEvent) => {
    try {
      applyPatrolStats(JSON.parse(ev.data) as PatrolSession);
    } catch {
      // ignore
    }
  };
  es.addEventListener('progress', onProgress);
  es.addEventListener('status', onProgress);
  es.onerror = () => {
    if (patrolEventSource === es) {
      es.close();
      patrolEventSource = null;
    }
    if (!patrolStatsTimer && patrolSessionId.value) {
      startPatrolStatsPolling();
    }
  };
}

function startPatrolStatsPolling() {
  stopPatrolStatsPolling();
  void refreshPatrolStats();
  patrolStatsTimer = window.setInterval(() => void refreshPatrolStats(), 5000);
}

function stopPatrolStatsPolling() {
  if (patrolStatsTimer != null) {
    window.clearInterval(patrolStatsTimer);
    patrolStatsTimer = undefined;
  }
}

async function startPatrolWithDeviceIds(deviceIds: string[], sessionName: string) {
  if (!deviceIds.length) {
    createMessage.warning('没有可巡检的设备');
    return;
  }
  if (!patrolModelId.value) {
    createMessage.warning('请选择模型');
    return;
  }
  patrolLoading.value = true;
  try {
    const createRes = await createPatrolSession({
      session_name: sessionName,
      device_ids: deviceIds,
      model_ids: [patrolModelId.value],
      interval_sec: patrolIntervalSec.value,
      pool_size: Math.min(4, deviceIds.length),
    });
    const session = (createRes?.data ?? createRes) as PatrolSession;
    patrolSessionId.value = session.id;
    await startPatrolSession(session.id);
    patrolRunning.value = true;
    startPatrolProgressStream();
    createMessage.success(`巡检已启动（${deviceIds.length} 路）`);
  } catch (e: any) {
    createMessage.error(e?.message || '启动巡检失败');
  } finally {
    patrolLoading.value = false;
  }
}

async function handleStartPatrol() {
  const deviceIds = state.playCells.filter((c) => c?.deviceId).map((c) => c!.deviceId);
  if (!deviceIds.length) {
    createMessage.warning('请先在分屏中添加摄像头');
    return;
  }
  await startPatrolWithDeviceIds(deviceIds, `分屏巡检-${new Date().toLocaleTimeString()}`);
}

async function handleStartDirectoryPatrol() {
  if (!selectedPatrolDirectoryId.value) {
    createMessage.warning('请先在左侧目录树中选择目录');
    return;
  }
  patrolLoading.value = true;
  try {
    const res = await getPatrolDirectoryDevices(selectedPatrolDirectoryId.value);
    const payload = res?.data ?? res;
    const deviceIds = payload?.device_ids ?? [];
    const dirName = payload?.directory_name || selectedPatrolDirectoryName.value || '目录';
    await startPatrolWithDeviceIds(deviceIds, `${dirName}巡检-${new Date().toLocaleTimeString()}`);
  } catch (e: any) {
    createMessage.error(e?.message || '获取目录设备失败');
    patrolLoading.value = false;
  }
}

async function handleStopPatrol() {
  if (!patrolSessionId.value) return;
  patrolLoading.value = true;
  try {
    await stopPatrolSession(patrolSessionId.value);
    patrolRunning.value = false;
    stopPatrolProgressStream();
    patrolStatusText.value = '已停止';
    createMessage.success('巡检已停止');
  } catch (e: any) {
    createMessage.error(e?.message || '停止巡检失败');
  } finally {
    patrolLoading.value = false;
  }
}

const selectedKeys = ref<string[]>([]);
const expandedKeys = ref<string[]>([]);
const treeData = ref<TreeItem[]>([]);
const treeLoading = ref(false);
/** 有缓存时后台静默刷新 */
const treeRefreshing = ref(false);
const playerRefs = ref<any[]>([]);

const state = reactive({
  playCells: [] as (PlayCell | null)[],
  splitMode: 4,
  playerIdx: 0,
  isFull: false,
  loadingCells: [] as number[]});

const loadedCount = computed(() => state.playCells.filter((c) => c).length);

const gridStyle = computed((): CSSProperties => {
  const base: CSSProperties = {
    display: 'grid',
    gridTemplateColumns: `repeat(${Math.sqrt(state.splitMode)}, 1fr)`,
    gridTemplateRows: `repeat(${Math.sqrt(state.splitMode)}, 1fr)`,
    gap: '2px',
    width: '100%',
    height: '100%',
    padding: '2px'};
  if (state.isFull) {
    return { ...base, position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 9999 };
  }
  return base;
});

const setPlayerRef = (el: any, index: number) => {
  if (el) playerRefs.value[index] = el;
};

async function resolveDirectPlayUrl(device: MonitorTreeDeviceNode) {
  if (isGb28181Device(device.source, device.device_kind)) {
    return { url: null as string | null, fallbackUrl: null as string | null | undefined };
  }
  return pickDirectPlayUrls(device, enableAi.value);
}

const aiFallbackTimers = new Map<number, number>();

function clearAiFallbackTimer(cellIdx: number) {
  const timerId = aiFallbackTimers.get(cellIdx);
  if (timerId != null) {
    window.clearTimeout(timerId);
    aiFallbackTimers.delete(cellIdx);
  }
}


/** 优先当前通道，否则第一个空通道，否则覆盖当前通道 */
function resolveTargetCellIndex(): number {
  if (!state.playCells[state.playerIdx]) {
    return state.playerIdx;
  }
  const emptyIdx = state.playCells.findIndex((c) => !c);
  if (emptyIdx >= 0) return emptyIdx;
  return state.playerIdx;
}

async function startPlayAtCell(
  cellIdx: number,
  payload: {
    deviceId: string;
    name: string;
    url: string;
    fallbackUrl?: string | null;
    preferAi?: boolean;
  },
) {
  clearAiFallbackTimer(cellIdx);
  const existing = state.playCells[cellIdx];
  if (existing && playerRefs.value[cellIdx]?.destroy) {
    playerRefs.value[cellIdx].destroy();
  }

  const fallbackUrl = payload.fallbackUrl?.trim();
  const hasFallback = !!(payload.preferAi && fallbackUrl && fallbackUrl !== payload.url);

  state.playerIdx = cellIdx;
  state.playCells[cellIdx] = {
    deviceId: payload.deviceId,
    name: payload.name,
    url: payload.url,
    fallbackUrl: hasFallback ? fallbackUrl : null};

  await nextTick();
  const player = playerRefs.value[cellIdx];
  if (player?.play) {
    player.play();
  }

  if (!hasFallback) return;

  const primaryUrl = payload.url;
  const timerId = window.setTimeout(async () => {
    aiFallbackTimers.delete(cellIdx);
    const cell = state.playCells[cellIdx];
    if (!cell || cell.url !== primaryUrl) return;
    if (playerRefs.value[cellIdx]?.playing) return;

    createMessage.warning(
      'AI 流暂不可用（请确认算法任务已启动且 ZLM 已收到推流），已切换为原始画面（无检测框）',
    );
    state.playCells[cellIdx] = { ...cell, url: fallbackUrl, fallbackUrl: null };
    await nextTick();
    playerRefs.value[cellIdx]?.play?.();
  }, AI_PLAY_FALLBACK_MS);
  aiFallbackTimers.set(cellIdx, timerId);
}

/** AI 流播放后中断（timeout/error）：回退到原始流，避免无限"疯狂加载中" */
function handleCellStreamError(cellIdx: number) {
  const cell = state.playCells[cellIdx];
  if (!cell) return;
  const fb = cell.fallbackUrl?.trim();
  if (!fb || fb === cell.url) return;
  clearAiFallbackTimer(cellIdx);
  createMessage.warning('AI 流已中断，已切换为原始画面（无检测框）');
  state.playCells[cellIdx] = { ...cell, url: fb, fallbackUrl: null };
  nextTick(() => playerRefs.value[cellIdx]?.play?.());
}

async function reloadPlayCellAtIndex(cellIdx: number) {
  const cell = state.playCells[cellIdx];
  if (!cell) return;

  const playId = cell.deviceId;
  if (playId.startsWith('gb_ch_')) {
    const gb = parseGbChannelKey(playId);
    if (gb) {
      const synced = findMonitorGbDeviceByChannel(treeData.value, gb.sipDeviceId, gb.channelId);
      const { url, fallbackUrl, preferAi } = await resolveGbChannelPlayUrls(
        gb.sipDeviceId,
        gb.channelId,
        { enableAi: enableAi.value, synced },
      );
      if (url) {
        await startPlayAtCell(cellIdx, {
          deviceId: playId,
          name: cell.name,
          url,
          fallbackUrl,
          preferAi});
      }
    }
    return;
  }

  const device = findMonitorDeviceById(treeData.value, playId);
  if (!device) return;

  const { url, fallbackUrl, preferAi } = await resolveDirectPlayUrl(device);
  if (!url) {
    createMessage.warn(enableAi.value ? '该设备暂无 AI 流或原始流地址' : '该设备暂无播放地址');
    return;
  }
  await startPlayAtCell(cellIdx, {
    deviceId: playId,
    name: cell.name,
    url,
    fallbackUrl,
    preferAi});
}

async function reloadAllPlayCellsForAiToggle() {
  const tasks: Promise<void>[] = [];
  state.playCells.forEach((cell, idx) => {
    if (cell) tasks.push(reloadPlayCellAtIndex(idx));
  });
  await Promise.all(tasks);
}

watch(enableAi, () => {
  reloadAllPlayCellsForAiToggle();
});

const onLoadGbDeviceChannels: TreeProps['loadData'] = (treeNode) => {
  return new Promise<void>((resolve) => {
    const key = String(treeNode?.key ?? treeNode?.eventKey ?? '');
    if (!key.startsWith('gb_dev_')) {
      resolve();
      return;
    }
    const sipDeviceId = key.slice('gb_dev_'.length);
    const dataRef = (treeNode.dataRef ?? treeNode) as TreeItem;
    if (dataRef?.children?.length) {
      resolve();
      return;
    }

    getDeviceChannels(sipDeviceId)
      .then((res) => {
        const list = res.data || res.list || [];
        dataRef.children = enrichWvpChannelTreeNodes(
          buildWvpChannelTreeNodes(list, sipDeviceId),
          treeData.value,
        );
        dataRef.isLeaf = !dataRef.children?.length;
        treeData.value = [...treeData.value];
        if (!expandedKeys.value.includes(key)) {
          expandedKeys.value = [...expandedKeys.value, key];
        }
        resolve();
      })
      .catch(() => resolve());
  });
};

function applyMonitorTreeBundle(bundle: MonitorDirectoryTreeBundle) {
  treeData.value = bundle.treeItems;
  expandedKeys.value = collectMonitorTreeExpandedKeys(treeData.value);
}

/** 缓存优先加载；国标通道展开时再按需请求 WVP */
async function loadMonitorTree(options?: { force?: boolean }) {
  const hasCache = !options?.force && !!getCachedMonitorDirectoryTreeBundle()?.treeItems?.length;
  if (!hasCache) treeLoading.value = true;
  await loadMonitorDirectoryTreeWithCache({
    force: options?.force,
    skipSync: true,
    onBundle: (bundle) => {
      applyMonitorTreeBundle(bundle);
    },
    onRefreshingChange: (v) => {
      treeRefreshing.value = v;
      if (hasCache) return;
      if (!v) treeLoading.value = false;
    },
    onError: (e) => {
      if (!treeData.value.length) {
        console.error(e);
        createMessage.error('加载设备目录树失败');
        treeData.value = [];
      }
      treeLoading.value = false;
    }});
  if (!hasCache) treeLoading.value = false;
}

/** 同步国标设备并刷新目录树 */
async function handleRefresh() {
  try {
    treeLoading.value = true;
    invalidateMonitorDirectoryTreeCache();
    try {
      const { channels } = await collectWvpGbChannelsForSync();
      const payload = await syncGb28181Devices(channels);
      const created = payload?.created ?? 0;
      const total = payload?.total_gb_devices ?? 0;
      const wvpCount = payload?.wvp_device_count ?? 0;
      if (wvpCount > 0 && total === 0) {
        createMessage.warning(
          `WVP 有 ${wvpCount} 个国标设备，但未入库；请检查 VIDEO 服务与数据库`,
        );
      } else if (wvpCount === 0) {
        createMessage.warning('未从 WVP 拉取到国标设备，请检查 dev-api/gb28181 网关');
      } else {
        createMessage.success(`同步完成：新增 ${created} 个，共 ${total} 个国标设备`);
      }
    } catch (e) {
      console.error(e);
      createMessage.error('同步国标设备失败，请检查 WVP 服务与网络');
    }
    await loadMonitorTree({ force: true });
  } catch (e) {
    console.error(e);
    createMessage.error('加载设备目录树失败');
    if (!treeData.value.length) treeData.value = [];
  } finally {
    treeLoading.value = false;
  }
}

async function playGbChannel(cellIdx: number, gb: GbChannelRef) {
  const playId = `gb_ch_${gb.sipDeviceId},${gb.channelId}`;
  const duplicate = state.playCells.findIndex((c) => c?.deviceId === playId);
  if (duplicate >= 0 && duplicate !== state.playerIdx) {
    state.playerIdx = duplicate;
    createMessage.info('该通道已在播放，已切换到对应窗口');
    return;
  }

  if (state.loadingCells.includes(cellIdx)) return;
  state.loadingCells.push(cellIdx);

  try {
    const displayName = resolveMonitorGbChannelDisplayName(
      gb.sipDeviceId,
      gb.channelId,
      treeData.value,
      gb.name,
    );
    const node = findMonitorTreeNodeByKey(treeData.value, `gb_ch_${gb.sipDeviceId},${gb.channelId}`);
    const synced =
      findMonitorGbDeviceByChannel(treeData.value, gb.sipDeviceId, gb.channelId) ??
      ((node as any)?.device as MonitorTreeDeviceNode | undefined);
    const { url, fallbackUrl, preferAi } = await resolveGbChannelPlayUrls(
      gb.sipDeviceId,
      gb.channelId,
      { enableAi: enableAi.value, synced },
    );
    if (!url) {
      createMessage.warn(
        enableAi.value
          ? '国标通道 AI 流不可用，请确认算法任务已启动；WVP 点播也失败，请检查通道状态'
          : '国标通道拉流失败，请检查 WVP 服务与通道状态',
      );
      return;
    }

    await startPlayAtCell(cellIdx, {
      deviceId: playId,
      name: displayName,
      url,
      fallbackUrl,
      preferAi});
  } catch (e) {
    console.error(e);
    createMessage.error('播放失败，请检查设备连接');
  } finally {
    const i = state.loadingCells.indexOf(cellIdx);
    if (i > -1) state.loadingCells.splice(i, 1);
  }
}

async function handleTreeSelect(keys: string[] | string) {
  const keyList = Array.isArray(keys) ? keys : keys ? [keys] : [];
  if (!keyList.length) return;
  const key = keyList[0];

  if (String(key).startsWith('gb_dev_')) {
    createMessage.info('请展开国标设备并选择具体通道');
    return;
  }

  if (String(key).startsWith('nvr_')) {
    createMessage.info('请展开 NVR 并选择具体通道');
    return;
  }

  if (String(key).startsWith('gb_dir_') || String(key).startsWith('dir_')) {
    const dirId = parseMonitorDirectoryId(String(key));
    if (dirId) {
      selectedPatrolDirectoryId.value = dirId;
      const node = findMonitorTreeNodeByKey(treeData.value, key);
      selectedPatrolDirectoryName.value = String(node?.title ?? '').replace(/\(\d+\)$/, '').trim();
      createMessage.info('已选中目录，可点击「目录巡检」对该目录下全部摄像头启动巡检');
    }
    return;
  }

  selectedPatrolDirectoryId.value = null;
  selectedPatrolDirectoryName.value = '';

  const cellIdx = resolveTargetCellIndex();

  if (String(key).startsWith('gb_ch_')) {
    let gb = parseGbChannelKey(key);
    const node = findMonitorTreeNodeByKey(treeData.value, key);
    if (node && (node as any).gbChannel) {
      gb = (node as any).gbChannel as GbChannelRef;
    }
    if (!gb) {
      createMessage.warn('无效国标通道');
      return;
    }
    await playGbChannel(cellIdx, gb);
    return;
  }

  if (!String(key).startsWith('device_')) {
    createMessage.info('请选择摄像头或国标通道');
    return;
  }

  const node = findMonitorTreeNodeByKey(treeData.value, key);
  const device = (node as any)?.device as MonitorTreeDeviceNode | undefined;
  if (!device) {
    createMessage.warn('无效设备');
    return;
  }
  if (isGb28181Device(device.source, device.device_kind)) {
    createMessage.info('请展开上级国标设备并选择通道');
    return;
  }

  const duplicate = state.playCells.findIndex((c) => c?.deviceId === device.id);
  if (duplicate >= 0 && duplicate !== state.playerIdx) {
    state.playerIdx = duplicate;
    createMessage.info('该设备已在播放，已切换到对应通道');
    return;
  }

  if (state.loadingCells.includes(cellIdx)) return;
  state.loadingCells.push(cellIdx);

  try {
    const { url, fallbackUrl, preferAi } = await resolveDirectPlayUrl(device);
    if (!url) {
      createMessage.warn(
        enableAi.value
          ? '该设备暂无 AI 流或原始流播放地址，请先在设备列表中配置'
          : '该设备暂无可用播放地址，请先在设备列表中配置流地址',
      );
      return;
    }
    await startPlayAtCell(cellIdx, {
      deviceId: device.id,
      name: formatCameraDeviceLabel(device),
      url,
      fallbackUrl,
      preferAi});
  } catch (e) {
    console.error(e);
    createMessage.error('播放失败，请检查设备连接');
  } finally {
    const i = state.loadingCells.indexOf(cellIdx);
    if (i > -1) state.loadingCells.splice(i, 1);
  }
}

function handleSplitModeChange() {
  const n = state.splitMode;
  if (state.playCells.length > n) {
    for (let i = n; i < state.playCells.length; i++) {
      if (playerRefs.value[i]?.destroy) playerRefs.value[i].destroy();
    }
    state.playCells = state.playCells.slice(0, n);
  } else {
    while (state.playCells.length < n) state.playCells.push(null);
  }
  if (state.playerIdx >= n) state.playerIdx = 0;
}

function handleGridDelete() {
  const idx = state.playerIdx;
  if (!state.playCells[idx]) {
    createMessage.warn('当前通道没有视频');
    return;
  }
  if (playerRefs.value[idx]?.destroy) playerRefs.value[idx].destroy();
  state.playCells[idx] = null;
  createMessage.success('已删除选中通道');
}

function handleCellDelete(index: number) {
  if (!state.playCells[index]) return;
  if (playerRefs.value[index]?.destroy) playerRefs.value[index].destroy();
  state.playCells[index] = null;
}

function handleClearAll() {
  playerRefs.value.forEach((p, i) => {
    if (p?.destroy && state.playCells[i]) p.destroy();
  });
  state.playCells = Array(state.splitMode).fill(null);
  state.playerIdx = 0;
  createMessage.success('已清空所有通道');
}

function handleGridFull() {
  state.isFull = !state.isFull;
  if (state.isFull) document.documentElement.requestFullscreen?.();
  else document.exitFullscreen?.();
}

const handleFullscreenChange = () => {
  state.isFull = !!document.fullscreenElement;
};

onMounted(() => {
  state.playCells = Array(state.splitMode).fill(null);
  loadMonitorTree();
  void loadPatrolModelOptions();
  document.addEventListener('fullscreenchange', handleFullscreenChange);
});

onUnmounted(() => {
  document.removeEventListener('fullscreenchange', handleFullscreenChange);
  aiFallbackTimers.forEach((id) => window.clearTimeout(id));
  aiFallbackTimers.clear();
  stopPatrolProgressStream();
  playerRefs.value.forEach((p) => p?.destroy?.());
});

defineExpose({ refresh: () => loadMonitorTree(), forceRefresh: handleRefresh });
</script>

<style lang="less" scoped>
.split-screen-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: #fff;
  overflow: hidden;

  &.fullscreen-mode {
    position: fixed;
    inset: 0;
    z-index: 9999;
    height: 100vh;
    max-height: 100vh;
  }
}

.monitor-layout {
  flex: 1;
  min-height: 0;
  height: 100%;
  background: #fff;
  overflow: hidden;

  :deep(.ant-layout) {
    height: 100%;
  }
}

.monitor-content-layout {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

.device-tree-sider {
  height: 100%;
  overflow: hidden;
  border-right: 1px solid #e5e7eb;

  :deep(.ant-layout-sider-children) {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .tree-container {
    height: 100%;
    display: flex;
    flex-direction: column;
    min-height: 0;

    :deep(.xingyuv-collapse-container__header) {
      height: auto;
      min-height: 48px;
      padding: 0 12px !important;
      background: linear-gradient(180deg, #fafbfc 0%, #fff 100%);
      border-bottom: 1px solid #eef0f3;
      border-radius: 0;
    }

    :deep(.xingyuv-basic-title) {
      flex: 1;
      min-width: 0;
      padding-left: 0 !important;
      font-size: inherit;
      font-weight: inherit;
      line-height: inherit;
      cursor: default;
      user-select: none;
    }

    :deep(.xingyuv-collapse-container__action) {
      flex: none;
    }

    /* 仅让折叠内容区占满剩余高度，不改变标题栏样式 */
    :deep(> .p-2) {
      flex: 1;
      min-height: 0;
      overflow: hidden;
      display: flex;
      flex-direction: column;

      > * {
        flex: 1;
        min-height: 0;
        display: flex;
        flex-direction: column;
        overflow: hidden;
      }
    }

    :deep(.xingyuv-collapse-container__body) {
      flex: 1;
      min-height: 0;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
  }
}

.tree-header-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;

  &__icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 6px;
    background: #eff6ff;
    color: #3b82f6;
    flex-shrink: 0;
  }

  &__text {
    font-size: 14px;
    font-weight: 600;
    color: #111827;
    line-height: 1;
    letter-spacing: 0.01em;
  }
}

.tree-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.tree-scroll {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 12px;
  display: flex;
  flex-direction: column;

  :deep(.device-tree) {
    flex: 1;
    min-height: 0;
    height: 100%;
    overflow: hidden;
    display: flex;
    flex-direction: column;

    .ant-spin-nested-loading,
    .ant-spin-container {
      flex: 1;
      min-height: 0;
      height: 100%;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    .scroll-container {
      flex: 1;
      min-height: 0;
    }

    .ant-tree-switcher {
      width: 16px;
      margin-inline-end: 2px;
    }

    /* 叶子节点前的展开占位更窄，避免整体偏右 */
    .ant-tree-switcher-noop {
      width: 8px;
    }

    .ant-tree-node-content-wrapper {
      padding-inline: 2px 6px;
      min-height: 26px;
      line-height: 26px;
    }

    .ant-tree-title,
    [class*='-tree__title'] {
      padding-left: 0 !important;
      padding-right: 8px;
    }
  }
}

.toolbar-header {
  height: auto;
  min-height: 56px;
  padding: 12px 16px;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
  line-height: normal;
}

.toolbar-content {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
  width: 100%;
}

.toolbar-status {
  margin-left: auto;

  .status-text {
    color: #6b7280;
    font-size: 13px;
  }

  .patrol-label {
    font-size: 12px;
    color: #64748b;
  }

  .patrol-status {
    min-width: 140px;
  }
}

.video-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: #f3f4f6;
}

.video-grid {
  width: 100%;
  height: 100%;
  min-height: 0;
}

.video-cell {
  position: relative;
  border: 2px solid #e5e7eb;
  background: #111;
  cursor: pointer;
  overflow: hidden;

  &.cell-selected {
    border-color: #3b82f6;
    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.35);
  }

  &.cell-empty {
    background: #f9fafb;
    border-style: dashed;
  }

  &.cell-loading::after {
    content: '';
    position: absolute;
    inset: 0;
    background: rgba(255, 255, 255, 0.65);
    z-index: 5;
  }
}

.empty-cell {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #6b7280;
  gap: 8px;

  .empty-icon {
    font-size: 36px;
    color: #9ca3af;
  }

  .empty-hint {
    font-size: 12px;
  }
}

.player-wrapper {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 120px;

  &:hover .cell-close-btn {
    opacity: 0.85;
  }
}

.cell-name {
  position: absolute;
  left: 6px;
  /* 紧贴播放栏上方（工具栏约 28px） */
  bottom: 25px;
  z-index: 11;
  max-width: calc(100% - 36px);
  padding: 1px 5px;
  font-size: 11px;
  line-height: 1.25;
  color: rgba(255, 255, 255, 0.78);
  background: rgba(0, 0, 0, 0.28);
  border-radius: 2px;
  pointer-events: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cell-close-btn {
  position: absolute;
  top: 4px;
  right: 4px;
  z-index: 3;
  min-width: 22px;
  height: 22px;
  padding: 0;
  opacity: 0.45;
  color: #fff !important;
  background: rgba(0, 0, 0, 0.25) !important;
  border-radius: 2px;
  transition: opacity 0.2s;

  &:hover {
    opacity: 1 !important;
    background: rgba(239, 68, 68, 0.75) !important;
  }
}
</style>
