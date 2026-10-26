"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Link2, Link2Off, Film, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { assetApi, storyboardApi } from "@/lib/api";
import type { AssetDto } from "@/lib/api";

export interface ShotDto {
  id: string;
  shot_number: number;
  label: string;
  description: string;
  duration: number;
  video_url?: string | null;
}

interface Props {
  projectId: string;
  /** 绑定变化后通知父级刷新镜头计数/素材列表 */
  onChanged?: () => void;
}

/**
 * 镜头素材绑定面板（M2）。
 *
 * 为什么需要：渲染链路的素材来源优先级是「镜头绑定的 video_url > AI 生成」。
 * 后端渲染不再造假数据，未绑定且 AI 不可用时任务会直接失败（并说明原因），
 * 所以必须给用户一个地方把已上传的片段挂到具体镜头上。
 *
 * 存的是素材的 **canonical_url**（不带签名），不是列表里那个短期签名地址：
 * 签名会过期，存进 shots.video_url 之后渲染时必然取不到素材。
 */
export function ShotBindingPanel({ projectId, onChanged }: Props) {
  const [shots, setShots] = useState<ShotDto[]>([]);
  const [assets, setAssets] = useState<AssetDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [savingId, setSavingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [shotRows, assetRows] = await Promise.all([
        storyboardApi.listShots(projectId),
        assetApi.list(projectId, { asset_type: "video" }),
      ]);
      setShots(Array.isArray(shotRows) ? (shotRows as ShotDto[]) : []);
      setAssets(Array.isArray(assetRows) ? (assetRows as AssetDto[]) : []);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "加载镜头/素材失败");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const bind = async (shot: ShotDto, canonicalUrl: string | null) => {
    setSavingId(shot.id);
    try {
      await storyboardApi.updateShot(projectId, shot.id, {
        video_url: canonicalUrl,
      });
      setShots((prev) =>
        prev.map((s) =>
          s.id === shot.id ? { ...s, video_url: canonicalUrl } : s
        )
      );
      toast.success(canonicalUrl ? "已绑定素材" : "已改为 AI 生成");
      onChanged?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "绑定失败");
    } finally {
      setSavingId(null);
    }
  };

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Link2 size={18} className="text-surface-500" />
          <h3 className="font-semibold text-surface-700">镜头素材绑定</h3>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="btn-outline flex items-center gap-2 text-sm disabled:opacity-60"
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          刷新
        </button>
      </div>

      <p className="text-xs text-surface-400">
        已绑定素材的镜头直接使用该片段；未绑定的镜头在渲染时调用 AI 生成
        （AI 不可用会失败并说明原因，不会用占位画面糊过去）。
      </p>

      {loading && shots.length === 0 ? (
        <div className="flex items-center gap-2 text-sm text-surface-400">
          <Loader2 size={14} className="animate-spin" />
          加载中…
        </div>
      ) : shots.length === 0 ? (
        <div className="text-sm text-surface-400 border border-dashed rounded-lg p-4">
          当前项目还没有镜头。先在「分镜设计」里生成镜头，再回来绑定素材。
        </div>
      ) : (
        <div className="space-y-2">
          {shots.map((shot) => {
            const boundUrl = shot.video_url || "";
            const saving = savingId === shot.id;
            return (
              <div
                key={shot.id}
                className="flex flex-col sm:flex-row sm:items-center gap-2 p-3 rounded-lg border border-surface-200 bg-white"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs px-1.5 py-0.5 rounded bg-surface-100 text-surface-600">
                      #{shot.shot_number}
                    </span>
                    <span className="text-sm font-medium text-surface-800 truncate">
                      {shot.label || "未命名镜头"}
                    </span>
                    {shot.duration ? (
                      <span className="text-xs text-surface-400">
                        {shot.duration}s
                      </span>
                    ) : null}
                  </div>
                  <p className="text-xs text-surface-400 mt-1 truncate">
                    {boundUrl ? (
                      <span className="text-green-600">
                        已绑定：{boundUrl.split("/").pop()}
                      </span>
                    ) : (
                      <span>未绑定 · 渲染时由 AI 生成</span>
                    )}
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <select
                    value={boundUrl}
                    disabled={saving}
                    onChange={(e) => {
                      const val = e.target.value;
                      if (!val) {
                        void bind(shot, null);
                        return;
                      }
                      const asset = assets.find(
                        (a) => (a.canonical_url || a.url) === val
                      );
                      void bind(shot, asset?.canonical_url || val);
                    }}
                    className="input-field max-w-[240px] text-sm"
                  >
                    <option value="">AI 生成（不绑定）</option>
                    {assets.map((a) => (
                      <option key={a.id} value={a.canonical_url || a.url}>
                        {a.name}
                        {a.size ? ` · ${(a.size / 1024 / 1024).toFixed(1)}MB` : ""}
                      </option>
                    ))}
                  </select>
                  {boundUrl && (
                    <button
                      type="button"
                      onClick={() => void bind(shot, null)}
                      disabled={saving}
                      title="解除绑定，改为 AI 生成"
                      className="p-2 rounded-lg border border-surface-200 text-surface-500 hover:text-surface-800 disabled:opacity-50"
                    >
                      {saving ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <Link2Off size={14} />
                      )}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {assets.length === 0 && shots.length > 0 && (
        <p className="text-xs text-surface-400 flex items-center gap-1">
          <Film size={12} />
          还没有视频素材：在「素材库」上传片段后才能绑定。
        </p>
      )}
    </div>
  );
}
