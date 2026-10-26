"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronUp,
  Clapperboard,
  Download,
  Film,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { StoryboardCanvas } from "@/components/StoryboardCanvas";
import {
  assetApi,
  scriptApi,
  storyboardApi,
  type AssetDto,
  type ShotDto,
} from "@/lib/api";
import { CAMERA_ANGLE_SUGGESTIONS, TRANSITION_SUGGESTIONS } from "@/lib/labels";
import { useCurrentProject } from "@/lib/useCurrentProject";

interface ShotDraft {
  label: string;
  description: string;
  duration: string;
  camera_angle: string;
  transition: string;
  scene_ref: string;
  character_refs: string;
  video_url: string;
}

function toDraft(shot: ShotDto): ShotDraft {
  return {
    label: shot.label ?? "",
    description: shot.description ?? "",
    duration: String(shot.duration ?? 3),
    camera_angle: shot.camera_angle || "中景",
    transition: shot.transition || "硬切",
    scene_ref: shot.scene_ref ?? "",
    character_refs: (shot.character_refs ?? []).join("、"),
    video_url: shot.video_url ?? "",
  };
}

function parseList(raw: string): string[] {
  return raw
    .split(/[,，、\s]+/)
    .map((t) => t.trim())
    .filter(Boolean);
}

function sortShots(shots: ShotDto[]): ShotDto[] {
  return [...shots].sort(
    (a, b) => a.sort_order - b.sort_order || a.shot_number - b.shot_number
  );
}

