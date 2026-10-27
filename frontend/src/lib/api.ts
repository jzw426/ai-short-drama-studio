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

/**
 * 带 HTTP 状态码的接口错误。
 *
 * 为什么不能再用裸 Error：AI 类接口的错误语义完全由状态码决定
 * （429=配额用尽、503=AI 不可用、501/502=供应商不支持该能力），
 * 而 axios 只把文案塞进 detail，页面拿到 Error 后无法区分
 * "配额用尽"和"供应商不支持"，只能把原文案糊在 toast 里。
 */
export class ApiError extends Error {
  /** HTTP 状态码；网络中断/超时（无响应）时为 undefined */
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** 取接口错误的 HTTP 状态码；非接口错误（如本地抛错）返回 undefined */
export function apiStatus(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null) return undefined;
  const status = (error as { status?: unknown }).status;
  return typeof status === "number" ? status : undefined;
}

/** 取用户可读的错误文案（Error.message；空则回退 fallback） */
export function apiMessage(error: unknown, fallback = "请求失败"): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error) return error;
  return fallback;
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
    return Promise.reject(
      new ApiError(
        typeof message === "string" ? message : "请求失败",
        error.response?.status
      )
    );
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
  updateScene: (
    projectId: string,
    sceneId: string,
    data: Record<string, unknown>
  ) => api.put(`/projects/${projectId}/script/scenes/${sceneId}`, data),
  deleteScene: (projectId: string, sceneId: string) =>
    api.delete(`/projects/${projectId}/script/scenes/${sceneId}`),
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
  deleteShot: (projectId: string, shotId: string) =>
    api.delete(`/projects/${projectId}/storyboard/shots/${shotId}`),
  // 从剧本一键生成分镜（AI）
  // 每个剧本场景一次 AI 调用，整体远超默认 30s 超时
  generateFromScript: (projectId: string) =>
    api.post(`/projects/${projectId}/storyboard/generate-from-script`, undefined, {
      timeout: 330000,
    }),
  // 导出分镜（JSON）
  exportJson: (projectId: string) =>
    api.get(`/projects/${projectId}/storyboard/export`),
  /**
   * 出首帧图（M4-3）：以角色锁脸参考图 + 场景四视图为参考图生成该镜头的第一帧。
   *
   * regenerate=true 表示已有首帧、重新生成（旧图会被覆盖）。
   * 超时放宽到 600s：一次出图要串行注入多张参考图，后端单次 httpx 就要 300s，
   * 30s 默认值会让前端先断而后端仍在跑、配额已扣。
   */
  generateFirstFrame: (
    projectId: string,
    shotId: string,
    data: { regenerate?: boolean } = {}
  ) =>
    api.post(
      `/projects/${projectId}/storyboard/shots/${shotId}/first-frame`,
      { regenerate: data.regenerate ?? false },
      { timeout: 600000 }
    ),
};

// ===== 视频作业 API（M4-3） =====

/** 作业状态：pending/submitted/polling 为进行中，其余为终态 */
export type VideoJobStatus =
  | "pending"
  | "submitted"
  | "polling"
  | "completed"
  | "failed"
  | "timeout"
  | "cancelled";

/** 出首帧的响应：落库后的签名地址 + 实际使用的提示词 + 注入的角色 */
export interface FirstFrameDto {
  image_url: string;
  prompt: string;
  characters_used: string[];
}

/** 后端 VideoJobResponse（snake_case） */
export interface VideoJobDto {
  id: string;
  project_id?: string;
  shot_id?: string | null;
  status: VideoJobStatus;
  /** 成功的规范化地址（已转存自有存储） */
  video_url?: string | null;
  /** 失败原因（后端原样透出供应商报错摘要） */
  error?: string | null;
  /** 后端已轮询次数，仅用于展示/排障，前端不要据此判断超时 */
  poll_count: number;
  prompt?: string | null;
  image_url?: string | null;
  duration?: number | null;
  provider?: string;
  model?: string;
  /** 转存降级等非致命告警（第三方链接有 TTL） */
  warnings?: string | null;
  created_at: string;
  updated_at?: string;
}

