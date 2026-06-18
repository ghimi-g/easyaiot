<template>
  <div class="camera-container">
    <div class="camera-tab">
      <Tabs
        :activeKey="state.activeKey"
        :animated="{ inkBar: true, tabPane: true }"
        :destroyInactiveTabPane="true"
        :tabBarGutter="60"
        @tabClick="handleTabClick"
      >
        <TabPane key="1" tab="地图分布">
          <CameraMapDistribution ref="cameraMapDistributionRef" />
        </TabPane>
        <TabPane key="2" tab="分屏监控">
          <SplitScreenMonitor
            ref="splitScreenMonitorRef"
            :initial-mode="splitScreenInitialMode"
            @play="handleCardPlay"
          />
        </TabPane>
        <TabPane key="3" tab="设备列表">
          <DeviceCreate
            v-if="deviceCreateVisible"
            :initial-kind="deviceCreateInitial.kind"
            :initial-method="deviceCreateInitial.method"
            :initial-brand="deviceCreateInitial.brand"
            @back="closeDeviceCreate"
            @success="handleDeviceCreateSuccess"
          />
          <Gb28181DeviceDetail
            v-else-if="gbDetailVisible"
            :sip-device-id="gbDetailSipId"
            :title="gbDetailTitle"
            channel-hint="点击下方通道进行点播播放"
            @back="closeGbDetail"
            @set-location="openDeviceLocationDrawer"
          />
          <NvrDeviceDetail
            v-else-if="nvrDetailVisible"
            ref="nvrDeviceDetailRef"
            :nvr-id="nvrDetailId"
            :title="nvrDetailTitle"
            @back="closeNvrDetail"
            @view="handleNvrChannelView"
            @edit="handleNvrChannelEdit"
            @play="handleCardPlay"
            @playAI="handleCardPlayAI"
            @delete="handleNvrChannelDelete"
            @set-location="openDeviceLocationDrawer"
          />
          <template v-else>
          <!-- 表格模式 -->
          <div v-if="viewMode === 'table'" class="device-list-table-wrap">
            <BasicTable @register="registerTable">
              <template #toolbar>
                <div class="device-list-toolbar">
                  <Button type="primary" preIcon="ant-design:video-camera-add-outlined" @click="openDeviceCreate()">
                    添加设备
                  </Button>
                  <Button preIcon="ant-design:import-outlined" @click="openBatchLocationModal(true)">
                    导入坐标
                  </Button>
                  <Button type="default" @click="handleToggleViewMode">
                    <template #icon><SwapOutlined /></template>
                    切换视图
                  </Button>
                </div>
              </template>
              <template #bodyCell="{ column, record }">
                <template v-if="column.dataIndex === 'name'">
                  <span
                    class="device-list-table__copyable"
                    :title="formatCameraDeviceLabel(record)"
                    @click="handleCopy(formatCameraDeviceLabel(record))"
                  >
                    <Icon icon="tdesign:copy-filled" color="#4287FCFF" />
                    {{ formatCameraDeviceLabel(record) }}
                  </span>
                </template>
                <template v-else-if="column.dataIndex === 'stream_status'">
                  <a-tag :color="getStreamStatusColor(getRecordStreamStatus(record.id))">
                    {{ getStreamStatusText(getRecordStreamStatus(record.id)) }}
                  </a-tag>
                </template>
                <template v-else-if="column.dataIndex === 'has_location'">
                  <a
                    v-if="canSetDeviceLocation(record)"
                    class="device-list-table__location-link"
                    :title="hasDeviceLocation(record) ? '点击修改坐标' : '点击设置坐标'"
                    @click.prevent="openDeviceLocationDrawer(record)"
                  >
                    {{
                      hasDeviceLocation(record)
                        ? formatLocationSummary(record)
                        : '未设置'
                    }}
                  </a>
                  <span v-else class="device-list-table__location-muted">—</span>
                </template>
                <template v-else-if="column.dataIndex === 'action'">
                  <TableAction :actions="getTableActions(record)" />
                </template>
              </template>
            </BasicTable>
          </div>

          <div v-else class="card-mode-wrapper">
                <DeviceMixedCardList
                  ref="deviceMixedCardListRef"
                  :params="{}"
                  @view="handleCardView"
                  @edit="handleCardEdit"
                  @delete="handleCardDelete"
                  @play="handleCardPlay"
                  @playAI="handleCardPlayAI"
                  @open-gb-device="handleOpenGbDevice"
                  @refresh-gb-device="handleRefreshGbDevice"
                  @view-gb-device="handleViewGbDevice"
                  @edit-gb-device="handleEditGbDevice"
                  @delete-gb-device="handleDeleteGbDevice"
                  @open-nvr-device="handleOpenNvrDevice"
                  @view-nvr-device="handleViewNvrDevice"
                  @edit-nvr-device="handleEditNvrDevice"
                  @delete-nvr-device="handleDeleteNvrDevice"
                  @set-location="handleCardSetLocation"
                >
                  <template #header>
                    <div class="device-list-toolbar device-list-toolbar--card">
                      <Button type="primary" preIcon="ant-design:video-camera-add-outlined" @click="openDeviceCreate()">
                        添加设备
                      </Button>
                      <Button preIcon="ant-design:import-outlined" @click="openBatchLocationModal(true)">
                        导入坐标
                      </Button>
                      <Button type="default" @click="handleToggleViewMode">
                        <template #icon><SwapOutlined /></template>
                        切换视图
                      </Button>
                    </div>
                  </template>
            </DeviceMixedCardList>
          </div>
          </template>

          <DialogPlayer title="视频播放" @register="registerPlayerAddModel"
                        @success="handlePlayerSuccess"/>
          <BatchLocationImportModal @register="registerBatchLocationModal" @success="handleLocationImportSuccess" />
          <VideoModal @register="registerAddModel" @success="handleSuccess"/>
          <Gb28181DeviceModal @register="registerGbDeviceModal" @success="handleSuccess"/>
          <NvrDeviceModal @register="registerNvrDeviceModal" @success="handleSuccess"/>
        </TabPane>
        <TabPane key="4" tab="存储空间">
          <StorageSpace ref="storageSpaceRef"/>
        </TabPane>
        <TabPane key="6" tab="推流转发">
          <StreamForward ref="streamForwardRef"/>
        </TabPane>
        <TabPane key="7" tab="算法任务">
          <AlgorithmTask ref="algorithmTaskRef"/>
        </TabPane>
        <TabPane key="9" tab="节点管理">
          <Gb28181Node ref="gb28181NodeRef"/>
        </TabPane>
        <TabPane key="10" tab="人脸库">
          <FaceLibrary ref="faceLibraryRef"/>
        </TabPane>
        <TabPane key="11" tab="车牌库">
          <PlateLibrary ref="plateLibraryRef"/>
        </TabPane>
      </Tabs>
    </div>
    <DeviceLocationDrawer @register="registerLocationDrawer" @success="handleLocationDrawerSuccess" />
  </div>