export default function StoryboardPage() {
  const { project, loading: projectLoading, error: projectError } = useCurrentProject();
  const projectId = project?.id ?? null;

  const [shots, setShots] = useState<ShotDto[]>([]);
  const [sceneCount, setSceneCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ShotDraft | null>(null);
  const [savingShot, setSavingShot] = useState(false);
  const [creatingShot, setCreatingShot] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [moving, setMoving] = useState(false);

  const [generating, setGenerating] = useState(false);
  const [exporting, setExporting] = useState(false);

  const [videoAssets, setVideoAssets] = useState<AssetDto[] | null>(null);
  const [assetsLoading, setAssetsLoading] = useState(false);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const [rawShots, rawScenes] = await Promise.all([
        storyboardApi.listShots(projectId),
        scriptApi.listScenes(projectId).catch(() => [] as unknown[]),
      ]);
      setShots(sortShots((rawShots as unknown as ShotDto[]) ?? []));
      setSceneCount(Array.isArray(rawScenes) ? rawScenes.length : 0);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "加载分镜失败";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (projectId) void load();
    else {
      setShots([]);
      setError(null);
    }
  }, [projectId, load]);

  // 打开镜头编辑时才拉取可绑定的视频素材
  const ensureVideoAssets = useCallback(async () => {
    if (!projectId || videoAssets !== null || assetsLoading) return;
    setAssetsLoading(true);
    try {
      const data = (await assetApi.list(projectId, {
        asset_type: "video",
      })) as unknown as AssetDto[];
      setVideoAssets(Array.isArray(data) ? data : []);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "加载视频素材失败");
      setVideoAssets([]);
    } finally {
      setAssetsLoading(false);
    }
  }, [projectId, videoAssets, assetsLoading]);

  const openEditor = (shot: ShotDto) => {
    setEditingId(shot.id);
    setDraft(toDraft(shot));
    void ensureVideoAssets();
  };

  const closeEditor = () => {
    if (savingShot) return;
    setEditingId(null);
    setDraft(null);
  };

  const handleSaveShot = async () => {
    if (!projectId || !editingId || !draft || savingShot) return;
    setSavingShot(true);
    try {
      await storyboardApi.updateShot(projectId, editingId, {
        label: draft.label.trim(),
        description: draft.description.trim(),
        duration: Math.max(0, Number(draft.duration) || 0),
        camera_angle: draft.camera_angle.trim(),
        transition: draft.transition.trim(),
        scene_ref: draft.scene_ref.trim() || null,
        character_refs: parseList(draft.character_refs),
        video_url: draft.video_url.trim() || null,
      });
      toast.success("镜头已保存");
      setEditingId(null);
      setDraft(null);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存镜头失败");
    } finally {
      setSavingShot(false);
    }
  };

  const handleAddShot = async () => {
    if (!projectId || creatingShot) return;
    setCreatingShot(true);
    try {
      const nextNumber =
        shots.reduce((max, s) => Math.max(max, s.shot_number), 0) + 1;
      const created = (await storyboardApi.createShot(projectId, {
        shot_number: nextNumber,
        label: `镜头 ${nextNumber}`,
        description: "",
        duration: 3,
        camera_angle: "中景",
        transition: "硬切",
        scene_ref: null,
        character_refs: [],
        video_url: null,
        sort_order: shots.length,
      })) as unknown as ShotDto;
      toast.success(`已新增镜头 ${nextNumber}`);
      if (created?.id) {
        setEditingId(created.id);
        setDraft(toDraft(created));
        void ensureVideoAssets();
      }
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "新增镜头失败");
    } finally {
      setCreatingShot(false);
    }
  };

  const handleDeleteShot = async (shot: ShotDto) => {
    if (!projectId || deletingId) return;
    if (
      !window.confirm(
        `确定删除镜头 ${shot.shot_number}${shot.label ? ` · ${shot.label}` : ""}？`
      )
    )
      return;
    setDeletingId(shot.id);
    try {
      await storyboardApi.deleteShot(projectId, shot.id);
      toast.success("镜头已删除");
      if (editingId === shot.id) {
        setEditingId(null);
        setDraft(null);
      }
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除镜头失败");
    } finally {
      setDeletingId(null);
    }
  };

  // 上移/下移：交换后把受影响镜头的 shot_number / sort_order 写回后端
  const handleMove = async (index: number, direction: -1 | 1) => {
    if (!projectId || moving) return;
    const target = index + direction;
    if (target < 0 || target >= shots.length) return;
    const reordered = [...shots];
    [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
    setShots(reordered);
    setMoving(true);
    try {
      await Promise.all(
        reordered.map((shot, i) =>
          shot.shot_number === i + 1 && shot.sort_order === i
            ? Promise.resolve(null)
            : storyboardApi.updateShot(projectId, shot.id, {
                shot_number: i + 1,
                sort_order: i,
              })
        )
      );
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "调整顺序失败");
      await load();
    } finally {
      setMoving(false);
    }
  };

  const handleGenerateFromScript = async () => {
    if (!projectId || generating) return;
    if (sceneCount === 0) {
      toast.error("剧本还没有场景，请先在剧本工坊创建场景");
      return;
    }
    if (
      shots.length > 0 &&
      !window.confirm(
        `从剧本生成分镜会替换现有 ${shots.length} 个镜头，确定继续？`
      )
    )
      return;
    setGenerating(true);
    try {
      const resp = (await storyboardApi.generateFromScript(projectId)) as unknown as {
        status: string;
        total: number;
      };
      toast.success(`已从剧本生成 ${resp?.total ?? 0} 个镜头`);
      setEditingId(null);
      setDraft(null);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "从剧本生成分镜失败");
    } finally {
      setGenerating(false);
    }
  };

  const handleExportJson = async () => {
    if (!projectId || !project || exporting) return;
    setExporting(true);
    try {
      const data = await storyboardApi.exportJson(projectId);
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${project.title}-分镜.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("分镜已导出");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导出分镜失败");
    } finally {
      setExporting(false);
    }
  };

  const totalDuration = useMemo(
    () => shots.reduce((sum, s) => sum + (Number(s.duration) || 0), 0),
    [shots]
  );

  if (!project) {
    return (
      <div className="max-w-3xl mx-auto mt-20 card p-10 text-center space-y-4">
        <Film size={36} className="mx-auto text-surface-300" />
        <p className="text-surface-500">
          {projectLoading
            ? "正在加载项目列表…"
            : projectError ?? "先在首页新建或选择一个项目，再回来设计分镜。"}
        </p>
        <Link href="/" className="btn-primary inline-flex">
          去选择项目
        </Link>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col animate-fade-in">
      <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-4 border-b border-surface-200 bg-white flex-shrink-0">
        <div>
          <h1 className="text-xl font-bold text-surface-900">分镜设计</h1>
          <p className="text-sm text-surface-500 mt-0.5">
            {project.title} · {shots.length} 个镜头 · 预计 {Math.round(totalDuration)} 秒 ·
            剧本场景 {sceneCount} 个
          </p>
        </div>
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
            onClick={() => void handleExportJson()}
            disabled={exporting || shots.length === 0}
            className="btn-outline flex items-center gap-1.5 text-sm disabled:opacity-60"
          >
            {exporting ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Download size={14} />
            )}
            导出 JSON
          </button>
          <button
            onClick={() => void handleGenerateFromScript()}
            disabled={generating}
            className="btn-primary flex items-center gap-1.5 text-sm disabled:opacity-60"
          >
            {generating ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Sparkles size={14} />
            )}
            {generating ? "生成中…" : "从剧本生成分镜"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-6 mt-3 flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => void load()} className="text-xs underline">
            重试
          </button>
        </div>
      )}

      <div className="flex-1 min-h-0 flex">
        {/* 镜头列表 */}
        <aside className="w-96 border-r border-surface-200 bg-white flex flex-col flex-shrink-0">
          <div className="flex items-center justify-between px-4 py-3 border-b border-surface-100">
            <div className="flex items-center gap-2">
              <Clapperboard size={16} className="text-primary-600" />
              <span className="text-sm font-medium text-surface-800">镜头列表</span>
              <span className="text-xs text-surface-400">共 {shots.length} 个</span>
            </div>
            <button
              onClick={() => void handleAddShot()}
              disabled={creatingShot}
              className="btn-outline flex items-center gap-1 text-xs disabled:opacity-60"
            >
              {creatingShot ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Plus size={12} />
              )}
              新增镜头
            </button>
          </div>

          <div className="flex-1 overflow-y-auto">
            {loading && shots.length === 0 ? (
              <div className="flex items-center justify-center gap-2 py-10 text-sm text-surface-500">
                <Loader2 size={16} className="animate-spin" />
                加载分镜中…
              </div>
            ) : shots.length === 0 ? (
              <div className="p-8 text-center space-y-3">
                <Clapperboard size={28} className="mx-auto text-surface-300" />
                <p className="text-sm text-surface-500">还没有镜头</p>
                <p className="text-xs text-surface-400">
                  从剧本 AI 生成，或手动新增镜头后逐个编辑
                </p>
                <div className="flex items-center justify-center gap-2">
                  <button
                    onClick={() => void handleGenerateFromScript()}
                    disabled={generating}
                    className="btn-primary flex items-center gap-1.5 text-xs disabled:opacity-60"
                  >
                    {generating ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Sparkles size={12} />
                    )}
                    从剧本生成
                  </button>
                  <button
                    onClick={() => void handleAddShot()}
                    disabled={creatingShot}
                    className="btn-outline flex items-center gap-1 text-xs disabled:opacity-60"
                  >
                    <Plus size={12} />
                    新增镜头
                  </button>
                </div>
              </div>
            ) : (
              <ul className="divide-y divide-surface-100">
                {shots.map((shot, index) => {
                  const expanded = editingId === shot.id;
                  const bound = Boolean(shot.video_url);
                  return (
                    <li key={shot.id} className="p-3 space-y-2">
                      <div className="flex items-start gap-2">
                        <span className="mt-0.5 inline-flex h-6 min-w-6 items-center justify-center rounded bg-surface-100 px-1 text-xs font-medium text-surface-600">
                          {shot.shot_number}
                        </span>
                        <div className="min-w-0 flex-1">
                          <button
                            onClick={() => (expanded ? closeEditor() : openEditor(shot))}
                            className="text-left w-full"
                          >
                            <p className="text-sm font-medium text-surface-800 truncate">
                              {shot.label || "未命名镜头"}
                            </p>
                            <p className="text-xs text-surface-400 truncate">
                              {[
                                shot.camera_angle,
                                shot.transition,
                                `${Number(shot.duration) || 0}s`,
                                shot.scene_ref ? `场景：${shot.scene_ref}` : null,
                              ]
                                .filter(Boolean)
                                .join(" · ")}
                            </p>
                          </button>
                          <p className="text-xs mt-1">
                            {bound ? (
                              <span className="text-green-600">
                                已绑定：{shot.video_url!.split("/").pop() || "素材"}
                              </span>
                            ) : (
                              <span className="text-surface-400">未绑定 · 渲染时由 AI 生成</span>
                            )}
                          </p>
                        </div>
                        <div className="flex flex-col items-center gap-1">
                          <button
                            onClick={() => void handleMove(index, -1)}
                            disabled={index === 0 || moving}
                            title="上移"
                            className="p-1 rounded hover:bg-surface-100 text-surface-400 disabled:opacity-30"
                          >
                            <ArrowUp size={13} />
                          </button>
                          <button
                            onClick={() => void handleMove(index, 1)}
                            disabled={index === shots.length - 1 || moving}
                            title="下移"
                            className="p-1 rounded hover:bg-surface-100 text-surface-400 disabled:opacity-30"
                          >
                            <ArrowDown size={13} />
                          </button>
                        </div>
                        <div className="flex flex-col items-center gap-1">
                          <button
                            onClick={() => (expanded ? closeEditor() : openEditor(shot))}
                            title="编辑镜头"
                            className="p-1 rounded hover:bg-surface-100 text-surface-400"
                          >
                            {expanded ? <ChevronUp size={14} /> : <Pencil size={14} />}
                          </button>
                          <button
                            onClick={() => void handleDeleteShot(shot)}
                            disabled={deletingId === shot.id}
                            title="删除镜头"
                            className="p-1 rounded hover:bg-red-50 text-surface-400 hover:text-red-600 disabled:opacity-40"
                          >
                            {deletingId === shot.id ? (
                              <Loader2 size={14} className="animate-spin" />
                            ) : (
                              <Trash2 size={14} />
                            )}
                          </button>
                        </div>
                      </div>

                      {expanded && draft && (
                        <div className="rounded-lg border border-surface-200 p-3 space-y-2 bg-surface-50/60">
                          <div className="grid grid-cols-2 gap-2">
                            <label className="space-y-1">
                              <span className="text-xs text-surface-500">镜头标题</span>
                              <input
                                value={draft.label}
                                onChange={(e) => setDraft({ ...draft, label: e.target.value })}
                                className="input-field w-full text-sm"
                                placeholder="镜头标题"
                              />
                            </label>
                            <label className="space-y-1">
                              <span className="text-xs text-surface-500">时长（秒）</span>
                              <input
                                type="number"
                                min={0}
                                step={0.5}
                                value={draft.duration}
                                onChange={(e) => setDraft({ ...draft, duration: e.target.value })}
                                className="input-field w-full text-sm"
                              />
                            </label>
                            <label className="space-y-1">
                              <span className="text-xs text-surface-500">景别</span>
                              <input
                                list="camera-angle-options"
                                value={draft.camera_angle}
                                onChange={(e) =>
                                  setDraft({ ...draft, camera_angle: e.target.value })
                                }
                                className="input-field w-full text-sm"
                              />
                            </label>
                            <label className="space-y-1">
                              <span className="text-xs text-surface-500">转场</span>
                              <input
                                list="transition-options"
                                value={draft.transition}
                                onChange={(e) =>
                                  setDraft({ ...draft, transition: e.target.value })
                                }
                                className="input-field w-full text-sm"
                              />
                            </label>
                          </div>

                          <label className="space-y-1 block">
                            <span className="text-xs text-surface-500">画面描述</span>
                            <textarea
                              value={draft.description}
                              onChange={(e) =>
                                setDraft({ ...draft, description: e.target.value })
                              }
                              rows={2}
                              className="input-field w-full text-sm resize-y"
                              placeholder="镜头画面内容"
                            />
                          </label>

                          <div className="grid grid-cols-2 gap-2">
                            <label className="space-y-1">
                              <span className="text-xs text-surface-500">关联场景</span>
                              <input
                                value={draft.scene_ref}
                                onChange={(e) =>
                                  setDraft({ ...draft, scene_ref: e.target.value })
                                }
                                className="input-field w-full text-sm"
                                placeholder="场景标题（可选）"
                              />
                            </label>
                            <label className="space-y-1">
                              <span className="text-xs text-surface-500">出场角色</span>
                              <input
                                value={draft.character_refs}
                                onChange={(e) =>
                                  setDraft({ ...draft, character_refs: e.target.value })
                                }
                                className="input-field w-full text-sm"
                                placeholder="用逗号分隔"
                              />
                            </label>
                          </div>

                          <label className="space-y-1 block">
                            <span className="text-xs text-surface-500">绑定视频素材</span>
                            <select
                              value={draft.video_url}
                              onChange={(e) =>
                                setDraft({ ...draft, video_url: e.target.value })
                              }
                              disabled={assetsLoading}
                              className="input-field w-full text-sm"
                            >
                              <option value="">AI 生成（不绑定）</option>
                              {(videoAssets ?? []).map((asset) => (
                                <option
                                  key={asset.id}
                                  value={asset.canonical_url ?? ""}
                                  disabled={!asset.canonical_url}
                                >
                                  {asset.name}
                                  {asset.duration ? `（${Math.round(asset.duration)}s）` : ""}
                                </option>
                              ))}
                            </select>
                            {draft.video_url &&
                              !(videoAssets ?? []).some(
                                (a) => a.canonical_url === draft.video_url
                              ) && (
                                <span className="text-xs text-surface-400">
                                  当前绑定：{draft.video_url.split("/").pop()}
                                </span>
                              )}
                          </label>

                          <div className="flex items-center justify-end gap-2 pt-1">
                            <button
                              onClick={closeEditor}
                              disabled={savingShot}
                              className="btn-outline text-xs"
                            >
                              取消
                            </button>
                            <button
                              onClick={() => void handleSaveShot()}
                              disabled={savingShot}
                              className="btn-primary flex items-center gap-1.5 text-xs disabled:opacity-60"
                            >
                              {savingShot && <Loader2 size={12} className="animate-spin" />}
                              保存镜头
                            </button>
                          </div>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="px-4 py-2 border-t border-surface-100 text-xs text-surface-400">
            分镜画面在右侧画布编排，画布状态自动保存
          </div>
        </aside>

        {/* 画布 */}
        <div className="flex-1 min-w-0">
          <StoryboardCanvas sceneCount={sceneCount} />
        </div>
      </div>

      <datalist id="camera-angle-options">
        {CAMERA_ANGLE_SUGGESTIONS.map((v) => (
          <option key={v} value={v} />
        ))}
      </datalist>
      <datalist id="transition-options">
        {TRANSITION_SUGGESTIONS.map((v) => (
          <option key={v} value={v} />
        ))}
      </datalist>
    </div>
  );
}
