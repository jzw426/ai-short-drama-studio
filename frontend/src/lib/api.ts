import axios from "axios";
import { clearAuth } from "./auth";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  // 携带 httpOnly 会话 Cookie（安全升级：Token 不再存 localStorage）
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

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
  aiGenerate: (projectId: string, prompt: string) =>
    api.post(`/projects/${projectId}/script/ai-generate`, { prompt }),
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
    api.post(`/projects/${projectId}/characters/ai-generate`, { description }),
  // 为已有角色追加生成形象图
  generateImage: (projectId: string, charId: string) =>
    api.post(`/projects/${projectId}/characters/${charId}/generate-image`),
};

// ===== 渲染 API =====
export const renderApi = {
  submit: (projectId: string, config: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/render`, config),
  status: (taskId: string) => api.get(`/render/${taskId}/status`),
  list: (projectId: string) =>
    api.get(`/projects/${projectId}/render/tasks`),
  cancel: (taskId: string) => api.post(`/render/${taskId}/cancel`),
  download: (taskId: string) => api.get(`/render/${taskId}/download`),
};

// ===== 素材 API =====
export const assetApi = {
  list: (projectId: string) =>
    api.get(`/projects/${projectId}/assets`),
  upload: (projectId: string, formData: FormData) =>
    api.post(`/projects/${projectId}/assets/upload`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    }),
  delete: (assetId: string) => api.delete(`/assets/${assetId}`),
  getUrl: (assetId: string) => api.get(`/assets/${assetId}/url`),
};

export default api;