</template>

<script lang="ts" setup>
import {nextTick, onMounted, onUnmounted, reactive, ref, watch} from 'vue';
import {useRoute} from 'vue-router';
import {TabPane, Tabs} from 'ant-design-vue';
import { SwapOutlined } from '@ant-design/icons-vue';
import {BasicTable, TableAction, useTable} from '@/components/Table';
import {useMessage} from '@/hooks/web/useMessage';
import {getBasicColumns, getFormConfig} from "./Data";
import {useModal} from "@/components/Modal";
import VideoModal from "./components/VideoModal/index.vue";
import DeviceCreate from './components/DeviceCreate/index.vue';
import {
  deleteDevice,
  deleteNvr,
  DeviceInfo,
  getDeviceList,
  getStreamStatus,
  StreamStatusResponse,
} from '@/api/device/camera';
import DialogPlayer from "@/components/VideoPlayer/DialogPlayer.vue";
import { Button } from '@/components/Button';
import SplitScreenMonitor from "./components/SplitScreenMonitor/index.vue";
import CameraMapDistribution from './components/CameraMapDistribution/index.vue';
import StorageSpace from "./components/StorageSpace/index.vue";
import AlgorithmTask from "./components/AlgorithmTask/index.vue";
import FaceLibrary from "./components/FaceLibrary/index.vue";
import PlateLibrary from "./components/PlateLibrary/index.vue";
import DeviceMixedCardList from './components/DeviceMixedCardList/index.vue';
import Gb28181DeviceDetail from './components/Gb28181DeviceDetail/index.vue';
import NvrDeviceDetail from './components/NvrDeviceDetail/index.vue';
import NvrDeviceModal from './components/NvrDeviceModal/index.vue';
import Gb28181DeviceModal from './components/Gb28181DeviceModal/index.vue';
import type { Gb28181CardItem } from './components/Gb28181DeviceCard/index.vue';
import type { NvrCardItem } from './utils/nvrDeviceGroup';
import {
  fetchMergedDeviceList,
  isGb28181SipListRow,
  type GbSipDeviceSummary,
} from './utils/gb28181DeviceGroup';
import { deleteGb28181SipDevice } from './utils/gb28181DeviceDelete';
import { isNvrListRow } from './utils/deviceLabel';
import StreamForward from "./components/StreamForward/index.vue";
import { formatCameraDeviceLabel } from './utils/deviceLabel';
import {
  hasDirectPlayStream,
  openDeviceInDialogPlayer,
  supportsRtspForward,
} from './utils/devicePlay';
import Gb28181Node from "@/views/gb28181/components/Node/index.vue";
import BatchLocationImportModal from './components/BatchLocationImportModal/index.vue';
import DeviceLocationDrawer from './components/DeviceLocationDrawer/index.vue';
import {
  canSetDeviceLocation,
  formatLocationSummary,
  hasDeviceLocation,
} from './utils/deviceLocation';
import {
  parseDeviceCreateQuery,
  type CameraBrand,
  type CreateMethod,
  type DeviceKind,
} from './utils/deviceCreateOptions';

