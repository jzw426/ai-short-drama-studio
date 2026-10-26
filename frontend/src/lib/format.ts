// 展示层格式化工具（前端只做展示，不做业务判断）

/**
 * 解析后端时间字符串。
 *
 * 后端所有时间都是 **naive UTC**（不带时区后缀，见 backend/app/core/time_utils.py），
 * 而 JS 的 `new Date("2026-10-26T12:00:00")` 会按**本地时区**解析 —— 直接用会整体偏 8 小时。
 * 这里对无时区后缀的字符串补 "Z"，确保按 UTC 解释后再本地化展示。
 */
export function parseServerTime(value?: string | null): Date | null {
  if (!value) return null;
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value);
  const date = new Date(hasZone ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value?: string | null): string {
  const date = parseServerTime(value);
  if (!date) return "—";
  return date.toLocaleString("zh-CN", { hour12: false });
}

export function formatBytes(size?: number | null): string {
  const n = Number(size ?? 0);
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  if (n >= 1024 * 1024 * 1024) return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}
