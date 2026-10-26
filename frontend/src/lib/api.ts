import axios from "axios";
import { clearAuth } from "./auth";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
// 媒体地址（/uploads/...）挂在 API 根路径而非 /api/v1 下，需要单独取 origin
const API_ORIGIN = API_BASE_URL.replace(/\/api\/v1\/?$/, "");

// 默认 30s：普通 CRUD 足够。
// 注意：AI 生成（后端单次 httpx 超时 300s）、大文件上传、渲染提交都要单独放宽，
// 否则长任务必然在前端先断（原实现全站一个 30s，AI 接口基本必超时）。
const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  // 携带 httpOnly 会话 Cookie（安全升级：Token 不再存 localStorage）
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

/**
 * 把后端返回的媒体地址补成可访问的绝对地址。
 *
 * 后端返回的 /uploads/... 带 exp+sig 签名（M1 起媒体不再公开），
 * 但其路径是**相对 API 域**的；<img>/<video> 直接引用会被浏览器解析到前端域
 * （如 localhost:3000/uploads/...）从而 404 或 401。这里统一补 API origin。
 */
export function mediaUrl(url?: string | null): string | undefined {
  if (!url) return undefined;
  if (/^https?:\/\//i.test(url)) return url;
  if (url.startsWith("/")) return `${API_ORIGIN}${url}`;
  return url;
}

// 响应拦截器
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    // 401：登录过期/未登录 → 清除本地状态并跳转登录页
    if (error.response?.status === 401) {
      clearAuth();
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
    }
    const message =
      error.response?.data?.detail || error.message || "请求失败";
    console.error(`[API Error] ${message}`);
    return Promise.reject(new Error(message));
  }
);

// ===== 认证 API =====
export const authApi = {
  register: (data: {
    username: string;
    email: string;
    password: string;
    display_name?: string;
  }) => api.post("/auth/register", data),
  login: (data: { username: string; password: string }) =>
    api.post("/auth/login", data),
  me: () => api.get("/auth/me"),
  logout: () => api.post("/auth/logout"),
};

// ===== 项目 API =====
export const projectApi = {
  list: () => api.get("/projects"),
  get: (id: string) => api.get(`/projects/${id}`),
  create: (data: Record<string, unknown>) => api.post("/projects", data),
  update: (id: string, data: Record<string, unknown>) =>
    api.put(`/projects/${id}`, data),
  delete: (id: string) => api.delete(`/projects/${id}`),
};

// ===== 剧本 API =====
export const scriptApi = {
  get: (projectId: string) => api.get(`/projects/${projectId}/script`),
  update: (projectId: string, data: Record<string, unknown>) =>
    api.put(`/projects/${projectId}/script`, data),
  // AI 生成是同步串行调用（后端单次 httpx 超时 300s），前端必须放宽，
  // 否则 30s 就被 axios 掐断，而后端仍在跑、配额已扣 —— 用户看到失败但钱花了。
  aiGenerate: (projectId: string, prompt: string) =>
    api.post(`/projects/${projectId}/script/ai-generate`, { prompt }, { timeout: 330000 }),
  listScenes: (projectId: string) =>
    api.get(`/projects/${projectId}/script/scenes`),
  createScene: (projectId: string, data: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/script/scenes`, data),
  // 导出剧本（markdown/txt），返回原始文本
  exportText: async (
    projectId: string,
    format: "markdown" | "txt" = "markdown"
  ): Promise<string> => {
    const resp = await api.get(
      `/projects/${projectId}/script/export?format=${format}`,
      { responseType: "text" }
    );
    return String(resp);
  },
};

// ===== 分镜 API =====
export const storyboardApi = {
  get: (projectId: string) => api.get(`/projects/${projectId}/storyboard`),
  update: (projectId: string, data: Record<string, unknown>) =>
    api.put(`/projects/${projectId}/storyboard`, data),
  listShots: (projectId: string) =>
    api.get(`/projects/${projectId}/storyboard/shots`),
  createShot: (projectId: string, data: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/storyboard/shots`, data),
  updateShot: (
    projectId: string,
    shotId: string,
    data: Record<string, unknown>
  ) => api.put(`/projects/${projectId}/storyboard/shots/${shotId}`, data),
  // 从剧本一键生成分镜（AI）
  generateFromScript: (projectId: string) =>
    api.post(`/projects/${projectId}/storyboard/generate-from-script`),
  // 导出分镜（JSON）
  exportJson: (projectId: string) =>
    api.get(`/projects/${projectId}/storyboard/export`),
};

