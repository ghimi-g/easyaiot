<template>
  <div style="width: 100%; height: 100%; background-color: #000c17">
    <div ref="container" class="jessibuca-container" @dblclick="fullscreen" @mousemove="mouseenter">
      <transition name="toolBtn">
        <div
          v-if="showToolBtn"
          class="buttons-box"
          id="buttonsBox"
          @mouseenter="keepShowTool"
          @mousemove="
            (e) => {
              e.stopPropagation()
            }
          "
          @mouseleave="mouseenter"
        >
          <div class="buttons-box-left">
            <Icon
              v-if="!playing"
              :size="iconSize"
              class="jessibuca-btn"
              icon="ic:baseline-play-arrow"
              @click="play"
            />
            <Icon
              :size="iconSize"
              v-if="playing"
              class="jessibuca-btn"
              icon="ic:baseline-pause"
              @click="pause"
            />
            <Icon
              :size="iconSize"
              icon="ic:baseline-stop"
              class="jessibuca-btn"
              @click="destroy"
            />
            <Icon
              :size="iconSize"
              v-if="!quieting"
              icon="ic:baseline-volume-up"
              class="jessibuca-btn"
              @click="mute"
            />
            <Icon
              :size="iconSize"
              v-if="quieting"
              icon="ic:baseline-volume-off"
              class="jessibuca-btn"
              @click="cancelMute"
            />
          </div>
          <div class="buttons-box-right">
            <span class="jessibuca-btn">{{ kbs }} kb/s</span>
            <Icon
              :size="iconSize"
              icon="ic:baseline-camera"
              class="jessibuca-btn"
              @click="screenShot"
            />
            <Icon
              v-if="!recording"
              :size="iconSize"
              icon="tabler:video"
              class="jessibuca-btn"
              @click="startRecord"
            />
            <Icon
              v-if="recording"
              :size="iconSize"
              icon="fluent-emoji-flat:stop-sign"
              class="jessibuca-btn"
              @click="stopAndSaveRecord"
            />
            <Icon
              :size="iconSize"
              v-if="!isFull"
              icon="ic:baseline-fullscreen"
              class="jessibuca-btn"
              @click="fullscreen"
            />
          </div>
        </div>
      </transition>
    </div>
  </div>
</template>

<script>

import {Icon} from "@/components/Icon";
import {ref} from "vue";
import {signStreamUrl, isProtectedStreamUrl, clearTicketForUrl} from "@/views/camera/utils/streamTicket";

