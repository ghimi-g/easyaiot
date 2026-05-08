# 实时算法服务：RTSP/RTMP 异步拉流（缓解 GB28181 链路灰屏与有效帧率受限）

## 解决的问题

在 **国标 GB28181** 等业务场景下，播放地址常解析为 **RTSP 或 RTMP**。实时算法服务的缓流线程使用 OpenCV `VideoCapture` 拉流时，容易出现：

- **画面灰屏、解码异常堆积**：解码与业务逻辑在同一线程串行时，容易造成缓冲区行为不符合预期，或与既有「灰屏检测」逻辑叠加后出现误判、重连抖动。
- **有效处理帧率被摄像头帧率“锁住”**：即便推理很快，主路径仍被迫按「同步 `read()`」的节奏取样，无法充分利用「总是处理最新一帧」的策略。
- **端到端延迟与卡顿感**：同步读阻塞期间，后续环节（缓冲、抽帧、推理）整体被拉长。

本文档描述问题的成因、`VIDEO/services/realtime_algorithm_service/run_deploy.py` 中的 **异步拉流** 实现思路，以及如何通过环境变量开关。

## 问题原因

### 1. `cv2.VideoCapture.read()` 的阻塞语义

默认用法下，**`read()` 会阻塞直到下一帧解码完成**（或失败返回）。若源流为 **25fps**，在同一线程里循环调用 `read()` 时，该调用本身的节拍近似 **每秒最多 25 次**，并不随推理加速而变快。

### 2. 解码与业务在同一调用栈串行

缓流器线程既要 **持续拉流**，又要 **帧率控制、推流、队列交互** 等。同步 `read()` 占用线程时间越长，越容易与其它逻辑争抢时间片，表现为卡顿或「总是读到过期帧」。

### 3. 缓冲区与灰屏现象叠加

通过 `CAP_PROP_BUFFERSIZE` 等减少队列深度可降低延迟，但若仍是「谁在何时调用 `read()`」唯一决定解码进度，在网络抖动、IDR 间隔、TCP 重传等场景下，仍可能出现长时间读到异常平面帧（灰屏）或与检测逻辑冲突。**把解码固定在同一线程**，会放大上述不确定性。

## 解决方案概述

采用与用户侧常见实践一致的模式：**单独线程专职拉流解码**，主线程只从锁保护的缓冲区中取 **最新一帧的拷贝** 继续做缓冲、检测与推流。

要点：

1. **后台线程**：循环调用 `VideoCapture.read()`，将最近一次成功解码的帧写入共享变量。
2. **互斥锁**：保证读写帧指针时的线程安全。
3. **`CAP_PROP_BUFFERSIZE=1`**：在创建 `VideoCapture` 后仍保留设置，尽量减少管道内堆积的旧帧（具体行为依赖 FFmpeg/OpenCV 版本）。
4. **与既有重连逻辑兼容**：异步模式下若 `(ret, frame)` 暂时为空，需区分 **「首帧未到」** 与 **「解码失败/流结束」**，避免误判断流；解码线程在主动 `release()` 时不应将「正常关闭」标成失败（详见代码中的 `_running` / `read_failed` 处理）。
5. **可关闭**：通过环境变量 **`AI_RTSP_ASYNC_READ`** 可在排查问题时恢复同步 `read()`。

## 配置说明

| 变量 | 含义 | 默认 |
|------|------|------|
| `AI_RTSP_ASYNC_READ` | 对 **rtsp://**、**rtmp://** 是否启用异步拉流（后台解码线程） | `1`（启用） |

关闭示例（恢复同步读，便于对比日志与行为）：

```bash
AI_RTSP_ASYNC_READ=0
```

项目内可在以下模板/环境中找到同名字段（与 `env.example` 及 `VIDEO/.env*` 保持同步）：

- `VIDEO/services/realtime_algorithm_service/env.example`
- `VIDEO/.env`、`VIDEO/.env.docker`、`VIDEO/.env.prod`