// ===== 角色 API =====
export const characterApi = {
  list: (projectId: string) =>
    api.get(`/projects/${projectId}/characters`),
  create: (projectId: string, data: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/characters`, data),
  update: (
    projectId: string,
    charId: string,
    data: Record<string, unknown>
  ) => api.put(`/projects/${projectId}/characters/${charId}`, data),
  delete: (projectId: string, charId: string) =>
    api.delete(`/projects/${projectId}/characters/${charId}`),
  aiGenerate: (projectId: string, description: string) =>
    api.post(
      `/projects/${projectId}/characters/ai-generate`,
      { description },
      { timeout: 330000 }
    ),
  // 为已有角色追加生成形象图
  generateImage: (projectId: string, charId: string) =>
    api.post(
      `/projects/${projectId}/characters/${charId}/generate-image`,
      undefined,
      { timeout: 330000 }
    ),
};

// ===== 渲染 API =====

/** 与后端 RenderConfigSchema 对齐（snake_case，直接透传给 FastAPI） */
export interface RenderConfigPayload {
  resolution: string;
  aspect_ratio: string;
  fps: number;
  visual_style: string;
  add_subtitles: boolean;
  subtitle_source: "description" | "label" | "none";
  add_bgm: boolean;
  bgm_source?: string | null;
  quality: string;
  ai_model: string;
}

export interface RenderSubmitPayload {
  name: string;
  config: RenderConfigPayload;
  /**
   * 幂等键：同一次"点击开始渲染"必须复用同一个值。
   * 后端据此去重，双击/重试不会排两次队（AI 按次计费，重复排队就是重复烧钱）。
   */
  idempotency_key: string;
}

/** 后端 RenderTaskResponse（snake_case，勿改成 camelCase） */
export interface RenderTaskDto {
  id: string;
  project_id: string;
  name: string;
  status: "queued" | "processing" | "completed" | "failed" | "cancelled";
  progress: number;
  config: Record<string, unknown>;
  output_url?: string | null;
  error_message?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  duration?: number | null;
  created_at: string;
  cancel_requested: boolean;
}

export interface RenderStatusDto {
  task_id: string;
  status: RenderTaskDto["status"];
  progress: number;
  output_url?: string | null;
  error_message?: string | null;
}

export const renderApi = {
  submit: (projectId: string, payload: RenderSubmitPayload) =>
    api.post(`/projects/${projectId}/render`, payload, { timeout: 30000 }),
  status: (taskId: string) => api.get(`/render/${taskId}/status`),
  list: (projectId: string) =>
    api.get(`/projects/${projectId}/render/tasks`),
  cancel: (taskId: string) => api.post(`/render/${taskId}/cancel`),
  download: (taskId: string) => api.get(`/render/${taskId}/download`),
  /** 查询某项目已提交的镜头数（用于渲染前提示"将生成几个镜头"） */
  shotCount: async (projectId: string): Promise<number> => {
    const shots = (await api.get(
      `/projects/${projectId}/storyboard/shots`
    )) as unknown as unknown[];
    return Array.isArray(shots) ? shots.length : 0;
  },
};

// ===== 素材 API =====

/** 后端 AssetResponse（snake_case） */
export interface AssetDto {
  id: string;
  project_id: string;
  name: string;
  type: "image" | "audio" | "video";
  mime_type: string;
  size: number;
  url: string;
  thumbnail_url?: string | null;
  tags: string[];
  duration?: number | null;
  width?: number | null;
  height?: number | null;
  uploaded_at: string;
}

export const assetApi = {
  list: (projectId: string, params?: { asset_type?: string; search?: string }) =>
    api.get(`/projects/${projectId}/assets`, { params }),
  /**
   * 上传素材。单文件上限由后端控制（默认 500MB），前端 timeout 必须放宽：
   * 30s 内传不完一个 100MB 的视频，会在"后端已收完"之前先被前端掐断。
   */
  upload: (
    projectId: string,
    formData: FormData,
    onProgress?: (percent: number) => void
  ) =>
    api.post(`/projects/${projectId}/assets/upload`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 0,
      onUploadProgress: (e) => {
        if (!onProgress || !e.total) return;
        onProgress(Math.min(99, Math.round((e.loaded / e.total) * 100)));
      },
    }),
  delete: (assetId: string) => api.delete(`/assets/${assetId}`),
  getUrl: (assetId: string) => api.get(`/assets/${assetId}/url`),
};

export default api;
