"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Images, Loader2, RefreshCw, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import {
  mediaUrl,
  sceneAssetApi,
  type SceneAssetDto,
  type SceneView,
} from "@/lib/api";
import { aiErrorMessage, sceneAssetErrorMessage } from "@/lib/aiErrors";

/**
 * 场景四视图的机位定义。
 *
 * 注意：场景的"四视图"是**机位**（同一场景从四个距离看），不是角色的正/侧/背。
 * 目的是把"这个场景长什么样"固化：同一间咖啡馆在第一镜木质暖光、
 * 第三镜冷白水泥，观众立刻出戏。
 */
const SCENE_VIEWS: { key: SceneView; label: string; hint: string }[] = [
  { key: "wide", label: "全景", hint: "交代空间关系" },
  { key: "medium", label: "中景", hint: "人物走位" },
  { key: "close", label: "特写", hint: "情绪 / 道具" },
  { key: "establishing", label: "定场", hint: "开场第一印象" },
];

interface Props {
  projectId: string;
  /**
   * 场景标识：与镜头的 scene_ref 对齐（通常是场景标题）。
   * 由调用方决定取值（ScriptEditor 用 scene.title 原样 trim，和后端
   * generate-from-script 的 scene_ref=scene.title 保持一致），这里只负责
   * 落库与展示，避免两边各写一套规则。
   */
  sceneRef: string;
  sceneNumber: number;
  sceneTitle?: string;
  onClose: () => void;
  /** 视图有增删后通知父级（父级目前不需要，保留给后续联动） */
  onChanged?: () => void;
}

/**
 * 场景四视图面板（M4-3）。
 *
 * 交互模型：
 *   - 已生成的视角直接显示图片，可单张删除/重生成（同一镜头视角是覆盖语义）；
 *   - 没生成的视角选中后点「生成所选视角」批量出图；
 *   - 请求是**串行**的：一个视角一次 AI 调用，并发会打满配额与供应商限流，
 *     而且失败时无法定位到底是哪个视角出的问题。
 */
