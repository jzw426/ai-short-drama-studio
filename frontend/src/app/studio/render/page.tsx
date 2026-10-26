"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  Download,
  XCircle,
  RefreshCw,
  Clock,
  Loader2,
  AlertTriangle,
  Film,
} from "lucide-react";
import { RenderPanel } from "@/components/RenderPanel";
import { mediaUrl, renderApi } from "@/lib/api";
import type { RenderConfigPayload, RenderTaskDto } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useCurrentProject } from "@/lib/useCurrentProject";

const ACTIVE_STATUSES: RenderTaskDto["status"][] = ["queued", "processing"];
const POLL_INTERVAL_MS = 4000;

const statusStyles: Record<string, string> = {
  queued: "bg-surface-100 text-surface-600",
  processing: "bg-yellow-100 text-yellow-700",
  completed: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
  cancelled: "bg-surface-200 text-surface-500",
};

const statusLabels: Record<string, string> = {
  queued: "排队中",
  processing: "渲染中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export default function RenderPage() {
  const { project, loading: projectLoading, error: projectError } =
    useCurrentProject();

  const [tasks, setTasks] = useState<RenderTaskDto[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [shotCount, setShotCount] = useState<number | null>(null);
  const projectIdRef = useRef<string | null>(null);

  const selected = useMemo(
    () => tasks.find((t) => t.id === selectedId) ?? tasks[0] ?? null,
    [tasks, selectedId]
  );

  const reload = useCallback(async (projectId: string, silent = false) => {
    if (!silent) setLoading(true);
    try {
      const list = (await renderApi.list(projectId)) as unknown as RenderTaskDto[];
      const arr = Array.isArray(list) ? list : [];
      setTasks(arr);
      setError(null);
      return arr;
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载渲染任务失败");
      return [];
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  // 切换项目时重新加载 + 查询镜头数（没有镜头时渲染必然空转）
  useEffect(() => {
    if (!project) return;
    projectIdRef.current = project.id;
    void reload(project.id);
    void renderApi
      .shotCount(project.id)
      .then((n) => setShotCount(n))
      .catch(() => setShotCount(null));
  }, [project, reload]);

  // 有排队/渲染中的任务才轮询；全部结束就停，避免无意义请求
  const hasActive = tasks.some((t) => ACTIVE_STATUSES.includes(t.status));
  useEffect(() => {
    const projectId = project?.id;
    if (!projectId || !hasActive) return;
    const timer = setInterval(() => {
      if (projectIdRef.current === projectId) void reload(projectId, true);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [project?.id, hasActive, reload]);

  const handleSubmit = async (config: RenderConfigPayload) => {
    if (!project) return;
    if (!shotCount) {
      toast.error("当前项目还没有镜头，先去分镜设计生成");
      return;
    }
    setSubmitting(true);
    try {
      // 幂等键：一次点击一个 key。双击/重试/网络重发都会落回同一个任务，
      // 让"AI 视频按次计费"不会因为手抖变成三倍成本。
      const payload = {
        name: `${project.title}·${new Date().toLocaleString("zh-CN", { hour12: false })}`,
        config,
        idempotency_key:
          typeof crypto !== "undefined" && "randomUUID" in crypto
            ? crypto.randomUUID()
            : `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      };
      const created = (await renderApi.submit(
        project.id,
        payload
      )) as unknown as RenderTaskDto;
      toast.success("渲染任务已提交，可在左侧跟踪进度");
      const arr = await reload(project.id);
      if (created?.id) setSelectedId(created.id);
      else if (arr.length) setSelectedId(arr[0].id);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "提交渲染失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async (task: RenderTaskDto) => {
    if (!window.confirm(`确认取消任务「${task.name}」？\n已生成的部分会被保留，不会重新扣费。`))
      return;
    try {
      await renderApi.cancel(task.id);
      toast.success("已请求取消");
      if (project) await reload(project.id, true);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "取消失败");
    }
  };

  const handleDownload = async (task: RenderTaskDto) => {
    try {
      const res = (await renderApi.download(task.id)) as unknown as {
        download_url?: string;
      };
      const url = mediaUrl(res?.download_url ?? task.output_url);
      if (!url) {
        toast.error("下载地址为空");
        return;
      }
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "获取下载地址失败");
    }
  };

  // ---- 无项目 ----
  if (!project) {
    return (
      <div className="max-w-3xl mx-auto mt-20 card p-10 text-center space-y-4">
        <Film size={40} className="mx-auto text-surface-300" />
        <h2 className="text-lg font-semibold text-surface-800">还没有选中项目</h2>
        <p className="text-sm text-surface-500">
          {projectLoading
            ? "正在加载项目列表…"
            : projectError
            ? projectError
            : "先在首页新建或选择一个项目，再回来渲染。"}
        </p>
        <Link href="/" className="btn-primary inline-flex items-center gap-2">
          去选择项目
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">一键成片</h1>
          <p className="text-surface-500 mt-1">
            {project.title} · 渲染任务与产物下载
            {shotCount !== null && ` · ${shotCount} 个镜头`}
          </p>
        </div>
        <button
          onClick={() => void reload(project.id)}
          disabled={loading}
          className="btn-outline flex items-center gap-2 disabled:opacity-60"
        >
          <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          刷新
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* 左侧：任务列表 */}
        <div className="lg:col-span-1 space-y-3">
          <h3 className="font-medium text-surface-700">
            渲染任务
            {tasks.length > 0 && (
              <span className="text-xs text-surface-400 font-normal ml-2">
                共 {tasks.length} 个
              </span>
            )}
          </h3>

          {loading && tasks.length === 0 ? (
            <div className="flex items-center gap-2 text-sm text-surface-400 p-3">
              <Loader2 size={14} className="animate-spin" />
              加载中…
            </div>
          ) : tasks.length === 0 ? (
            <div className="text-sm text-surface-400 p-3 border border-dashed rounded-lg">
              还没有渲染任务。配置好参数后点「确认并开始渲染」。
            </div>
          ) : (
            <div className="space-y-2">
              {tasks.map((task) => (
                <div
                  key={task.id}
                  onClick={() => setSelectedId(task.id)}
                  className={`p-3 rounded-lg cursor-pointer border transition-all ${
                    selected?.id === task.id
                      ? "border-primary-500 bg-primary-50"
                      : "border-surface-200 hover:border-surface-300 bg-white"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-surface-800 truncate">
                      {task.name}
                    </span>
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full flex-shrink-0 ${
                        statusStyles[task.status] ?? statusStyles.queued
                      }`}
                    >
                      {statusLabels[task.status] ?? task.status}
                    </span>
                  </div>
                  <div className="mt-2 w-full h-1.5 bg-surface-200 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-700 ${
                        task.status === "failed"
                          ? "bg-red-500"
                          : task.status === "completed"
                          ? "bg-green-500"
                          : task.status === "cancelled"
                          ? "bg-surface-400"
                          : "bg-primary-500"
                      }`}
                      style={{ width: `${Math.min(100, Math.max(0, task.progress || 0))}%` }}
                    />
                  </div>
                  <p className="text-xs text-surface-400 mt-1.5">
                    {Math.round(task.progress || 0)}% ·{" "}
                    {formatDateTime(task.created_at)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 右侧：预览 + 配置 */}
        <div className="lg:col-span-3 space-y-4">
          <div className="card overflow-hidden">
            <div className="aspect-video bg-surface-900 flex items-center justify-center relative">
              {!selected ? (
                <div className="text-center text-surface-400">
                  <Film size={40} className="mx-auto mb-2 opacity-50" />
                  <p className="text-sm">选择左侧任务查看详情</p>
                </div>
              ) : selected.status === "completed" && selected.output_url ? (
                <video
                  key={selected.id}
                  controls
                  preload="metadata"
                  className="w-full h-full object-contain bg-black"
                  src={mediaUrl(selected.output_url)}
                >
                  你的浏览器不支持 video 标签。
                </video>
              ) : selected.status === "processing" ||
                selected.status === "queued" ? (
                <div className="text-center">
                  <div className="w-16 h-16 border-4 border-primary-500 border-t-transparent rounded-full animate-spin mx-auto" />
                  <p className="text-surface-300 mt-4">
                    {selected.status === "queued" ? "排队中…" : "正在渲染…"}{" "}
                    {Math.round(selected.progress || 0)}%
                  </p>
                  <button
                    onClick={() => void handleCancel(selected)}
                    className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-white/10 hover:bg-white/20 text-white rounded-lg text-sm"
                  >
                    <XCircle size={14} />
                    {selected.cancel_requested ? "已请求取消，等待 worker 收尾" : "取消渲染"}
                  </button>
                </div>
              ) : selected.status === "failed" ? (
                <div className="text-center px-6">
                  <AlertTriangle size={36} className="mx-auto text-red-400" />
                  <p className="text-red-400 text-lg mt-2">渲染失败</p>
                  <p className="text-surface-400 text-sm mt-2 max-w-lg mx-auto break-words">
                    {selected.error_message || "未返回错误信息"}
                  </p>
                </div>
              ) : selected.status === "cancelled" ? (
                <div className="text-center">
                  <XCircle size={36} className="mx-auto text-surface-400" />
                  <p className="text-surface-300 mt-2">任务已取消</p>
                  <p className="text-xs text-surface-500 mt-1">
                    已生成的分镜片段保留在任务记录中，重新渲染可复用
                  </p>
                </div>
              ) : (
                <div className="text-center">
                  <Clock size={28} className="mx-auto text-surface-400" />
                  <p className="text-surface-400 mt-2">状态未知：{selected.status}</p>
                </div>
              )}
            </div>

            {selected && (
              <div className="px-4 py-3 flex items-center justify-between flex-wrap gap-2 border-t border-surface-100">
                <div className="text-xs text-surface-500">
                  任务 {selected.id.slice(0, 8)} · 创建于{" "}
                  {formatDateTime(selected.created_at)}
                  {selected.end_time && ` · 完成于 ${formatDateTime(selected.end_time)}`}
                  {selected.duration ? ` · 耗时 ${Math.round(selected.duration)}s` : ""}
                </div>
                {selected.status === "completed" && selected.output_url && (
                  <button
                    onClick={() => void handleDownload(selected)}
                    className="btn-outline flex items-center gap-2 text-sm"
                  >
                    <Download size={14} />
                    下载视频
                  </button>
                )}
              </div>
            )}
          </div>

          <RenderPanel
            onSubmit={handleSubmit}
            submitting={submitting}
            disabled={!shotCount}
            shotCount={shotCount}
          />
        </div>
      </div>
    </div>
  );
}