defineOptions({name: 'CAMERA'})

const route = useRoute();

const {createMessage} = useMessage();
const [registerAddModel, {openModal}] = useModal();
const [registerGbDeviceModal, {openModal: openGbDeviceModal}] = useModal();
const [registerNvrDeviceModal, {openModal: openNvrDeviceModal}] = useModal();

const [registerPlayerAddModel, {openModal: openPlayerAddModel}] = useModal();
const [registerBatchLocationModal, {openModal: openBatchLocationModal}] = useModal();
const [registerLocationDrawer, { openModal: openLocationModal }] = useModal();

// Tab状态
const state = reactive({
  activeKey: '1',
});

// 视图模式（默认卡片模式）
const viewMode = ref<'table' | 'card'>('card');

function handleToggleViewMode() {
  viewMode.value = viewMode.value === 'card' ? 'table' : 'card';
  if (viewMode.value === 'table') {
    reload();
  } else {
    deviceMixedCardListRef.value?.fetch?.();
  }
}

// 分屏监控组件引用
const splitScreenMonitorRef = ref();
const cameraMapDistributionRef = ref();
const splitScreenInitialMode = ref<'config' | 'monitor'>('monitor');

// 混合设备卡片列表引用
const deviceMixedCardListRef = ref();
const nvrDeviceDetailRef = ref();

// 国标设备详情内页
const gbDetailVisible = ref(false);
const gbDetailSipId = ref('');
const gbDetailTitle = ref('');

const nvrDetailVisible = ref(false);
const nvrDetailId = ref(0);
const nvrDetailTitle = ref('');

const deviceCreateVisible = ref(false);
const deviceCreateInitial = reactive<{
  kind: DeviceKind;
  method: CreateMethod;
  brand: CameraBrand;
}>({
  kind: 'camera',
  method: 'onvif',
  brand: 'custom',
});

// 存储空间组件引用
const storageSpaceRef = ref();

// 算法任务组件引用
const algorithmTaskRef = ref();
const faceLibraryRef = ref();
const plateLibraryRef = ref();

// 推流转发组件引用
const streamForwardRef = ref();

// 节点管理组件引用
const gb28181NodeRef = ref();

/** 一级 Tab key（与模板 TabPane 从左到右顺序一致） */
const CAMERA_TAB_KEYS = {
  CAMERA_MAP: '1',
  SPLIT_MONITOR: '2',
  DEVICE_LIST: '3',
  STORAGE: '4',
  STREAM_FORWARD: '6',
  ALGORITHM: '7',
  GB_NODE: '9',
  FACE_LIBRARY: '10',
  PLATE_LIBRARY: '11',
} as const;

const CAMERA_TAB_ID_SET = new Set<string>(Object.values(CAMERA_TAB_KEYS));

/** 旧版 tab 编号兼容（已移除的 Tab 或历史编号） */
const LEGACY_CAMERA_TAB_MAP: Record<string, string> = {
  '5': CAMERA_TAB_KEYS.STORAGE,
  '8': CAMERA_TAB_KEYS.CAMERA_MAP,
  '12': CAMERA_TAB_KEYS.DEVICE_LIST,
};