export function SceneAssetPanel({
  projectId,
  sceneRef,
  sceneNumber,
  sceneTitle,
  onClose,
  onChanged,
}: Props) {
  const [assets, setAssets] = useState<SceneAssetDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selection, setSelection] = useState<SceneView[]>(["wide", "medium"]);
  const [generating, setGenerating] = useState(false);
  const [deletingView, setDeletingView] = useState<SceneView | null>(null);

  const ref = sceneRef.trim();

  const load = useCallback(async () => {
    if (!ref) {
      setAssets([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const rows = (await sceneAssetApi.list(projectId, ref)) as unknown as
        | SceneAssetDto[]
        | null;
      setAssets(Array.isArray(rows) ? rows : []);
    } catch (e) {
      setError(sceneAssetErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [projectId, ref]);

  useEffect(() => {
    void load();
  }, [load]);

  // 关闭时按 Esc（弹窗的基本预期，少一次找叉号）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const byView = useMemo(() => {
    const map = new Map<SceneView, SceneAssetDto>();
    for (const asset of assets) map.set(asset.view, asset);
    return map;
  }, [assets]);

  const toggleView = (view: SceneView) => {
    setSelection((prev) =>
      prev.includes(view) ? prev.filter((v) => v !== view) : [...prev, view]
    );
  };

  const handleGenerate = async () => {
    if (generating) return;
    if (!ref) {
      toast.error("场景还没有标题，无法确定场景标识");
      return;
    }
    if (selection.length === 0) {
      toast.error("至少选择一个视角");
      return;
    }
    setGenerating(true);
    const loadingId = toast.loading(
      `正在生成 ${selection.length} 个场景视角…`
    );
    // 逐个记账：失败时前面的视角可能已经出图并扣过配额，必须如实告诉用户
    const doneViews: SceneView[] = [];
    try {
      for (const view of selection) {
        // 串行：一次一个视角，后端每次都要注入参考图，并发只会互相拖慢、
        // 还容易触发供应商限流，而且失败时分不清是哪个视角出的问题
        await sceneAssetApi.create(projectId, {
          scene_ref: ref,
          view,
          source: "ai",
        });
        doneViews.push(view);
      }
      toast.success(`已生成 ${doneViews.length} 个视角`, { id: loadingId });
      onChanged?.();
    } catch (e) {
      // 配额用尽 / 供应商不支持时剩下的视角注定失败，循环已随异常中断，
      // 这里只要把「成功几个 + 为什么失败」一次说清。
      const { text } = aiErrorMessage(e, {
        unsupported: "供应商不支持参考图",
        fallback: "生成场景视图失败",
      });
      toast.error(
        doneViews.length > 0
          ? `已生成 ${doneViews.length} 个视角，其余失败：${text}`
          : text,
        { id: loadingId }
      );
    } finally {
      // 成功的视角从选中里摘掉：再点「生成所选视角」只重试没成的，
      // 否则用户一按就把已生成（已付费）的图又买一遍。
      if (doneViews.length > 0) {
        setSelection((prev) => prev.filter((v) => !doneViews.includes(v)));
      }
      await load();
      setGenerating(false);
    }
  };

  const handleDelete = async (asset: SceneAssetDto) => {
    if (deletingView) return;
    if (!window.confirm(`确定删除「${viewLabel(asset.view)}」视角？`)) return;
    setDeletingView(asset.view);
    try {
      await sceneAssetApi.remove(projectId, asset.id);
      setAssets((prev) => prev.filter((a) => a.id !== asset.id));
      onChanged?.();
      toast.success("场景视角已删除");
    } catch (e) {
      toast.error(sceneAssetErrorMessage(e));
    } finally {
      setDeletingView(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="card w-full max-w-3xl max-h-[90vh] overflow-y-auto p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 font-semibold text-surface-800">
              <Images size={18} className="text-primary-600" />
              场景 {sceneNumber} 四视图
              {sceneTitle ? (
                <span className="truncate text-surface-500">· {sceneTitle}</span>
              ) : null}
            </h2>
            <p className="mt-1 text-xs text-surface-400">
              场景标识：<span className="font-mono">{ref || "（空）"}</span>
              · 镜头「关联场景」填同一个标识时，出首帧会复用这里的参考图
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md hover:bg-surface-100 text-surface-400"
            title="关闭"
          >
            <X size={16} />
          </button>
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            <span className="flex-1">{error}</span>
            <button onClick={() => void load()} className="text-xs underline">
              重试
            </button>
          </div>
        )}

        {!ref && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700">
            这个场景还没有标题。请先在场景编辑里填写「场景标题」——
            它同时是镜头 scene_ref 的匹配依据，没有标识的视图无法被出首帧复用。
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {SCENE_VIEWS.map((view) => {
            const asset = byView.get(view.key);
            const selected = selection.includes(view.key);
            const deleting = deletingView === view.key;
            return (
              <div key={view.key} className="space-y-1">
                <div
                  className={`group relative aspect-video overflow-hidden rounded-md border bg-surface-100 ${
                    selected ? "border-primary-300 ring-1 ring-primary-200" : "border-surface-200"
                  }`}
                >
                  {asset?.url ? (
                    <img
                      src={mediaUrl(asset.url)}
                      alt={`场景 ${sceneNumber} ${view.label}`}
                      className="h-full w-full object-cover"
                      loading="lazy"
                    />
                  ) : (
                    <span className="flex h-full w-full items-center justify-center text-[11px] text-surface-400">
                      {loading ? "加载中…" : "未生成"}
                    </span>
                  )}
                  {asset?.url && (
                    <button
                      onClick={() => void handleDelete(asset)}
                      disabled={deleting || generating}
                      title={`删除${view.label}`}
                      className="absolute right-1 top-1 rounded bg-black/50 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100 disabled:opacity-50"
                    >
                      {deleting ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <Trash2 size={12} />
                      )}
                    </button>
                  )}
                </div>
                <button
                  onClick={() => toggleView(view.key)}
                  className={`w-full rounded border px-1.5 py-1 text-left text-[11px] ${
                    selected
                      ? "border-primary-300 bg-primary-50 text-primary-700"
                      : "border-surface-200 text-surface-500"
                  }`}
                >
                  <span className="font-medium">{view.label}</span>
                  <span className="ml-1 text-surface-400">{view.hint}</span>
                </button>
              </div>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-surface-100 pt-3">
          <p className="text-xs text-surface-400">
            已选 {selection.length} 个视角 · 每个视角一次 AI 调用（消耗配额）
            {assets.length > 0 ? ` · 已生成 ${assets.length}/4` : ""}
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => void load()}
              disabled={loading}
              className="btn-outline flex items-center gap-1.5 text-sm disabled:opacity-60"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
              刷新
            </button>
            <button
              onClick={() => void handleGenerate()}
              disabled={generating || !ref || selection.length === 0}
              className="btn-primary flex items-center gap-2 text-sm disabled:opacity-60"
            >
              {generating ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Images size={14} />
              )}
              {generating ? "生成中…" : "生成所选视角"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function viewLabel(view: SceneView): string {
  return SCENE_VIEWS.find((v) => v.key === view)?.label ?? view;
}
