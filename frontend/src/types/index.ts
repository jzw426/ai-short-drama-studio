// ===== 基础类型 =====

export interface Project {
  id: string;
  title: string;
  description: string;
  status: "draft" | "editing" | "rendering" | "completed";
  progress: number;
  thumbnail?: string;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreate {
  title: string;
  description: string;
}

// ===== 剧本类型 =====

export interface Script {
  id: string;
  projectId: string;
  title: string;
  content: string;
  wordCount: number;
  scenes: Scene[];
  aiPromptHistory: AIPrompt[];
  created_at: string;
  updated_at: string;
}

export interface Scene {
  id: string;
  scriptId: string;
  sceneNumber: number;
  title: string;
  location: string;
  timeOfDay: "morning" | "afternoon" | "evening" | "night";
  interior: boolean;
  summary: string;
  content: string;
  duration: number;
  sortOrder: number;
}

export interface AIPrompt {
  prompt: string;
  response: string;
  timestamp: string;
}

// ===== 分镜类型 =====

export interface Storyboard {
  id: string;
  projectId: string;
  canvasState: string; // JSON string of Fabric.js canvas state
  shots: Shot[];
  created_at: string;
  updated_at: string;
}

export interface Shot {
  id: string;
  storyboardId: string;
  shotNumber: number;
  label: string;
  description: string;
  duration: number; // seconds
  cameraAngle: string;
  transition: string;
  sceneRef?: string;
  characterRefs: string[];
  sortOrder: number;
  created_at: string;
}

// ===== 角色类型 =====

export interface Character {
  id: string;
  projectId: string;
  name: string;
  role: "protagonist" | "antagonist" | "supporting" | "extra";
  description: string;
  avatarUrl?: string;
  generatedImages: string[];
  voice: string;
  age: number;
  gender: "male" | "female" | "other";
  traits: string[];
  backstory: string;
  created_at: string;
  updated_at: string;
}

export interface CharacterCreate {
  name: string;
  role: Character["role"];
  description: string;
  voice: string;
  age: number;
  gender: Character["gender"];
  traits: string[];
  backstory: string;
}

// ===== 渲染类型 =====

export interface RenderTask {
  id: string;
  projectId: string;
  name: string;
  status: "queued" | "processing" | "completed" | "failed";
  progress: number;
  config: RenderConfig;
  outputUrl?: string;
  errorMessage?: string;
  startTime?: string;
  endTime?: string;
  duration?: number;
  created_at: string;
}

export interface RenderConfig {
  resolution: "1280x720" | "1920x1080" | "2560x1440";
  aspectRatio: "9:16" | "16:9" | "1:1";
  fps: 24 | 30 | 60;
  visualStyle: string;
  addSubtitles: boolean;
  addBGM: boolean;
  bgmSource?: string;
  quality: "standard" | "high" | "ultra";
  aiModel: "kling" | "seedance";
}

// ===== 素材类型 =====

export interface Asset {
  id: string;
  projectId: string;
  name: string;
  type: "image" | "audio" | "video";
  mimeType: string;
  size: number;
  url: string;
  thumbnailUrl?: string;
  tags: string[];
  duration?: number; // audio/video only
  width?: number; // image/video only
  height?: number;
  uploadedAt: string;
}

export interface AssetUploadResponse {
  assetId: string;
  url: string;
  thumbnailUrl?: string;
}

// ===== API 通用响应类型 =====

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

export interface ApiError {
  detail: string;
  code?: string;
  field?: string;
}