/** 路由 ?tab=：优先匹配当前编号；旧编号通过 LEGACY_CAMERA_TAB_MAP 映射 */
function normalizeCameraRouteTab(tab: string): string {
  if (CAMERA_TAB_ID_SET.has(tab)) return tab;
  if (LEGACY_CAMERA_TAB_MAP[tab]) return LEGACY_CAMERA_TAB_MAP[tab];
  return CAMERA_TAB_KEYS.CAMERA_MAP;
}

// Tab切换
const handleTabClick = (activeKey: string) => {
  state.activeKey = activeKey;
  // 切换到设备列表标签页时，刷新直连设备数据
  if (activeKey === CAMERA_TAB_KEYS.DEVICE_LIST) {
    handleSuccess();
  }
  // 切换到存储空间标签页时，刷新数据（TabPane destroyInactiveTabPane 下需 nextTick 等待挂载）
  if (activeKey === CAMERA_TAB_KEYS.STORAGE) {
    void nextTick(() => {
      storageSpaceRef.value?.refresh?.();
    });
  }
  // 切换到算法任务标签页时，刷新数据
  if (activeKey === CAMERA_TAB_KEYS.ALGORITHM && algorithmTaskRef.value) {
    algorithmTaskRef.value.refresh();
  }
  if (activeKey === CAMERA_TAB_KEYS.FACE_LIBRARY && faceLibraryRef.value) {
    faceLibraryRef.value.refresh?.();
  }
  if (activeKey === CAMERA_TAB_KEYS.PLATE_LIBRARY && plateLibraryRef.value) {
    plateLibraryRef.value.refresh?.();
  }
  // 切换到推流转发标签页时，刷新数据
  if (activeKey === CAMERA_TAB_KEYS.STREAM_FORWARD && streamForwardRef.value) {
    streamForwardRef.value.refresh();
  }
  if (activeKey === CAMERA_TAB_KEYS.SPLIT_MONITOR && splitScreenMonitorRef.value) {
    splitScreenMonitorRef.value.refresh();
  }
  if (activeKey === CAMERA_TAB_KEYS.CAMERA_MAP && cameraMapDistributionRef.value) {
    cameraMapDistributionRef.value.refresh();
  }
};

// 切换视图时刷新对应列表
watch(viewMode, (mode) => {
  if (mode === 'table') {
    reload();
  } else if (deviceMixedCardListRef.value) {
    deviceMixedCardListRef.value.fetch();
  }
});

function openGbDetail(summary: GbSipDeviceSummary) {
  gbDetailSipId.value = summary.sipDeviceId;
  gbDetailTitle.value = summary.name || summary.sipDeviceId;
  gbDetailVisible.value = true;
}

function closeGbDetail() {
  gbDetailVisible.value = false;
  gbDetailSipId.value = '';
  gbDetailTitle.value = '';
}

function openNvrDetail(item: NvrCardItem) {
  nvrDetailId.value = item.nvrId;
  nvrDetailTitle.value = item.name;
  nvrDetailVisible.value = true;
}

function closeNvrDetail() {
  nvrDetailVisible.value = false;
  nvrDetailId.value = 0;
  nvrDetailTitle.value = '';
}

function handleOpenNvrDevice(item: NvrCardItem) {
  openNvrDetail(item);
}

function openNvrInfoModal(type: 'view' | 'edit', item: NvrCardItem | { nvr_id_num?: number; nvrId?: number }) {
  const nvrId = 'nvrId' in item && item.nvrId
    ? item.nvrId
    : (item as { nvr_id_num?: number }).nvr_id_num ?? 0;
  if (!nvrId) {
    createMessage.warning('缺少 NVR ID');
    return;
  }
  openNvrDeviceModal(true, { isView: type === 'view', nvrId });
}

function handleViewNvrDevice(item: NvrCardItem) {
  openNvrInfoModal('view', item);
}

function handleEditNvrDevice(item: NvrCardItem) {
  openNvrInfoModal('edit', item);
}

async function handleDeleteNvrDevice(item: NvrCardItem) {
  try {
    await deleteNvr(item.nvrId);
    createMessage.success('删除成功');
    if (nvrDetailVisible.value && nvrDetailId.value === item.nvrId) {
      closeNvrDetail();
    }
    handleSuccess();
  } catch (error) {
    console.error('删除 NVR 失败', error);
    createMessage.error('删除失败');
  }
}

function handleNvrChannelView(device: DeviceInfo) {
  openAddModal('view', device);
}

function handleNvrChannelEdit(device: DeviceInfo) {
  openAddModal('edit', device);
}

function handleOpenGbDevice(summary: GbSipDeviceSummary) {
  openGbDetail(summary);
}

