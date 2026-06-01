import type { AppRouteRecordRaw } from '@/router/types'
import { EXCEPTION_COMPONENT, LAYOUT, PAGE_NOT_FOUND_NAME, REDIRECT_NAME } from '@/router/constant'

// 404 on a page
export const PAGE_NOT_FOUND_ROUTE: AppRouteRecordRaw = {
  path: '/:path(.*)*',
  name: PAGE_NOT_FOUND_NAME,
  component: LAYOUT,
  meta: {
    title: 'ErrorPage',
    hideBreadcrumb: true,
    hideMenu: true,
  },
  children: [
    {
      path: '/:path(.*)*',
      name: PAGE_NOT_FOUND_NAME,
      component: EXCEPTION_COMPONENT,
      meta: {
        title: 'ErrorPage',
        hideBreadcrumb: true,
        hideMenu: true,
      },
    },
  ],
}

/** GB28181：按名称跳转（不依赖后台菜单是否配置了同名路由） */
export const GB28181_ROUTE_MODULE: AppRouteRecordRaw = {
  path: '/gb28181-view',
  component: LAYOUT,
  name: 'Gb28181ViewLayout',
  meta: {
    title: 'GB28181',
    hideMenu: true,
    hideBreadcrumb: true,
  },
  children: [
    {
      path: 'channel/:deviceIdentification',
      name: 'Gb28181Channel',
      component: () => import('@/views/gb28181/components/Channel/index.vue'),
      meta: {
        title: '通道管理',
        hideMenu: true,
        canTo: true,
      },
    },
    {
      path: 'cloud-record/:deviceId/:channelId',
      name: 'Gb28181CloudRecord',
      component: () => import('@/views/gb28181/components/CloudRecord/index.vue'),
      meta: {
        title: '云端录像',
        hideMenu: true,
        canTo: true,
      },
    },
    {
      path: 'device-record/:deviceId/:channelId',
      name: 'Gb28181DeviceRecord',
      component: () => import('@/views/gb28181/components/DeviceRecord/index.vue'),
      meta: {
        title: '设备录像',
        hideMenu: true,
        canTo: true,
      },
    },
  ],
}

/** 人脸管理独立页（从人脸库列表跳转） */
export const FACE_MANAGE_ROUTE: AppRouteRecordRaw = {
  path: '/face-manage',
  component: LAYOUT,
  name: 'FaceManageLayout',
  meta: {
    title: '人脸管理',
    hideMenu: true,
    hideBreadcrumb: true,
  },
  children: [
    {
      path: ':libraryId',
      name: 'FaceManage',
      component: () => import('@/views/face-manage/index.vue'),
      meta: {
        title: '人脸管理',
        hideMenu: true,
        canTo: true,
        activeMenu: 'camera/index',
      },
    },
  ],
}

export const REDIRECT_ROUTE: AppRouteRecordRaw = {
  path: '/redirect',
  component: LAYOUT,
  name: 'RedirectTo',
  meta: {
    title: REDIRECT_NAME,
    hideBreadcrumb: true,
    hideMenu: true,
  },
  children: [
    {
      path: '/redirect/:path(.*)/:_redirect_type(.*)/:_origin_params(.*)?',
      name: REDIRECT_NAME,
      component: () => import('@/views/base/redirect/index.vue'),
      meta: {
        title: REDIRECT_NAME,
        hideBreadcrumb: true,
      },
    },
  ],
}