/**
 * AI 视频作业（M4-3）。
 *
 * 为什么不是"一个接口等到出片"：视频供应商是异步任务制，单条片段要轮询数分钟。
 * 同步等会把前端连接和后端 worker 一起按住，还没法单独取消/重试某个镜头。
 * 这里只负责提交作业，进度由页面每 5s 调 get 轮询。
 */
export const videoJobApi = {
  /** 提交图生视频作业；image_url 传镜头当前首帧，空则退化为文生视频 */
  create: (
    projectId: string,
    shotId: string,
    data: { prompt?: string; duration?: number; image_url?: string } = {}
  ) =>
    api.post(
      `/projects/${projectId}/shots/${shotId}/video-jobs`,
      {
        ...(data.prompt ? { prompt: data.prompt } : {}),
        ...(data.duration != null ? { duration: data.duration } : {}),
        ...(data.image_url ? { image_url: data.image_url } : {}),
      },
      // 只等"提交成功"（拿到 job_id），不等待出片；供应商提交本身可能慢，放宽到 120s
      { timeout: 120000 }
    ),
  get: (projectId: string, jobId: string) =>
    api.get(`/projects/${projectId}/video-jobs/${jobId}`),
  list: (
    projectId: string,
    params?: { status?: VideoJobStatus; limit?: number }
  ) => api.get(`/projects/${projectId}/video-jobs`, { params }),
  cancel: (projectId: string, jobId: string) =>
    api.post(`/projects/${projectId}/video-jobs/${jobId}/cancel`),
};

// ===== 场景资产 API（M4-3） =====

/** 场景四视图的机位视角（不是角色的正/侧/背） */
export type SceneView = "wide" | "medium" | "close" | "establishing";
export type SceneAssetSource = "ai" | "upload";

/** 后端 SceneAssetResponse（snake_case） */
export interface SceneAssetDto {
  id: string;
  project_id?: string;
  /** 场景标识：与镜头的 scene_ref 对齐（通常是 scenes.title） */
  scene_ref: string;
  view: SceneView;
  url: string;
  source: SceneAssetSource;
  prompt?: string | null;
  created_at?: string;
}

/**
 * 场景资产（场景四视图复用池）。
 *
 * 一套场景只该有一种"长相"：同一间咖啡馆第一镜是木质暖光、第三镜变冷白水泥，
 * 观众立刻出戏。四视图把场景固化，出首帧时按 scene_ref 注入参考图。
 * 同一 (project, scene_ref, view) 只有一条，重新生成即覆盖。
 */