async function handleRefreshGbDevice(summary: GbSipDeviceSummary) {
  try {
    const { refreshChannelList } = await import('@/api/device/gb28181');
    await refreshChannelList(summary.sipDeviceId);
    createMessage.success('已开始同步通道');
    if (deviceMixedCardListRef.value) {
      deviceMixedCardListRef.value.fetch();
    }
  } catch (e) {
    console.error(e);
    createMessage.error('同步通道失败');
  }
}

function gbSipIdFromRecord(record: { sip_device_id?: string; id?: string; deviceIdentification?: string }) {
  return (
    record.sip_device_id ||
    String(record.deviceIdentification || '').trim() ||
    String(record.id || '').replace(/^gb_sip_/, '')
  );
}

function openGbDeviceInfoModal(type: 'view' | 'edit', payload: { sipDeviceId: string }) {
  openGbDeviceModal(true, {
    isView: type === 'view',
    sipDeviceId: payload.sipDeviceId,
  });
}

function handleViewGbDevice(item: Gb28181CardItem) {
  openGbDeviceInfoModal('view', { sipDeviceId: item.deviceIdentification });
}

function handleEditGbDevice(item: Gb28181CardItem) {
  openGbDeviceInfoModal('edit', { sipDeviceId: item.deviceIdentification });
}

async function handleDeleteGbDevice(item: Gb28181CardItem | { sip_device_id?: string; deviceIdentification?: string }) {
  const sipId =
    'deviceIdentification' in item && item.deviceIdentification
      ? item.deviceIdentification
      : gbSipIdFromRecord(item as DeviceInfo & { sip_device_id?: string });
  try {
    await deleteGb28181SipDevice(sipId);
    createMessage.success('删除成功');
    if (gbDetailVisible.value && gbDetailSipId.value === sipId) {
      closeGbDetail();
    }
    handleSuccess();
  } catch (error) {
    console.error('删除国标设备失败', error);
    createMessage.error('删除失败');
  }
}

function handleTableViewGbDevice(record: DeviceInfo & { sip_device_id?: string }) {
  openGbDeviceInfoModal('view', { sipDeviceId: gbSipIdFromRecord(record) });
}

function handleTableEditGbDevice(record: DeviceInfo & { sip_device_id?: string }) {
  openGbDeviceInfoModal('edit', { sipDeviceId: gbSipIdFromRecord(record) });
}

// 设备流状态映射
const deviceStreamStatuses = ref<Record<string, string>>({});
// 状态检查定时器
const statusCheckTimer = ref<NodeJS.Timeout | null>(null);

// 获取流状态文本
const getStreamStatusText = (status: string) => {
  const statusMap: Record<string, string> = {
    'running': '运行中',
    'stopped': '已停止',
    'error': '错误',
    'unknown': '未知'
  };
  return statusMap[status] || status;
};

// 获取流状态颜色
const getStreamStatusColor = (status: string) => {
  const colorMap: Record<string, string> = {
    'running': 'green',
    'stopped': 'red',
    'error': 'orange',
    'unknown': 'default'
  };
  return colorMap[status] || 'default';
};

// 检查单个设备的流状态
const checkDeviceStreamStatus = async (deviceId: string) => {
  try {
    // 确保 deviceStreamStatuses.value 始终是一个对象
    if (!deviceStreamStatuses.value) {
      deviceStreamStatuses.value = {};
    }
    const response: StreamStatusResponse = await getStreamStatus(deviceId);
    if (response.code === 0) {
      deviceStreamStatuses.value[deviceId] = response.data.status;
    } else {
      deviceStreamStatuses.value[deviceId] = 'error';
    }
  } catch (error) {
    console.error(`检查设备 ${deviceId} 流状态失败`, error);
    // 确保 deviceStreamStatuses.value 始终是一个对象
    if (!deviceStreamStatuses.value) {
      deviceStreamStatuses.value = {};
    }
    deviceStreamStatuses.value[deviceId] = 'error';
  }
};

// 检查所有设备的流状态
const checkAllDevicesStreamStatus = async (devices: DeviceInfo[]) => {
  try {
    const deviceIds = devices.map(device => device.id);
    for (const deviceId of deviceIds) {
      await checkDeviceStreamStatus(deviceId);
    }
  } catch (error) {
    console.error('检查设备流状态失败', error);
  }
};

function getRecordStreamStatus(deviceId: string) {
  return (deviceStreamStatuses.value && deviceStreamStatuses.value[deviceId]) || 'unknown';
}

