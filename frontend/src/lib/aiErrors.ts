import { apiMessage, apiStatus } from "./api";
import type { VideoJobStatus } from "./api";

/**
 * AI 类接口的错误语义 → 一句用户能看懂的中文。
 *
 * 为什么集中在这里：后端对不同失败原因给的是状态码而不是可以直出的文案
 * （detail 往往是供应商的英文报错，用户看不懂，还可能泄露密钥片段）。
 * 页面各自拼一份字符串迟早会漂移，这里统一口径：
 *   501/502 → 供应商不支持该能力
 *   503     → AI 不可用
 *   429     → 今日配额用尽
 *   504/超时文案 → 超时，可重试
 * 其它状态码 / 网络错误 → 后端 detail 原文（不猜，避免掩盖真实问题）。
 */

function isTimeoutText(text: string): boolean {
  return /timeout|timed out|超时|ECONNABORTED|ETIMEDOUT/i.test(text);
}

/**
 * 统一映射：返回 { text, retryable }。
 * retryable=false 表示重试也不会成功（配额、供应商能力缺失），
 * 页面据此决定是否显示「重试」。
 */
export function aiErrorMessage(
  error: unknown,
  options: { unsupported: string; fallback: string }
): { text: string; retryable: boolean } {
  const status = apiStatus(error);
  const detail = apiMessage(error, options.fallback);

  if (status === 501 || status === 502) {
    return { text: options.unsupported, retryable: false };
  }
  if (status === 503) {
    return { text: "AI 不可用", retryable: true };
  }
  if (status === 429) {
    return { text: "今日配额用尽", retryable: false };
  }
  if (status === 504 || isTimeoutText(detail)) {
    return { text: "超时，可重试", retryable: true };
  }
  if (status === 401) {
    // 拦截器已跳转登录页，这里只需要一个不误导的文案
    return { text: "登录已过期，请重新登录", retryable: false };
  }
  return { text: detail, retryable: true };
}

/** 出首帧：502=供应商不支持参考图（角色图/场景图无法注入） */
export function firstFrameErrorMessage(error: unknown): string {
  return aiErrorMessage(error, {
    unsupported: "供应商不支持参考图",
    fallback: "出首帧失败",
  }).text;
}

/** 出视频：501/502=供应商不支持图生视频 */
export function videoJobErrorMessage(error: unknown): string {
  return aiErrorMessage(error, {
    unsupported: "供应商不支持图生视频",
    fallback: "生成视频失败",
  }).text;
}

/** 场景四视图：与首帧同源（参考图注入），文案按场景语境 */
export function sceneAssetErrorMessage(error: unknown): string {
  return aiErrorMessage(error, {
    unsupported: "供应商不支持参考图",
    fallback: "生成场景视图失败",
  }).text;
}

export const VIDEO_JOB_TERMINAL: readonly VideoJobStatus[] = [
  "completed",
  "failed",
  "timeout",
  "cancelled",
];

export function isVideoJobTerminal(status: VideoJobStatus): boolean {
  return VIDEO_JOB_TERMINAL.includes(status);
}

/** 作业进行中（按钮要禁用、界面显示进度） */
export function isVideoJobInflight(status: VideoJobStatus): boolean {
  return status === "pending" || status === "submitted" || status === "polling";
}

/**
 * 终态/失败态 → 展示文案。
 *
 * timeout 是后端自己判定的（作业超过供应商时限），与前端轮询上限不同；
 * 两种情况用户看到的都应该是"超时，可重试"。
 */
export function videoJobStatusText(
  status: VideoJobStatus,
  error?: string | null
): string {
  switch (status) {
    case "completed":
      return "已生成视频";
    case "cancelled":
      return "已取消";
    case "timeout":
      return "超时，可重试";
    case "failed": {
      const detail = (error ?? "").trim();
      if (!detail) return "生成失败，可重试";
      if (isTimeoutText(detail)) return "超时，可重试";
      return detail;
    }
    default:
      return "生成中";
  }
}
