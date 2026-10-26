"use client";

// 认证状态存取
// 安全升级（v0.2）：Token 不再写入 localStorage，改为后端下发的 httpOnly Cookie
// （XSS 无法读取）；本地仅保留用户信息用于 UI 展示，会话有效性由 Cookie 维持。

export interface AuthUser {
  id: string;
  username: string;
  email: string;
  display_name: string;
}

const USER_KEY = "ai_drama_user";

/** Token 仅存于 httpOnly Cookie，由浏览器自动携带；此处始终返回 null */
export function getToken(): string | null {
  return null;
}

export function setAuth(user: AuthUser): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function clearAuth(): void {
  localStorage.removeItem(USER_KEY);
}

export function isAuthenticated(): boolean {
  return !!getUser();
}