const [registerTable, {reload}] = useTable({
  canResize: true,
  showIndexColumn: false,
  title: '摄像头列表',
  api: fetchMergedDeviceList,
  columns: getBasicColumns(),
  useSearchForm: true,
  showTableSetting: false,
  pagination: true,
  formConfig: getFormConfig(),
  fetchSetting: {
    listField: 'data',
    totalField: 'total',
  },
  rowKey: 'id',
  scroll: { x: 1200 },
  beforeFetch: (params) => ({
    ...params,
    search: params.search ?? params.deviceName,
    deviceName: params.deviceName ?? params.search,
  }),
  // 添加成功回调，获取设备流状态
  onSuccess: (data) => {
    if (data && data.data) {
      // 确保 deviceStreamStatuses.value 始终是一个对象
      if (!deviceStreamStatuses.value) {
        deviceStreamStatuses.value = {};
      }
      // 初始化设备流状态
      data.data.forEach((device: DeviceInfo) => {
        if (!deviceStreamStatuses.value[device.id]) {
          deviceStreamStatuses.value[device.id] = 'unknown';
        }
      });

      // 已禁用自动检查设备流状态
      // checkAllDevicesStreamStatus(data.data);
    }
  }
});

// 启动状态检查定时器
const startStatusCheckTimer = () => {
  if (statusCheckTimer.value) {
    clearInterval(statusCheckTimer.value);
  }

  statusCheckTimer.value = setInterval(() => {
    if (Object.keys(deviceStreamStatuses.value).length > 0) {
      Object.keys(deviceStreamStatuses.value).forEach(deviceId => {
        checkDeviceStreamStatus(deviceId);
      });
    }
  }, 10000); // 每10秒检查一次
};

// 获取表格操作按钮
const getTableActions = (record) => {
  if (isNvrListRow(record)) {
    const nvrId = record.nvr_id_num ?? Number(String(record.id).replace(/^nvr_/, ''));
    const nvrCard = {
      nvrId,
      name: record.name || `[NVR] ${record.ip}`,
      ip: record.ip,
      port: record.port ?? 80,
      camera_count: record.channel_count ?? 0,
      _nvr: { id: nvrId, ip: record.ip },
    } as NvrCardItem;
    return [
      {
        icon: 'ant-design:cluster-outlined',
        tooltip: '挂载摄像头',
        onClick: () => openNvrDetail(nvrCard),
      },
      {
        icon: 'ant-design:eye-filled',
        tooltip: '详情',
        onClick: () => openNvrInfoModal('view', { nvr_id_num: nvrId }),
      },
      {
        icon: 'ant-design:edit-filled',
        tooltip: '编辑',
        onClick: () => openNvrInfoModal('edit', { nvr_id_num: nvrId }),
      },
      {
        icon: 'ant-design:copy-outlined',
        tooltip: '复制 IP',
        onClick: () => {
          const text = `${record.ip}:${record.port ?? 80}`;
          navigator.clipboard?.writeText(text).then(
            () => createMessage.success('复制成功'),
            () => createMessage.error('复制失败'),
          );
        },
      },
      {
        icon: 'material-symbols:delete-outline-rounded',
        danger: true,
        tooltip: '删除',
        popConfirm: {
          title: '删除后挂载摄像头将解除关联，是否确认？',
          confirm: () => handleDeleteNvrDevice(nvrCard),
        },
      },
    ];
  }
  if (isGb28181SipListRow(record)) {
    return [
      {
        icon: 'ant-design:eye-filled',
        tooltip: '详情',
        onClick: () => handleTableViewGbDevice(record),
      },
      {
        icon: 'ant-design:edit-filled',
        tooltip: '编辑',
        onClick: () => handleTableEditGbDevice(record),
      },
      {
        icon: 'ant-design:video-camera-outlined',
        tooltip: '通道列表',
        onClick: () => {
          openGbDetail({
            sipDeviceId: gbSipIdFromRecord(record),
            name: record.name || record.sip_device_id,
            channelCount: record.channel_count || 0,
            online: !!record.online,
            channels: [],
          });
        },
      },
      {
        icon: 'material-symbols:delete-outline-rounded',
        danger: true,
        tooltip: '删除',
        popConfirm: {
          title: '删除后 WVP 国标设备及已同步的通道将移除，是否确认？',
          confirm: () => handleDeleteGbDevice(record),
        },
      },
    ];
  }

  const actions = [];

  if (hasDirectPlayStream(record)) {
    actions.push({
      icon: 'octicon:play-16',
      tooltip: supportsRtspForward(record) ? '播放视频流' : '播放国标通道',
      onClick: () => handlePlay(record),
    });
  }

  if (hasDirectPlayStream(record, true)) {
    actions.push({
      icon: 'hugeicons:ai-video',
      tooltip: '查看AI流',
      onClick: () => handlePlayAIStream(record),
    });
  }

  if (canSetDeviceLocation(record)) {
    actions.unshift({
      icon: 'ant-design:environment-outlined',
      tooltip: '设置坐标',
      label: '坐标',
      onClick: () => openDeviceLocationDrawer(record),
    });
  }

  // 添加详情、编辑、删除按钮
  actions.push(
    {
      icon: 'ant-design:eye-filled',
      tooltip: '详情',
      onClick: () => openAddModal('view', record)
    },
    {
      icon: 'ant-design:edit-filled',
      tooltip: '编辑',
      onClick: () => openAddModal('edit', record)
    },
    {
      icon: 'material-symbols:delete-outline-rounded',
      danger: true,
      tooltip: '删除',
      popConfirm: {
        title: '确定删除此设备？',
        confirm: () => handleDelete(record),
      },
    },
  );

  return actions;
};

