"use client";

import React, { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { useShallow } from "zustand/shallow";
import { toast } from "sonner";
import {
  Plus,
  Trash2,
  Save,
  Download,
  Sparkles,
  GripVertical,
  ChevronUp,
  ChevronDown,
  RefreshCw,
  MessageSquare,
  Eye,
  FileText,
  MapPin,
  Clock,
  MoreHorizontal,
} from "lucide-react";
import { useProjectStore, selectScriptStats } from "@/store/useProjectStore";
import type { ScriptScene, DialogueLine } from "@/store/useProjectStore";
import { scriptApi } from "@/lib/api";

// ===== 子组件 =====

/* ---- 场景标签按钮 ---- */
function SceneTab({
  scene,
  isActive,
  onClick,
  onDelete,
  disabled,
}: {
  scene: ScriptScene;
  isActive: boolean;
  onClick: () => void;
  onDelete: () => void;
  disabled: boolean;
}) {
  return (
    <div
      className={`group flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer transition-colors whitespace-nowrap border ${
        isActive
          ? "bg-primary-50 text-primary-700 border-primary-200"
          : "bg-white text-surface-600 border-transparent hover:bg-surface-50 hover:border-surface-200"
      }`}
      onClick={onClick}
    >
      <span className="text-[10px] font-bold text-primary-400">
        #{scene.sceneNumber}
      </span>
      <span className="truncate max-w-[80px]">{scene.title}</span>
      <button
        className="ml-0.5 opacity-0 group-hover:opacity-100 text-surface-400 hover:text-red-500 transition-opacity"
        onClick={(e) => {
          e.stopPropagation();
          if (!disabled) onDelete();
        }}
        disabled={disabled}
        title="删除场景"
      >
        <Trash2 size={10} />
      </button>
    </div>
  );
}

/* ---- 对白行编辑器 ---- */
function DialogueBlock({
  line,
  sceneId,
  onUpdate,
  onDelete,
  onAddAfter,
}: {
  line: DialogueLine;
  sceneId: string;
  onUpdate: (lineId: string, data: Partial<DialogueLine>) => void;
  onDelete: (lineId: string) => void;
  onAddAfter: (lineId: string, type: DialogueLine["type"]) => void;
}) {
  const [localContent, setLocalContent] = useState(line.content);
  const [localCharacter, setLocalCharacter] = useState(line.character ?? "");
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    setLocalContent(line.content);
    setLocalCharacter(line.character ?? "");
  }, [line.content, line.character]);

  const handleContentChange = useCallback(
    (val: string) => {
      setLocalContent(val);
      clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        onUpdate(line.id, { content: val });
      }, 400);
    },
    [line.id, onUpdate]
  );

  const handleCharacterChange = useCallback(
    (val: string) => {
      setLocalCharacter(val);
      clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        onUpdate(line.id, { character: val });
      }, 400);
    },
    [line.id, onUpdate]
  );

  const styleMap: Record<
    DialogueLine["type"],
    { border: string; bg: string; label: string; labelClass: string }
  > = {
    dialogue: {
      border: "border-l-blue-400",
      bg: "bg-blue-50/40",
      label: "对白",
      labelClass: "bg-blue-100 text-blue-700",
    },
    action: {
      border: "border-l-gray-400",
      bg: "bg-gray-50/40",
      label: "动作",
      labelClass: "bg-gray-100 text-gray-600",
    },
    narration: {
      border: "border-l-purple-400",
      bg: "bg-purple-50/40",
      label: "旁白",
      labelClass: "bg-purple-100 text-purple-700",
    },
  };

  const s = styleMap[line.type];

  return (
    <div className={`group/block border-l-4 ${s.border} ${s.bg} pl-3 pr-2 py-2 rounded-r-md mb-2`}>
      <div className="flex items-center gap-1.5 mb-1">
        <span
          className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${s.labelClass}`}
        >
          {s.label}
        </span>
        {line.type === "dialogue" && (
          <input
            value={localCharacter}
            onChange={(e) => handleCharacterChange(e.target.value)}
            className="text-xs font-medium text-blue-700 bg-transparent border-none outline-none placeholder:text-blue-300 w-24"
            placeholder="角色名"
          />
        )}
        <div className="ml-auto flex items-center gap-0.5 opacity-0 group-hover/block:opacity-100 transition-opacity">
          <button
            className="p-0.5 text-surface-400 hover:text-surface-600"
            onClick={() => onAddAfter(line.id, "dialogue")}
            title="添加对白"
          >
            <MessageSquare size={12} />
          </button>
          <button
            className="p-0.5 text-surface-400 hover:text-surface-600"
            onClick={() => onAddAfter(line.id, "action")}
            title="添加动作"
          >
            <Eye size={12} />
          </button>
          <button
            className="p-0.5 text-surface-400 hover:text-red-500"
            onClick={() => onDelete(line.id)}
            title="删除此行"
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      {line.type === "dialogue" ? (
        <div className="text-sm text-blue-900 font-medium leading-relaxed">
          <span className="text-blue-400 select-none">&ldquo;</span>
          <textarea
            value={localContent}
            onChange={(e) => handleContentChange(e.target.value)}
            className="w-full resize-none bg-transparent border-none outline-none text-sm leading-relaxed placeholder:text-blue-300"
            rows={Math.max(1, Math.min(6, localContent.split("\n").length))}
            placeholder="输入对话内容..."
          />
          <span className="text-blue-400 select-none">&rdquo;</span>
        </div>
      ) : (
        <textarea
          value={localContent}
          onChange={(e) => handleContentChange(e.target.value)}
          className={`w-full resize-none bg-transparent border-none outline-none text-sm leading-relaxed ${
            line.type === "action"
              ? "text-gray-500 italic"
              : "text-purple-700"
          } placeholder:text-surface-300`}
          rows={Math.max(1, Math.min(6, localContent.split("\n").length))}
          placeholder={
            line.type === "action" ? "描述动作或场景..." : "旁白内容..."
          }
        />
      )}
    </div>
  );
}

/* ---- 时间标签选择器 ---- */
const TIME_OPTIONS: { value: ScriptScene["timeOfDay"]; label: string; icon: string }[] = [
  { value: "morning", label: "早晨", icon: "☀" },
  { value: "afternoon", label: "下午", icon: "☁" },
  { value: "evening", label: "傍晚", icon: "🌅" },
  { value: "night", label: "夜晚", icon: "🌙" },
];

// ===== 主组件 =====

export function ScriptEditor() {
  const {
    scriptScenes,
    scriptLoading,
    scriptSaveStatus,
    scriptError,
    setScriptScenes,
    addScene,
    updateScene,
    deleteScene,
    reorderScenes,
    addDialogueLine,
    updateDialogueLine,
    deleteDialogueLine,
    setScriptSaveStatus,
    setScriptLoading,
    setScriptError,
    currentProject,
  } = useProjectStore();

  const [activeSceneIndex, setActiveSceneIndex] = useState(0);
  const initializedRef = useRef(false);

  const stats = useProjectStore(useShallow(selectScriptStats));

  // 自动初始化场景（仅执行一次）
  useEffect(() => {
    if (!initializedRef.current && scriptScenes.length === 0 && currentProject) {
      initializedRef.current = true;
      const initial: ScriptScene = {
        id: "init_scene_1",
        sceneNumber: 1,
        title: "场景 1",
        location: "",
        timeOfDay: "morning",
        interior: true,
        dialogues: [
          { id: "init_line_1", type: "action", content: "（在此处添加场景描述或动作...）" },
        ],
        sortOrder: 0,
      };
      setScriptScenes([initial]);
    }
  }, [scriptScenes.length, currentProject, setScriptScenes]);

  // 错误提示
  useEffect(() => {
    if (scriptError) {
      toast.error(scriptError);
      setScriptError(null);
    }
  }, [scriptError, setScriptError]);

  const activeScene = scriptScenes[activeSceneIndex] ?? scriptScenes[0];

  // ---- 操作方法 ----

  const handleAddScene = useCallback(() => {
    addScene(activeSceneIndex);
    setActiveSceneIndex(scriptScenes.length); // 新增场景在末尾
  }, [addScene, activeSceneIndex, scriptScenes.length]);

  const handleDeleteScene = useCallback(
    (index: number) => {
      if (scriptScenes.length <= 1) {
        toast.warning("至少保留一个场景");
        return;
      }
      const sceneId = scriptScenes[index]?.id;
      if (sceneId) deleteScene(sceneId);
      if (activeSceneIndex >= index && activeSceneIndex > 0) {
        setActiveSceneIndex((prev) => Math.max(0, prev - 1));
      }
    },
    [scriptScenes, deleteScene, activeSceneIndex]
  );

  const handleMoveSceneUp = useCallback(
    (index: number) => {
      if (index === 0) return;
      reorderScenes(index, index - 1);
      if (activeSceneIndex === index) setActiveSceneIndex(index - 1);
      else if (activeSceneIndex === index - 1) setActiveSceneIndex(index);
    },
    [reorderScenes, activeSceneIndex]
  );

  const handleMoveSceneDown = useCallback(
    (index: number) => {
      if (index === scriptScenes.length - 1) return;
      reorderScenes(index, index + 1);
      if (activeSceneIndex === index) setActiveSceneIndex(index + 1);
      else if (activeSceneIndex === index + 1) setActiveSceneIndex(index);
    },
    [reorderScenes, activeSceneIndex, scriptScenes.length]
  );

  const handleSave = useCallback(async () => {
    if (!currentProject) {
      toast.error("请先选择一个项目");
      return;
    }
    setScriptSaveStatus("saving");
    try {
      await scriptApi.update(currentProject.id, {
        scenes: scriptScenes,
        content: JSON.stringify(scriptScenes),
      });
      setScriptSaveStatus("saved");
      toast.success("剧本已保存");
    } catch {
      setScriptSaveStatus("unsaved");
      toast.error("保存失败，请重试");
    }
  }, [currentProject, scriptScenes, setScriptSaveStatus]);

  const handleAiGenerate = useCallback(async () => {
    if (!currentProject) {
      toast.error("请先选择一个项目");
      return;
    }
    setScriptLoading(true);
    try {
      const prompt = scriptScenes
        .map((s) => `场景${s.sceneNumber}: ${s.title} (${s.location})`)
        .join("; ");
      const result: unknown = await scriptApi.aiGenerate(
        currentProject.id,
        prompt || "请生成一个短剧剧本"
      );
      // 尝试解析 AI 返回的场景数据
      const data = result as { scenes?: ScriptScene[]; content?: string };
      if (data?.scenes && Array.isArray(data.scenes)) {
        setScriptScenes(data.scenes);
        toast.success("AI 剧本生成完成");
      } else {
        toast.info("AI 已返回建议，请在编辑器中调整");
      }
    } catch {
      toast.error("AI 生成失败，请稍后重试");
    } finally {
      setScriptLoading(false);
    }
  }, [currentProject, scriptScenes, setScriptScenes, setScriptLoading]);

  const handleExport = useCallback(() => {
    const lines: string[] = [];
    for (const scene of scriptScenes) {
      const interior = scene.interior ? "内" : "外";
      const timeLabel = TIME_OPTIONS.find((t) => t.value === scene.timeOfDay)?.label ?? "";
      lines.push(`\n【场景 ${scene.sceneNumber}：${scene.title}】`);
      lines.push(`  地点：${scene.location}  |  时间：${timeLabel}  |  ${interior}景`);
      lines.push("");
      for (const line of scene.dialogues) {
        if (line.type === "dialogue") {
          lines.push(`  ${line.character ?? "未知"}："${line.content}"`);
        } else if (line.type === "action") {
          lines.push(`  （${line.content}）`);
        } else {
          lines.push(`  [旁白] ${line.content}`);
        }
      }
      lines.push("");
    }

    const text = lines.join("\n");
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const filename =
      currentProject?.title ?? "剧本";
    a.download = `${filename}_剧本.txt`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("剧本已导出");
  }, [scriptScenes, currentProject]);

  // ---- 加载骨架 ----
  if (scriptLoading && scriptScenes.length === 0) {
    return (
      <div className="space-y-4 p-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="animate-pulse space-y-2">
            <div className="h-4 w-24 bg-surface-200 rounded" />
            <div className="h-20 bg-surface-100 rounded-lg" />
          </div>
        ))}
      </div>
    );
  }

  if (!activeScene) {
    return (
      <div className="flex items-center justify-center h-64 text-surface-400">
        <div className="text-center">
          <FileText size={40} className="mx-auto mb-2 opacity-30" />
          <p className="text-sm">点击「添加场景」开始创作</p>
        </div>
      </div>
    );
  }

  const saveStatusText: Record<string, string> = {
    idle: "",
    saved: "已保存",
    unsaved: "未保存",
    saving: "保存中...",
  };

  return (
    <div className="flex flex-col h-full bg-white rounded-lg border border-surface-200 overflow-hidden">
      {/* ---- 顶部工具栏 ---- */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-surface-200 bg-surface-50/50 flex-shrink-0">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-surface-800">剧本编辑器</h2>
          <span
            className={`text-[10px] px-1.5 py-0.5 rounded-full ${
              scriptSaveStatus === "saved"
                ? "bg-green-100 text-green-700"
                : scriptSaveStatus === "unsaved"
                ? "bg-amber-100 text-amber-700"
                : scriptSaveStatus === "saving"
                ? "bg-blue-100 text-blue-700"
                : "hidden"
            }`}
          >
            {saveStatusText[scriptSaveStatus]}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={handleAiGenerate}
            disabled={scriptLoading}
            className="btn-primary text-xs py-1.5 px-3 flex items-center gap-1"
          >
            {scriptLoading ? (
              <RefreshCw size={13} className="animate-spin" />
            ) : (
              <Sparkles size={13} />
            )}
            <span className="hidden sm:inline">AI 生成</span>
          </button>
          <button
            onClick={handleSave}
            disabled={scriptSaveStatus === "saving" || !currentProject}
            className="btn-secondary text-xs py-1.5 px-3 flex items-center gap-1"
          >
            <Save size={13} />
            <span className="hidden sm:inline">保存</span>
          </button>
          <button
            onClick={handleExport}
            disabled={scriptScenes.length === 0}
            className="btn-secondary text-xs py-1.5 px-3 flex items-center gap-1"
          >
            <Download size={13} />
            <span className="hidden sm:inline">导出</span>
          </button>
        </div>
      </div>

      {/* ---- 场景标签栏 ---- */}
      <div className="flex items-center gap-1 px-4 py-2 border-b border-surface-100 bg-white overflow-x-auto scrollbar-thin flex-shrink-0">
        {scriptScenes.map((scene, idx) => (
          <SceneTab
            key={scene.id}
            scene={scene}
            isActive={idx === activeSceneIndex}
            onClick={() => setActiveSceneIndex(idx)}
            onDelete={() => handleDeleteScene(idx)}
            disabled={scriptScenes.length <= 1}
          />
        ))}
        <button
          onClick={handleAddScene}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium text-primary-600 hover:bg-primary-50 border border-dashed border-primary-200 transition-colors whitespace-nowrap flex-shrink-0 ml-1"
        >
          <Plus size={12} />
          添加场景
        </button>

        {/* 场景排序按钮（桌面端） */}
        <div className="hidden md:flex items-center gap-0.5 ml-auto">
          <button
            onClick={() => handleMoveSceneUp(activeSceneIndex)}
            disabled={activeSceneIndex === 0}
            className="p-1 text-surface-400 hover:text-surface-600 disabled:opacity-30"
            title="上移场景"
          >
            <ChevronUp size={14} />
          </button>
          <button
            onClick={() => handleMoveSceneDown(activeSceneIndex)}
            disabled={activeSceneIndex === scriptScenes.length - 1}
            className="p-1 text-surface-400 hover:text-surface-600 disabled:opacity-30"
            title="下移场景"
          >
            <ChevronDown size={14} />
          </button>
        </div>
      </div>

      {/* ---- 场景编辑区 ---- */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6 scrollbar-thin">
        {/* 场景头部信息 */}
        <div className="mb-4 pb-4 border-b border-dashed border-surface-200">
          <div className="flex flex-wrap items-end gap-3">
            {/* 场景标题 */}
            <div className="flex items-center gap-1">
              <span className="text-xs font-bold text-primary-500 bg-primary-50 px-1.5 py-0.5 rounded">
                场景 {activeScene.sceneNumber}
              </span>
              <input
                value={activeScene.title}
                onChange={(e) =>
                  updateScene(activeScene.id, { title: e.target.value })
                }
                className="text-lg font-semibold text-surface-900 bg-transparent border-none outline-none w-36 placeholder:text-surface-300"
                placeholder="场景标题"
              />
            </div>

            {/* 地点 */}
            <div className="flex items-center gap-1 text-sm text-surface-500">
              <MapPin size={14} />
              <input
                value={activeScene.location}
                onChange={(e) =>
                  updateScene(activeScene.id, { location: e.target.value })
                }
                className="bg-transparent border-none outline-none w-28 placeholder:text-surface-300 text-sm"
                placeholder="地点"
              />
            </div>

            {/* 时间 */}
            <div className="flex items-center gap-1">
              <Clock size={14} className="text-surface-400" />
              <select
                value={activeScene.timeOfDay}
                onChange={(e) =>
                  updateScene(activeScene.id, {
                    timeOfDay: e.target.value as ScriptScene["timeOfDay"],
                  })
                }
                className="text-xs bg-surface-50 border border-surface-200 rounded px-2 py-1 outline-none focus:border-primary-300"
              >
                {TIME_OPTIONS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.icon} {t.label}
                  </option>
                ))}
              </select>
            </div>

            {/* 内外景 */}
            <label className="flex items-center gap-1 text-xs text-surface-500 cursor-pointer">
              <input
                type="checkbox"
                checked={activeScene.interior}
                onChange={(e) =>
                  updateScene(activeScene.id, { interior: e.target.checked })
                }
                className="rounded border-surface-300 text-primary-600 focus:ring-primary-500"
              />
              内景
            </label>
          </div>
        </div>

        {/* 对白列表 */}
        <div className="space-y-1">
          {activeScene.dialogues.map((line, idx) => (
            <DialogueBlock
              key={line.id}
              line={line}
              sceneId={activeScene.id}
              onUpdate={(lineId, data) =>
                updateDialogueLine(activeScene.id, lineId, data)
              }
              onDelete={(lineId) => deleteDialogueLine(activeScene.id, lineId)}
              onAddAfter={(lineId, type) => {
                const afterIndex = activeScene.dialogues.findIndex(
                  (d) => d.id === lineId
                );
                addDialogueLine(activeScene.id, type, afterIndex);
              }}
            />
          ))}

          {/* 添加新行按钮 */}
          <div className="flex items-center gap-1 pt-1">
            <button
              onClick={() => addDialogueLine(activeScene.id, "dialogue")}
              className="text-[11px] text-primary-500 hover:text-primary-700 hover:bg-primary-50 px-2 py-1 rounded transition-colors"
            >
              + 对白
            </button>
            <button
              onClick={() => addDialogueLine(activeScene.id, "action")}
              className="text-[11px] text-gray-500 hover:text-gray-700 hover:bg-gray-50 px-2 py-1 rounded transition-colors"
            >
              + 动作
            </button>
            <button
              onClick={() => addDialogueLine(activeScene.id, "narration")}
              className="text-[11px] text-purple-500 hover:text-purple-700 hover:bg-purple-50 px-2 py-1 rounded transition-colors"
            >
              + 旁白
            </button>
          </div>
        </div>
      </div>

      {/* ---- 底部状态栏 ---- */}
      <div className="flex items-center justify-between px-4 py-1.5 border-t border-surface-200 bg-surface-50 text-[11px] text-surface-400 flex-shrink-0">
        <div className="flex items-center gap-3">
          <span>
            场景 <strong className="text-surface-600">{stats.sceneCount}</strong>
          </span>
          <span>
            对白 <strong className="text-surface-600">{stats.dialogueCount}</strong>
          </span>
          <span>
            动作 <strong className="text-surface-600">{stats.actionCount}</strong>
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span>
            总字数 <strong className="text-surface-600">{stats.totalChars}</strong>
          </span>
          <span className="hidden sm:inline text-surface-300">Ctrl+S 保存</span>
        </div>
      </div>
    </div>
  );
}

export default ScriptEditor;