export default {
  name: "Player",
  components: {Icon},
  emits: ["stream-error"],
  props: {
    playUrl: {
      type: String,
      required: true,
    },
    hasAudio: {
      type: Boolean,
      required: true,
    }
  },
  data() {
    return {
      jessibuca: null,
      version: '',
      wasm: false,
      vc: "ff",
      playing: false,
      quieting: true,
      loaded: false, // mute
      showOperateBtns: false,
      showBandwidth: false,
      err: "",
      speed: 0,
      performance: "",
      volume: 1,
      rotate: 0,
      useWCS: false,
      useMSE: true,
      useOffscreen: false,
      recording: false,
      recordType: 'mp4',
      scale: 0,
      iconSize: 16,
      showToolBtnTimer: 0,
      showToolBtn: false,
      kbs: 0,
      isFull: false,
      // 受保护流(secure_link)票据过期/报错时的静默续票重试计数
      protectedRetries: 0,
      maxProtectedRetries: 2,
    };
  },
  mounted() {
    this.create();
    window.onerror = (msg) => (this.err = msg);
    if (this.playUrl) {
      this.$nextTick(() => this.play());
    }
  },
  watch: {
    playUrl(url) {
      this.protectedRetries = 0; // 切换地址，重置续票重试计数
      if (url && this.jessibuca) {
        this.$nextTick(() => this.play());
      }
    },
  },
  async unmounted() {
    if(this.jessibuca){
      await this.jessibuca.destroy();
      this.jessibuca = null;
    }
  },
  methods: {
    create(options) {
      options = options || {};
      const pageHttps =
        typeof window !== 'undefined' && window.location.protocol === 'https:';
      this.jessibuca = new window.Jessibuca(
        Object.assign(
          {
            container: this.$refs.container,
            decoder: '/static/js/jessibuca/decoder.js',
            videoBuffer: 0.2, // 缓存时长
            isResize: true, // 等比缩放，避免子码流(4:3)在16:9格子里被拉伸放大
            useWCS: pageHttps,
            useMSE: this.useMSE,
            autoWasm: true,
            text: "",
            loadingText: "疯狂加载中...",
            debug: false,
            supportDblclickFullscreen: true,
            showBandwidth: this.showBandwidth, // 显示网速
            operateBtns: {
              fullscreen: this.showOperateBtns,
              screenshot: this.showOperateBtns,
              play: this.showOperateBtns,
              audio: this.showOperateBtns,
            },
            vod: this.vod,
            forceNoOffscreen: !this.useOffscreen,
            isNotMute: true,
            timeout: 10,
            loadingTimeout: 10,
            // 关闭 Jessibuca 自带的「同地址重放」：受保护流的票据会过期，重放旧地址会一直 403。
            // 改由本组件在 error/timeout 时强制重新签发再重连（见 maybeRenewOnError）。
            loadingTimeoutReplay: false,
            heartTimeoutReplay: false,
            wasmDecodeErrorReplay: true,
          },
          options
        )
      );
      var _this = this;
      this.jessibuca.on("load", function () {
        console.log("on load");
      });
      this.jessibuca.on("log", function (msg) {
        console.log("on log", msg);
      });
      this.jessibuca.on("record", function (msg) {
        console.log("on record:", msg);
      });
      this.jessibuca.on("pause", function () {
        console.log("on pause");
        _this.playing = false;
      });
      this.jessibuca.on("play", function () {
        console.log("on play");
        _this.playing = true;
        _this.protectedRetries = 0; // 成功起播，重置续票重试计数
      });
      this.jessibuca.on("fullscreen", function (msg) {
        console.log("on fullscreen", msg);
      });
      this.jessibuca.on("mute", function (msg) {
        console.log("on mute", msg);
        _this.quieting = msg;
      });
      this.jessibuca.on("mute", function (msg) {
        console.log("on mute2", msg);
      });
      this.jessibuca.on("audioInfo", function (msg) {
        console.log("audioInfo", msg);
      });
      // this.jessibuca.on("bps", function (bps) {
      //   // console.log('bps', bps);
      // });
      // let _ts = 0;
      // this.jessibuca.on("timeUpdate", function (ts) {
      //     console.log('timeUpdate,old,new,timestamp', _ts, ts, ts - _ts);
      //     _ts = ts;
      // });
      this.jessibuca.on("videoInfo", function (info) {
        console.log("videoInfo", info);
      });
      this.jessibuca.on("error", function (error) {
        console.log("error", error);
        if (_this.maybeRenewOnError()) return;
        _this.$emit("stream-error", { type: "error", detail: error });
      });
      this.jessibuca.on("timeout", function () {
        console.log("timeout");
        if (_this.maybeRenewOnError()) return;
        _this.$emit("stream-error", { type: "timeout" });
      });
      this.jessibuca.on('start', function () {
        console.log('frame start');
      })
      this.jessibuca.on("performance", function (performance) {
        var show = "卡顿";
        if (performance === 2) {
          show = "非常流畅";
        } else if (performance === 1) {
          show = "流畅";
        }
        _this.performance = show;
      });
      this.jessibuca.on('buffer', function (buffer) {
        console.log('buffer', buffer);
      })
      this.jessibuca.on('stats', function (stats) {
        console.log('stats', stats);
      })
      this.jessibuca.on('kBps', function (kBps) {
        _this.kbs = Math.round(kBps)
      });
      this.jessibuca.on("play", () => {
        this.playing = true;
        this.loaded = true;
        this.quieting = this.jessibuca.isMute();
      });
      this.jessibuca.on('recordingTimestamp', (ts) => {
        console.log('recordingTimestamp', ts);
      })
      // console.log(this.jessibuca);
    },
    async play(forceRefresh = false) {
      // 模板 @click="play" 会把鼠标事件当参数传入，这里归一为布尔，避免手动点播时被误判为强制续票
      const force = forceRefresh === true;
      if (!this.jessibuca && this.$refs.container) {
        this.create();
      }
      if (!this.playUrl || !this.jessibuca) return;

      let target = this.playUrl;
      // 受保护流(/ai /live /rtp)需带 secure_link 票据，未签名会被 nginx 403
      if (isProtectedStreamUrl(this.playUrl)) {
        const reqUrl = this.playUrl;
        try {
          target = await signStreamUrl(this.playUrl, { forceRefresh: force });
        } catch (e) {
          // 签发失败(mint 不可用/网络/会话过期)：降级用未签名地址尽力播放，
          // 不把整路播放卡死在签发服务上：强制校验关闭时仍可播；开启时会 403 ->
          // on('error') -> maybeRenewOnError 再续票自愈；若是 401，axios 已统一跳登录。
          console.warn("stream ticket sign failed, fallback to unsigned url", e);
          target = this.playUrl;
        }
        // 防竞态：等待签发期间地址已切换/组件已销毁则放弃
        if (this.playUrl !== reqUrl || !this.jessibuca) return;
      }
      this.jessibuca.play(target);
    },
    // 受保护流报错(多为票据过期/连接被关)时：强制重新签发并重连，限次防死循环。
    // 返回 true 表示已接管(吞掉本次错误)，false 表示交回上层 emit stream-error。
    maybeRenewOnError() {
      if (!isProtectedStreamUrl(this.playUrl)) return false;
      if (this.protectedRetries >= this.maxProtectedRetries) return false;
      this.protectedRetries++;
      clearTicketForUrl(this.playUrl);
      this.play(true);
      return true;
    },
    mute() {
      this.jessibuca.mute();
    },
    cancelMute() {
      this.jessibuca.cancelMute();
    },
    pause() {
      this.jessibuca.pause();
      this.playing = false;
      this.err = "";
      this.performance = "";
    },
    volumeChange() {
      this.jessibuca.setVolume(this.volume);
    },
    rotateChange() {
      this.jessibuca.setRotate(this.rotate);
    },
    async destroy() {
      if (this.jessibuca) {
        await this.jessibuca.destroy();
        this.jessibuca = null;
      }
      // 仅当容器仍在(切流复用)时才重建；容器已被移除(删格/卸载)时跳过，避免 "Jessibuca need container option" 崩溃
      if (this.$refs.container) {
        this.create();
      }
      this.playing = false;
      this.loaded = false;
      this.performance = "";
    },
    fullscreen() {
      this.jessibuca.setFullscreen(true);
    },
    clearView() {
      this.jessibuca.clearView();
    },
    startRecord() {
      this.recording = !this.recording;
      const time = new Date().getTime();
      this.jessibuca.startRecord(time, this.recordType);
    },
    stopAndSaveRecord() {
      this.recording = !this.recording;
      this.jessibuca.stopRecordAndSave();
    },
    screenShot() {
      this.jessibuca.screenshot();
    },
    mouseenter() {
      this.showToolBtn = true
      if (this.showToolBtnTimer) {
        window.clearTimeout(this.showToolBtnTimer)
      }
      this.showToolBtnTimer = window.setTimeout(() => {
        this.showToolBtn = false
      }, 4000)
    },
    keepShowTool() {
      console.log('keepShowToolkeepShowToolkeepShowTool')
      this.showToolBtn = true
      window.clearTimeout(this.showToolBtnTimer)
    },
    isFullscreen() {
      return document.fullscreenElement || false
    },
    async restartPlay(type) {
      if (type === 'mse') {
        this.useWCS = false;
        this.useOffscreen = false;
      } else if (type === 'wcs') {
        this.useMSE = false
      } else if (type === 'offscreen') {
        this.useMSE = false
      }
      await this.destroy();
      setTimeout(() => {
        this.play();
      }, 100)
    },
    changeBuffer() {
      this.jessibuca.setBufferTime(Number(0.2));
    },
    scaleChange() {
      this.jessibuca.setScaleMode(this.scale);
    },
  },
};
</script>

<style>
.buttons-box {
  width: 100%;
  height: 28px;
  background-color: rgba(43, 51, 63, 0.7);
  position: absolute;
  display: -webkit-box;
  display: -ms-flexbox;
  display: flex;
  left: 0;
  bottom: 0;
  user-select: none;
  z-index: 10;
  transition: opacity 1s ease;
}

.jessibuca-btn {
  width: 20px;
  color: rgb(255, 255, 255);
  line-height: 28px;
  margin: 0px 10px;
  padding: 0px 2px;
  cursor: pointer;
  text-align: center;
  font-size: 1rem !important;
}

.buttons-box-right {
  position: absolute;
  right: 0;
}

.toolBtn-enter-active {
  transition: all 0.1s;
  overflow: hidden;
}

.toolBtn-leave-active {
  transition: all 0.5s;
  overflow: hidden;
}

.toolBtn-enter-from,
.toolBtn-leave-to {
  height: 0px !important;
  opacity: 0;
}

.jessibuca-container video {
  max-height: 100%;
}
</style>