// 表格刷新
function handlePlayerSuccess() {
}

function handlePlay(record: DeviceInfo) {
  if (!openDeviceInDialogPlayer(openPlayerAddModel, record)) {
    createMessage.warning('该设备暂无可播放地址');
  }
}

function handlePlayAIStream(record: DeviceInfo) {
  if (!openDeviceInDialogPlayer(openPlayerAddModel, record, { ai: true })) {
    createMessage.warning('该设备暂无 AI 流地址');
  }
}

async function handleCopy(text: string) {
  if (navigator.clipboard) {
    await navigator.clipboard.writeText(text);
  } else {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
  }
  createMessage.success('复制成功');
}

// 打开模态框
const openAddModal = (type, record = null) => {
  openModal(true, {
    type,
    record,
    isEdit: type === 'edit',
    isView: type === 'view'
  });
};

function openDeviceCreate(query?: Partial<{ kind: DeviceKind; method: CreateMethod; brand: CameraBrand }>) {
  if (query?.kind) deviceCreateInitial.kind = query.kind;
  if (query?.method) deviceCreateInitial.method = query.method;
  if (query?.brand) deviceCreateInitial.brand = query.brand;
  deviceCreateVisible.value = true;
}

function closeDeviceCreate() {
  deviceCreateVisible.value = false;
}

function handleDeviceCreateSuccess() {
  handleSuccess();
}

function handleLocationImportSuccess() {
  handleLocationDrawerSuccess();
}

function openDeviceLocationDrawer(record: DeviceInfo | { id: string; name?: string }) {
  if (!canSetDeviceLocation(record)) return;
  openLocationModal(true, { deviceId: record.id, record });
}

function handleLocationDrawerSuccess() {
  handleSuccess();
}

function handleCardSetLocation(record: DeviceInfo) {
  openDeviceLocationDrawer(record);
}

function handleSuccess() {
  if (viewMode.value === 'table') {
    reload();
  } else if (deviceMixedCardListRef.value) {
    deviceMixedCardListRef.value.fetch();
  }
}

// 删除设备
const handleDelete = async (record) => {
  try {
    await deleteDevice(record.id);
    createMessage.success('删除成功');
    handleSuccess();
  } catch (error) {
    console.error('删除失败', error);
    createMessage.error('删除失败');
  }
};

// 卡片视图事件处理
const handleCardView = (record) => {
  if (isGb28181SipListRow(record)) {
    handleTableViewGbDevice(record);
    return;
  }
  openAddModal('view', record);
};

const handleCardEdit = (record) => {
  if (isGb28181SipListRow(record)) {
    handleTableEditGbDevice(record);
    return;
  }
  openAddModal('edit', record);
};

const handleCardDelete = async (record) => {
  if (isGb28181SipListRow(record)) {
    await handleDeleteGbDevice(record);
    return;
  }
  await handleDelete(record);
};

async function handleNvrChannelDelete(record: DeviceInfo) {
  await handleDelete(record);
  if (nvrDetailVisible.value) {
    nvrDeviceDetailRef.value?.load?.();
  }
}

const handleCardPlay = (record) => {
  handlePlay(record);
};

const handleCardPlayAI = (record) => {
  handlePlayAIStream(record);
};