export const sceneAssetApi = {
  list: (projectId: string, sceneRef?: string) =>
    api.get(`/projects/${projectId}/scene-assets`, {
      params: sceneRef ? { scene_ref: sceneRef } : undefined,
    }),
  /**
   * 生成/上传某个视角。AI 出图会串行注入参考图，必须放宽超时；
   * 同一视角重复调用是覆盖语义，所以 regenerate 无需额外参数。
   */
  create: (
    projectId: string,
    data: {
      scene_ref: string;
      view: SceneView;
      source?: SceneAssetSource;
      url?: string;
      prompt?: string;
    }
  ) =>
    api.post(`/projects/${projectId}/scene-assets`, data, {
      timeout: 600000,
    }),
  remove: (projectId: string, assetId: string) =>
    api.delete(`/projects/${projectId}/scene-assets/${assetId}`),
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
  /**
   * 锁定角色形象（M4-2）：把基准图落到自有存储，并记下 seed 与外观描述。
   * 之后所有出图都走「参考图 + 同 seed」的图生图，同一个角色才不会每张脸都不一样。
   * 该接口不调用 AI、不占配额。
   */
  lockFace: (
    projectId: string,
    charId: string,
    data: { source_url?: string; seed?: number; visual_prompt?: string }
  ) => api.post(`/projects/${projectId}/characters/${charId}/lock-face`, data),
  /**
   * 生成三视图（front/side/full/back）。每个视角各消耗一次 AI 配额，
   * 服务端逐视角失败退配额、部分成功也返回已有结果。
   */
  generateViews: (
    projectId: string,
    charId: string,
    views?: string[],
    seed?: number
  ) =>
    api.post(
      `/projects/${projectId}/characters/${charId}/views`,
      {
        ...(views && views.length ? { views } : {}),
        ...(seed != null ? { seed } : {}),
      },
      { timeout: 600000 }
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
  /** dialogue = 剧本台词（正解）；description = 画面描述（历史行为，读起来像旁白） */
  subtitle_source: "dialogue" | "description" | "label" | "none";
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

/** 后端 ScriptResponse（snake_case） */
export interface SceneDto {
  id: string;
  script_id: string;
  scene_number: number;
  title: string;
  location: string;
  time_of_day: string;
  interior: boolean;
  summary: string;
  content: string;
  /** 台词：渲染烧字幕的唯一正确来源 */
  dialogue: string;
  duration: number;
  sort_order: number;
}

/** 后端 ScriptUpdate 只接受这三个字段，其余一律不发 */
export interface ScriptUpdatePayload {
  title?: string;
  content?: string;
  word_count?: number;
}

export interface ScriptDto {
  id: string;
  project_id: string;
  title: string;
  content: string;
  word_count: number;
  scenes: SceneDto[];
  ai_prompt_history?: { id: string; prompt: string; response: string; timestamp: string }[];
  created_at: string;
  updated_at: string;
}

/** 后端 AIGenerateResponse（剧本正文生成） */
export interface AIGenerateTextDto {
  generated_content: string;
  prompt: string;
  usage?: Record<string, unknown> | null;
}

/** 与后端 CharacterResponse 对齐（snake_case） */
export interface CharacterDto {
  id: string;
  project_id: string;
  name: string;
  role: string;
  description: string;
  avatar_url: string | null;
  generated_images?: string[];
  voice: string;
  age: number;
  gender: string;
  traits: string[];
  backstory: string;
  created_at?: string;
  updated_at?: string;
  /** 锁定后的基准图（自有存储签名地址）；null 表示还没锁脸 */
  reference_image_url?: string | null;
  /** 锁脸时固定的图像种子，出图时透传，保证同角色同一张脸 */
  image_seed?: number | null;
  /** 锁脸时冻结的外观描述（只留外观锚点，不含剧情） */
  visual_prompt?: string | null;
  /** 三视图：front / side / full / back → 图片地址 */
  view_images?: Record<string, string>;
}

/** 后端 ShotResponse（snake_case） */
export interface ShotDto {
  id: string;
  storyboard_id: string;
  shot_number: number;
  label: string;
  description: string;
  duration: number;
  /** 景别/角度：AI 返回中文（全景/中景/特写…），后端不限枚举 */
  camera_angle: string;
  /** 转场：AI 返回中文（硬切/淡入…），后端不限枚举 */
  transition: string;
  scene_ref?: string | null;
  character_refs: string[];
  /** 绑定的素材存储地址（canonical_url）；为空表示渲染时由 AI 生成 */
  video_url?: string | null;
  /** 首帧图（M4-3，短期签名地址）；图生视频的入参，为空才退回纯文生视频 */
  image_url?: string | null;
  /**
   * 喂给视频模型的提示词（M4-3）。与 description 分离：
   * description 是给人看的运镜描述，video_prompt 是给模型的结构化描述。
   */
  video_prompt?: string | null;
  sort_order: number;
  created_at?: string;
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
  /** 短期签名链接（只能用于展示/播放，几分钟后失效） */
  url: string;
  /**
   * 不带签名的稳定存储地址。绑定到镜头时必须存这个：
   * 把 url 存进 shots.video_url，签名过期后渲染就取不到素材了。
   */
  canonical_url?: string | null;
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
