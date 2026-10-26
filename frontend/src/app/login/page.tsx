"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Clapperboard, Loader2 } from "lucide-react";
import { authApi } from "@/lib/api";
import { setAuth } from "@/lib/auth";

type Mode = "login" | "register";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    username: "",
    email: "",
    password: "",
    display_name: "",
  });

  const setField = useCallback(
    (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm((f) => ({ ...f, [key]: e.target.value })),
    []
  );

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!form.username || !form.password) {
        toast.error("请填写用户名和密码");
        return;
      }
      if (mode === "register" && form.password.length < 6) {
        toast.error("密码至少 6 位");
        return;
      }
      setLoading(true);
      try {
        const res = (await (mode === "login"
          ? authApi.login({ username: form.username, password: form.password })
          : authApi.register({
              username: form.username,
              email: form.email || `${form.username}@local.dev`,
              password: form.password,
              display_name: form.display_name,
            }))) as unknown as { access_token: string; user: { id: string; username: string; email: string; display_name: string } };

        // Token 由后端下发 httpOnly Cookie（setAuth 仅保存用户信息）
        setAuth(res.user);
        toast.success(mode === "login" ? "欢迎回来" : "注册成功，已自动登录");
        router.replace("/studio");
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "操作失败，请重试");
      } finally {
        setLoading(false);
      }
    },
    [form, mode, router]
  );

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-50 p-4">
      <div className="w-full max-w-md">
        {/* Logo 区 */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-primary-600 flex items-center justify-center shadow-lg shadow-primary-600/20 mb-4">
            <Clapperboard size={28} className="text-white" />
          </div>
          <h1 className="text-2xl font-bold text-surface-900">AI Short Drama Studio</h1>
          <p className="text-sm text-surface-500 mt-1">
            剧本工坊 · 分镜设计 · 一键成片
          </p>
        </div>

        {/* 卡片 */}
        <div className="bg-white rounded-2xl border border-surface-200 shadow-sm p-8">
          {/* Tab 切换 */}
          <div className="grid grid-cols-2 gap-1 bg-surface-100 p-1 rounded-lg mb-6">
            <button
              type="button"
              onClick={() => setMode("login")}
              className={`py-2 text-sm font-medium rounded-md transition-colors ${
                mode === "login"
                  ? "bg-white text-primary-700 shadow-sm"
                  : "text-surface-500 hover:text-surface-700"
              }`}
            >
              登录
            </button>
            <button
              type="button"
              onClick={() => setMode("register")}
              className={`py-2 text-sm font-medium rounded-md transition-colors ${
                mode === "register"
                  ? "bg-white text-primary-700 shadow-sm"
                  : "text-surface-500 hover:text-surface-700"
              }`}
            >
              注册
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm text-surface-600 mb-1.5">用户名</label>
              <input
                value={form.username}
                onChange={setField("username")}
                placeholder="请输入用户名"
                autoComplete="username"
                className="w-full px-3 py-2 text-sm border border-surface-200 rounded-lg bg-surface-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              />
            </div>

            {mode === "register" && (
              <>
                <div>
                  <label className="block text-sm text-surface-600 mb-1.5">邮箱（可选）</label>
                  <input
                    type="email"
                    value={form.email}
                    onChange={setField("email")}
                    placeholder="name@example.com"
                    autoComplete="email"
                    className="w-full px-3 py-2 text-sm border border-surface-200 rounded-lg bg-surface-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  />
                </div>
                <div>
                  <label className="block text-sm text-surface-600 mb-1.5">昵称（可选）</label>
                  <input
                    value={form.display_name}
                    onChange={setField("display_name")}
                    placeholder="展示昵称"
                    className="w-full px-3 py-2 text-sm border border-surface-200 rounded-lg bg-surface-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  />
                </div>
              </>
            )}

            <div>
              <label className="block text-sm text-surface-600 mb-1.5">密码</label>
              <input
                type="password"
                value={form.password}
                onChange={setField("password")}
                placeholder={mode === "register" ? "至少 6 位" : "请输入密码"}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                className="w-full px-3 py-2 text-sm border border-surface-200 rounded-lg bg-surface-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full btn-primary py-2.5 text-sm flex items-center justify-center gap-2 disabled:opacity-60"
            >
              {loading && <Loader2 size={15} className="animate-spin" />}
              {mode === "login" ? "登录" : "注册并登录"}
            </button>
          </form>

          <p className="text-[11px] text-surface-400 mt-5 text-center leading-relaxed">
            登录即代表同意本地部署使用条款。数据保存在你自己的服务器。
          </p>
        </div>
      </div>
    </div>
  );
}