/** 根据路由 query 切换 Camera 一级 Tab（子 Tab 如 storage 由 StorageSpace 自行同步，不触发整页刷新） */
function applyCameraRouteQuery() {
  const prevActiveKey = state.activeKey;
  const rawTab = route.query.tab as string;
  if (rawTab === '3' || route.query.mode === 'config') {
    splitScreenInitialMode.value = 'config';
  }
  if (route.query.mode === 'map') {
    state.activeKey = CAMERA_TAB_KEYS.CAMERA_MAP;
  } else if (rawTab) {
    state.activeKey = normalizeCameraRouteTab(rawTab);
    if (rawTab === '5' && !route.query.storage) {
      router.replace({
        path: route.path,
        query: { ...route.query, tab: CAMERA_TAB_KEYS.STORAGE, storage: 'record' },
      });
    }
  } else if (route.query.mode === 'config') {
    state.activeKey = CAMERA_TAB_KEYS.SPLIT_MONITOR;
  }
  if (route.query.action === 'create' && state.activeKey === CAMERA_TAB_KEYS.DEVICE_LIST) {
    const parsed = parseDeviceCreateQuery(route.query as Record<string, unknown>);
    openDeviceCreate(parsed);
  }
  // 仅首次进入「存储空间」一级 Tab 时刷新；子 Tab（storage=）切换保持已挂载状态，避免重复拉树
  if (
    state.activeKey === CAMERA_TAB_KEYS.STORAGE &&
    prevActiveKey !== CAMERA_TAB_KEYS.STORAGE
  ) {
    void nextTick(() => {
      storageSpaceRef.value?.refresh?.();
    });
  }
  if (
    state.activeKey === CAMERA_TAB_KEYS.CAMERA_MAP &&
    prevActiveKey !== CAMERA_TAB_KEYS.CAMERA_MAP
  ) {
    void nextTick(() => {
      cameraMapDistributionRef.value?.refresh?.();
    });
  }
}

watch(
  () => route.query.tab,
  () => applyCameraRouteQuery(),
);

// 组件挂载时启动状态检查定时器
onMounted(() => {
  applyCameraRouteQuery();
});

// 组件卸载时清除定时器
onUnmounted(() => {
  if (statusCheckTimer.value) {
    clearInterval(statusCheckTimer.value);
    statusCheckTimer.value = null;
  }
});
</script>

<style lang="less" scoped>
.camera-container {
  :deep(.ant-form-item) {
    margin-bottom: 10px;
  }

  .camera-tab {
    padding: 16px 19px 0 15px;

    :deep(.ant-tabs-nav) {
      padding: 5px 0 0 25px;
    }

    :deep(.ant-tabs) {
      background-color: #FFFFFF;

      :deep(.ant-tabs-nav) {
        padding: 5px 0 0 25px;
      }
    }
  }

  .device-list-toolbar {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
    flex: 1;
    width: 100%;
    margin-left: auto;

    &--card {
      flex: none;
      width: auto;
      margin-left: 0;
    }
  }

  .device-list-table-wrap {
    :deep(.vben-basic-table-header__toolbar) {
      flex: 1;
      justify-content: flex-end;
    }

    :deep(.vben-basic-table-form-container) {
      padding: 12px 12px 0;

      > .ant-form > .ant-row {
        flex-wrap: nowrap;
      }

      .ant-form-item {
        margin-bottom: 16px;
      }

      .ant-form-item-control-input-content:has(.ant-btn) {
        display: flex;
        justify-content: flex-end;
        flex-wrap: nowrap;
        gap: 8px;
        white-space: nowrap;
      }
    }

    :deep(.ant-table-wrapper) {
      padding: 0 12px 12px;
    }

    :deep(.ant-table-cell) {
      vertical-align: middle;
    }

    :deep(.vben-basic-table-action) {
      flex-wrap: wrap;
      justify-content: center;
      row-gap: 2px;

      .ant-btn-link {
        height: 28px;
        padding: 4px 6px;
      }

      .ant-btn-link.ant-btn-dangerous {
        color: #dc2626;

        &:hover {
          color: #b91c1c;
        }
      }
    }
  }

  .device-list-table__copyable {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    max-width: 100%;
    cursor: pointer;
    color: rgba(0, 0, 0, 0.88);

    &:hover {
      color: #4287fc;
    }
  }

  .device-list-table__location-link {
    color: #266cfb;
    cursor: pointer;

    &:hover {
      text-decoration: underline;
    }
  }

  .device-list-table__location-muted {
    color: rgba(0, 0, 0, 0.25);
  }
}
</style>