## 代码位置

- **共享实现**：`VIDEO/app/utils/async_video_stream.py`（**`AsyncVideoStream`**、**`async_rtsp_read_enabled()`**，环境变量 **`AI_RTSP_ASYNC_READ`**）。
- **实时算法**：`VIDEO/services/realtime_algorithm_service/run_deploy.py` → `buffer_streamer_worker()`：打开 **RTSP/RTMP** 后按需包装异步对象；主循环区分 **`read_failed`** 与首帧等待（短睡眠）。
- **推流转发**：`VIDEO/services/stream_forward_service/run_deploy.py` → 各设备读取器线程：逻辑同上（无实时算法的灰屏检测，但有读失败重试）。
- **抓拍算法**：`VIDEO/services/snapshot_algorithm_service/run_deploy.py` → 抓拍缓流主循环：同上，并与原有 RTSP 灰屏重连逻辑共用 **`cap.release()`**。

## 使用与排查建议

1. **默认保持开启**（`AI_RTSP_ASYNC_READ=1`），观察灰屏、卡顿、有效抽帧率是否改善。
2. 若需确认是否为异步路径问题，**临时设 `0`** 对比同一路 GB28181 源的表现。
3. 灰屏类问题仍可能来自 **网络、编码（如 HEVC）**、**ZLM/无读者回收** 等，需结合已有 `AI_RTSP_GRAY_*` 与 `GB28181_*` 配置与日志综合判断；本文档仅覆盖 **拉流与主线程解耦** 这一层。

## FAQ：为什么有人觉得「非 GB28181 更流畅、不灰」？代码是不是早就对直连做了异步？

### 结论：拉流侧只有一条路，不按「是不是国标」分两套读帧代码

1. **配置加载时**：设备 `source` 若是 `gb28181://...`，会先经 `resolve_gb28181_source()` 解析成真实的 **`rtsp://` / `rtmp://`**；若是直连地址，得到的也是同样的 **`rtsp_url`** 字符串。
2. **缓流线程 `buffer_streamer_worker()`** 里 **只使用解析后的 `rtsp_url`**，**没有**「GB28181 专用分支 vs 直连专用分支」两套 `VideoCapture` 逻辑。
3. **启用异步拉流时**：只要 URL 是 **`rtsp://` 或 `rtmp://`** 且 **`AI_RTSP_ASYNC_READ=1`**，**无论该 URL 来自国标解析还是设备里直接填写**，都会同样包一层 **`AsyncVideoStream`**。

因此：**不是**「非 GB28181 早就偷偷用了异步、国标才用同步」——**在引入 `AsyncVideoStream` 之前**，两类来源 **都是** 同步 `read()`；**引入之后**，两类来源在 RTSP/RTMP 下 **也是同一套异步**（开关一致时）。

### 那为什么体感上「直连更顺、国标更易灰」？

差的多半是 **链路复杂度与环境**，而不是程序里另一段「只对直连生效」的读法：

| 对比 | 直连相机 / 简单 RTSP | 经 GB28181 / 平台（如 ZLM） |
|------|---------------------|------------------------------|
| 环节 | 往往少（如：相机 → 算法进程） | 多：信令、播发、RTMP/RTSP 候选、保活等 |
| 编码与封装 | 相对固定 | HEVC、转封装、缺关键帧等更容易触发解码异常或灰片 |
| 服务端行为 | 相对单纯 | 无读者回收流、播发顺序策略等，更容易抖 |

**更顺的是「路更简单」的那条链路**，不是「非 GB28181 走了另一套拉流代码」。

## 相关文档

- `VIDEO/docs/fix_stream_busy_error.md`：推流侧 StreamBusy 与冲突处理
- `VIDEO/services/realtime_algorithm_service/env.example`：实时算法任务环境变量说明
- `VIDEO/services/snapshot_algorithm_service/env.example`：抓拍服务（含 `AI_RTSP_ASYNC_READ` 说明）
