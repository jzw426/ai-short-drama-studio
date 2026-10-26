"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  FileText,
  Loader2,
  Plus,
  Save,
  Sparkles,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { scriptApi, type SceneDto, type ScriptDto } from "@/lib/api";
import { TIME_OF_DAY_SUGGESTIONS } from "@/lib/labels";

interface ScriptEditorProps {
  projectId: string;
}

/** 后端 word_count 是 Python len(content)（按 Unicode 码点计），这里保持一致 */
function countWords(text: string): number {
  return Array.from(text).length;
}

function sortScenes(list: SceneDto[]): SceneDto[] {
  return [...list].sort(
    (a, b) => a.sort_order - b.sort_order || a.scene_number - b.scene_number
  );
}

const SCENE_FIELDS = [
  "scene_number",
  "title",
  "location",
  "time_of_day",
  "interior",
  "summary",
  "content",
  "dialogue",
  "duration",
  "sort_order",
] as const;

export function ScriptEditor({ projectId }: ScriptEditorProps) {
  const [script, setScript] = useState<ScriptDto | null>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [scenes, setScenes] = useState<SceneDto[]>([]);
  const [activeSceneId, setActiveSceneId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"scenes" | "content">("scenes");
  const [scriptDirty, setScriptDirty] = useState(false);
  const [savingScript, setSavingScript] = useState(false);
  const [dirtySceneIds, setDirtySceneIds] = useState<string[]>([]);
  const [savingSceneId, setSavingSceneId] = useState<string | null>(null);
  const [creatingScene, setCreatingScene] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiGenerating, setAiGenerating] = useState(false);

  const activeScene = useMemo(
    () => scenes.find((s) => s.id === activeSceneId) ?? null,
    [scenes, activeSceneId]
  );

  const wordCount = useMemo(() => countWords(content), [content]);
  const totalDuration = useMemo(
    () => scenes.reduce((sum, s) => sum + (Number.isFinite(s.duration) ? s.duration : 0), 0),
    [scenes]
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = (await scriptApi.get(projectId)) as unknown as ScriptDto;
      const sorted = sortScenes(data.scenes ?? []);
      setScript(data);
      setTitle(data.title ?? "");
      setContent(data.content ?? "");
      setScenes(sorted);
      setScriptDirty(false);
      setDirtySceneIds([]);
      setActiveSceneId((prev) =>
        prev && sorted.some((s) => s.id === prev) ? prev : sorted[0]?.id ?? null
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : "加载剧本失败";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  // ===== 剧本级保存（title/content/word_count，后端 ScriptUpdate 只收这三个字段） =====
  const saveScript = useCallback(async () => {
    if (savingScript) return;
    setSavingScript(true);
    try {
      const updated = (await scriptApi.update(projectId, {
        title: title.trim() || "未命名剧本",
        content,
        word_count: countWords(content),
      })) as unknown as ScriptDto;
      setScript(updated);
      setTitle(updated.title ?? "");
      setContent(updated.content ?? "");
      // 有未保存的场景修改时不要用服务端旧数据覆盖本地编辑
      if (dirtySceneIds.length === 0) {
        setScenes(sortScenes(updated.scenes ?? []));
      }
      setScriptDirty(false);
      toast.success("剧本已保存");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存剧本失败");
    } finally {
      setSavingScript(false);
    }
  }, [projectId, title, content, savingScript, dirtySceneIds.length]);

  // ===== 场景编辑（本地改，显式保存） =====
  const patchScene = useCallback((sceneId: string, patch: Partial<SceneDto>) => {
    setScenes((prev) => prev.map((s) => (s.id === sceneId ? { ...s, ...patch } : s)));
    setDirtySceneIds((prev) => (prev.includes(sceneId) ? prev : [...prev, sceneId]));
  }, []);

  const saveScene = useCallback(
    async (scene: SceneDto) => {
      if (savingSceneId) return;
      setSavingSceneId(scene.id);
      try {
        const payload: Record<string, unknown> = {};
        for (const key of SCENE_FIELDS) {
          payload[key] = scene[key];
        }
        const updated = (await scriptApi.updateScene(
          projectId,
          scene.id,
          payload
        )) as unknown as SceneDto;
        // 只回填非编辑字段，避免响应覆盖用户正在输入的内容
        setScenes((prev) =>
          prev.map((s) => (s.id === scene.id ? { ...s, scene_number: updated.scene_number, sort_order: updated.sort_order } : s))
        );
        setDirtySceneIds((prev) => prev.filter((id) => id !== scene.id));
        toast.success(`场景 ${scene.scene_number} 已保存`);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "保存场景失败");
      } finally {
        setSavingSceneId(null);
      }
    },
    [projectId, savingSceneId]
  );

  const selectScene = useCallback(
    (sceneId: string) => {
      if (sceneId === activeSceneId) return;
      if (activeSceneId && dirtySceneIds.includes(activeSceneId)) {
        if (!window.confirm("当前场景有未保存的修改，切换后将丢失，是否继续？")) {
          return;
        }
        setDirtySceneIds((prev) => prev.filter((id) => id !== activeSceneId));
      }
      setActiveSceneId(sceneId);
    },
    [activeSceneId, dirtySceneIds]
  );

  const createScene = useCallback(async () => {
    if (creatingScene) return;
    setCreatingScene(true);
    try {
      const nextNumber = scenes.reduce((max, s) => Math.max(max, s.scene_number), 0) + 1;
      const nextOrder = scenes.reduce((max, s) => Math.max(max, s.sort_order), 0) + 1;
      const created = (await scriptApi.createScene(projectId, {
        scene_number: nextNumber,
        title: "",
        location: "",
        time_of_day: "day",
        interior: true,
        summary: "",
        content: "",
        dialogue: "",
        duration: 0,
        sort_order: nextOrder,
      })) as unknown as SceneDto;
      setScenes((prev) => sortScenes([...prev, created]));
      setActiveSceneId(created.id);
      toast.success("场景已创建");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "创建场景失败");
    } finally {
      setCreatingScene(false);
    }
  }, [projectId, scenes, creatingScene]);

  const deleteScene = useCallback(
    async (scene: SceneDto) => {
      if (!window.confirm(`确定删除场景 ${scene.scene_number}？`)) return;
      try {
        await scriptApi.deleteScene(projectId, scene.id);
        const remaining = scenes.filter((s) => s.id !== scene.id);
        setScenes(remaining);
        setDirtySceneIds((prev) => prev.filter((id) => id !== scene.id));
        if (activeSceneId === scene.id) {
          setActiveSceneId(remaining[0]?.id ?? null);
        }
        toast.success("场景已删除");
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "删除场景失败");
      }
    },
    [projectId, scenes, activeSceneId]
  );

  // 排序：直接用 PUT 改写 scene_number/sort_order（后端按 sort_order 排序）
  const moveScene = useCallback(
    async (index: number, direction: -1 | 1) => {
      const target = index + direction;
      if (target < 0 || target >= scenes.length) return;
      const reordered = [...scenes];
      const [moved] = reordered.splice(index, 1);
      reordered.splice(target, 0, moved);
      const changed = reordered
        .map((scene, idx) => ({ scene, number: idx + 1, order: idx }))
        .filter(({ scene, number, order }) => scene.scene_number !== number || scene.sort_order !== order);
      try {
        await Promise.all(
          changed.map(({ scene, number, order }) =>
            scriptApi.updateScene(projectId, scene.id, {
              scene_number: number,
              sort_order: order,
            })
          )
        );
        setScenes(
          reordered.map((scene, idx) => ({ ...scene, scene_number: idx + 1, sort_order: idx }))
        );
        toast.success("场景顺序已更新");
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "调整顺序失败");
      }
    },
    [projectId, scenes]
  );

  // ===== AI 续写：后端把生成内容追加进 script.content，返回 generated_content =====
  const aiGenerate = useCallback(async () => {
    const prompt = aiPrompt.trim();
    if (!prompt) {
      toast.error("请先描述想要生成的内容");
      return;
    }
    if (
      (scriptDirty || dirtySceneIds.length > 0) &&
      !window.confirm("AI 生成会重新加载剧本，未保存的修改将丢失，是否继续？")
    ) {
      return;
    }
    setAiGenerating(true);
    try {
      const result = (await scriptApi.aiGenerate(projectId, prompt)) as unknown as {
        generated_content: string;
      };
      // 重新拉取：后端已把生成内容追加到 content 并更新 word_count
      await load();
      setTab("content");
      setAiOpen(false);
      setAiPrompt("");
      toast.success(
        result?.generated_content
          ? `AI 已生成 ${countWords(result.generated_content)} 字，已追加到剧本正文`
          : "AI 生成完成"
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "AI 生成失败");
    } finally {
      setAiGenerating(false);
    }
  }, [aiPrompt, projectId, load, scriptDirty, dirtySceneIds.length]);

  if (loading && !script) {
    return (
      <div className="card p-10 flex items-center justify-center gap-2 text-sm text-surface-500">
        <Loader2 size={16} className="animate-spin" />
        加载剧本中…
      </div>
    );
  }

  if (error && !script) {
    return (
      <div className="card p-10 text-center space-y-4">
        <AlertTriangle size={28} className="mx-auto text-red-500" />
        <p className="text-sm text-red-600">{error}</p>
        <button onClick={() => void load()} className="btn-outline text-sm">
          重新加载
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => void load()} className="text-xs underline">
            重试
          </button>
        </div>
      )}

      {/* 顶部：标题 + 保存 + AI */}
      <div className="card p-4 space-y-3">
        <div className="flex flex-col md:flex-row md:items-center gap-3">
          <input
            value={title}
            onChange={(e) => {
              setTitle(e.target.value);
              setScriptDirty(true);
            }}
            placeholder="剧本标题"
            className="input-field flex-1 text-lg font-semibold"
          />
          <div className="flex items-center gap-2">
            <button
              onClick={() => void saveScript()}
              disabled={savingScript || !scriptDirty}
              className="btn-primary flex items-center gap-2 text-sm disabled:opacity-60"
            >
              {savingScript ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Save size={16} />
              )}
              保存剧本
            </button>
            <button
              onClick={() => setAiOpen((v) => !v)}
              className="btn-outline flex items-center gap-2 text-sm"
            >
              <Sparkles size={16} />
              AI 续写
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs text-surface-400">
          <span>场景 {scenes.length} 个</span>
          <span>总时长 {Math.round(totalDuration)} 秒</span>
          <span>字数 {wordCount}</span>
          <span>
            {savingScript
              ? "保存中…"
              : scriptDirty
              ? "剧本有未保存修改"
              : script
              ? "剧本已保存"
              : ""}
          </span>
          {dirtySceneIds.length > 0 && (
            <span className="text-amber-600">
              {dirtySceneIds.length} 个场景有未保存修改
            </span>
          )}
        </div>

        {aiOpen && (
          <div className="border border-surface-200 rounded-lg p-3 space-y-2 bg-surface-50">
            <p className="text-xs text-surface-500">
              描述想要的情节，AI 会续写并追加到剧本正文（每次生成会消耗 AI 配额）。
            </p>
            <textarea
              value={aiPrompt}
              onChange={(e) => setAiPrompt(e.target.value)}
              rows={3}
              maxLength={5000}
              placeholder="例如：男主在雨夜发现女主隐瞒的身份，两人爆发争吵……"
              className="input-field w-full resize-y"
            />
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-surface-400">
                {aiPrompt.length}/5000
              </span>
              <button
                onClick={() => void aiGenerate()}
                disabled={aiGenerating || !aiPrompt.trim()}
                className="btn-primary flex items-center gap-2 text-sm disabled:opacity-60"
              >
                {aiGenerating ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <Sparkles size={16} />
                )}
                {aiGenerating ? "生成中…" : "开始生成"}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Tab 切换 */}
      <div className="flex items-center gap-1 border-b border-surface-200">
        <button
          onClick={() => setTab("scenes")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "scenes"
              ? "border-primary-500 text-primary-600"
              : "border-transparent text-surface-500 hover:text-surface-700"
          }`}
        >
          分镜场景
        </button>
        <button
          onClick={() => setTab("content")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "content"
              ? "border-primary-500 text-primary-600"
              : "border-transparent text-surface-500 hover:text-surface-700"
          }`}
        >
          剧本正文
        </button>
      </div>

      {tab === "content" && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-surface-700">剧本正文</p>
            <span className="text-xs text-surface-400">
              AI 生成的内容会追加到这里
            </span>
          </div>
          <textarea
            value={content}
            onChange={(e) => {
              setContent(e.target.value);
              setScriptDirty(true);
            }}
            rows={22}
            placeholder="在这里写剧本正文，或使用上方 AI 续写…"
            className="input-field w-full font-mono text-sm leading-6 resize-y"
          />
          <div className="flex items-center justify-between">
            <span className="text-xs text-surface-400">字数 {wordCount}</span>
            <button
              onClick={() => void saveScript()}
              disabled={savingScript || !scriptDirty}
              className="btn-primary flex items-center gap-2 text-sm disabled:opacity-60"
            >
              {savingScript ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Save size={16} />
              )}
              保存剧本
            </button>
          </div>
        </div>
      )}

      {tab === "scenes" && (
        <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
          {/* 场景列表 */}
          <div className="card p-3 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-surface-700">场景列表</p>
              <button
                onClick={() => void createScene()}
                disabled={creatingScene}
                className="flex items-center gap-1 text-xs text-primary-600 hover:text-primary-700 disabled:opacity-60"
              >
                {creatingScene ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Plus size={14} />
                )}
                新建场景
              </button>
            </div>

            {scenes.length === 0 ? (
              <div className="text-center py-8 space-y-3">
                <FileText size={24} className="mx-auto text-surface-300" />
                <p className="text-xs text-surface-400">还没有场景</p>
                <button onClick={() => void createScene()} className="btn-outline text-xs">
                  创建第一个场景
                </button>
              </div>
            ) : (
              <div className="space-y-1.5 max-h-[560px] overflow-y-auto">
                {scenes.map((scene, index) => {
                  const dirty = dirtySceneIds.includes(scene.id);
                  return (
                    <div
                      key={scene.id}
                      onClick={() => selectScene(scene.id)}
                      className={`group rounded-lg border p-2.5 cursor-pointer transition-colors ${
                        scene.id === activeSceneId
                          ? "border-primary-300 bg-primary-50"
                          : "border-surface-200 hover:bg-surface-50"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-medium text-surface-700 truncate">
                          场景 {scene.scene_number}
                          {scene.title ? ` · ${scene.title}` : ""}
                        </span>
                        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              void moveScene(index, -1);
                            }}
                            disabled={index === 0}
                            title="上移"
                            className="p-1 rounded hover:bg-surface-200 disabled:opacity-30"
                          >
                            <ArrowUp size={12} />
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              void moveScene(index, 1);
                            }}
                            disabled={index === scenes.length - 1}
                            title="下移"
                            className="p-1 rounded hover:bg-surface-200 disabled:opacity-30"
                          >
                            <ArrowDown size={12} />
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              void deleteScene(scene);
                            }}
                            title="删除场景"
                            className="p-1 rounded hover:bg-red-100 text-surface-400 hover:text-red-600"
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                      </div>
                      <p className="text-[11px] text-surface-400 truncate mt-1">
                        {[scene.location || "未设地点", scene.time_of_day || "未设时段", `${scene.duration || 0} 秒`].join(" · ")}
                      </p>
                      {dirty && (
                        <span className="text-[11px] text-amber-600">未保存</span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* 场景编辑 */}
          <div className="card p-4 min-w-0">
            {!activeScene ? (
              <div className="text-center py-16 space-y-3">
                <FileText size={28} className="mx-auto text-surface-300" />
                <p className="text-sm text-surface-400">
                  从左侧选择一个场景，或新建场景开始编写
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-surface-800">
                    场景 {activeScene.scene_number}
                    {dirtySceneIds.includes(activeScene.id) ? "（未保存）" : ""}
                  </h3>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => void saveScene(activeScene)}
                      disabled={savingSceneId === activeScene.id || !dirtySceneIds.includes(activeScene.id)}
                      className="btn-primary flex items-center gap-2 text-sm disabled:opacity-60"
                    >
                      {savingSceneId === activeScene.id ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <Save size={14} />
                      )}
                      保存场景
                    </button>
                    <button
                      onClick={() => void deleteScene(activeScene)}
                      className="btn-outline flex items-center gap-2 text-sm text-red-600"
                    >
                      <Trash2 size={14} />
                      删除
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <label className="space-y-1 block">
                    <span className="text-xs text-surface-500">场景标题</span>
                    <input
                      value={activeScene.title}
                      onChange={(e) => patchScene(activeScene.id, { title: e.target.value })}
                      placeholder="例如：雨夜重逢"
                      className="input-field w-full"
                    />
                  </label>
                  <label className="space-y-1 block">
                    <span className="text-xs text-surface-500">地点</span>
                    <input
                      value={activeScene.location}
                      onChange={(e) => patchScene(activeScene.id, { location: e.target.value })}
                      placeholder="例如：城市街头"
                      className="input-field w-full"
                    />
                  </label>
                  <label className="space-y-1 block">
                    <span className="text-xs text-surface-500">时段</span>
                    <input
                      value={activeScene.time_of_day}
                      onChange={(e) => patchScene(activeScene.id, { time_of_day: e.target.value })}
                      list="scene-time-options"
                      placeholder="day / night …"
                      className="input-field w-full"
                    />
                    <datalist id="scene-time-options">
                      {TIME_OF_DAY_SUGGESTIONS.map((t) => (
                        <option key={t} value={t} />
                      ))}
                    </datalist>
                  </label>
                  <label className="space-y-1 block">
                    <span className="text-xs text-surface-500">景别</span>
                    <select
                      value={activeScene.interior ? "interior" : "exterior"}
                      onChange={(e) =>
                        patchScene(activeScene.id, { interior: e.target.value === "interior" })
                      }
                      className="input-field w-full"
                    >
                      <option value="interior">内景</option>
                      <option value="exterior">外景</option>
                    </select>
                  </label>
                  <label className="space-y-1 block">
                    <span className="text-xs text-surface-500">时长（秒）</span>
                    <input
                      type="number"
                      min={0}
                      value={activeScene.duration}
                      onChange={(e) =>
                        patchScene(activeScene.id, {
                          duration: Math.max(0, Math.round(Number(e.target.value) || 0)),
                        })
                      }
                      className="input-field w-full"
                    />
                  </label>
                </div>

                <label className="space-y-1 block">
                  <span className="text-xs text-surface-500">场景概要</span>
                  <textarea
                    value={activeScene.summary}
                    onChange={(e) => patchScene(activeScene.id, { summary: e.target.value })}
                    rows={2}
                    placeholder="一句话概括这一场发生了什么"
                    className="input-field w-full resize-y"
                  />
                </label>

                <label className="space-y-1 block">
                  <span className="text-xs text-surface-500">画面描述</span>
                  <textarea
                    value={activeScene.content}
                    onChange={(e) => patchScene(activeScene.id, { content: e.target.value })}
                    rows={5}
                    placeholder="镜头拍什么、人物动作、环境氛围…"
                    className="input-field w-full resize-y"
                  />
                </label>

                <label className="space-y-1 block">
                  <span className="text-xs text-surface-500">
                    台词（渲染烧字幕的唯一来源，留空则从画面描述的引号文本提取）
                  </span>
                  <textarea
                    value={activeScene.dialogue}
                    onChange={(e) => patchScene(activeScene.id, { dialogue: e.target.value })}
                    rows={4}
                    placeholder="每行一句台词，例如：林夏：你到底还瞒着我什么？"
                    className="input-field w-full resize-y"
                  />
                </label>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
