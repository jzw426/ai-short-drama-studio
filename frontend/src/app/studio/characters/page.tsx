"use client";

import { useCallback, useEffect, useState } from "react";
import { CharacterCard, Character } from "@/components/CharacterCard";
import { Plus, Sparkles, Search, X, Loader2 } from "lucide-react";
import { characterApi } from "@/lib/api";
import { useProjectStore } from "@/store/useProjectStore";
import { toast } from "sonner";

const traitColors: Record<string, string> = {
  执着: "bg-blue-100 text-blue-700",
  冷静: "bg-indigo-100 text-indigo-700",
  创业: "bg-purple-100 text-purple-700",
  重情义: "bg-pink-100 text-pink-700",
  温柔: "bg-green-100 text-green-700",
  独立: "bg-teal-100 text-teal-700",
  设计师: "bg-cyan-100 text-cyan-700",
  善良: "bg-lime-100 text-lime-700",
  野心: "bg-red-100 text-red-700",
  狡猾: "bg-orange-100 text-orange-700",
  商人: "bg-amber-100 text-amber-700",
  复仇: "bg-rose-100 text-rose-700",
  勇敢: "bg-blue-100 text-blue-700",
  聪明: "bg-indigo-100 text-indigo-700",
  幽默: "bg-yellow-100 text-yellow-700",
  神秘: "bg-purple-100 text-purple-700",
  冷酷: "bg-slate-100 text-slate-700",
  善良温柔: "bg-green-100 text-green-700",
};

interface CreateForm {
  name: string;
  role: string;
  description: string;
  voice: string;
  age: string;
  gender: string;
  traits: string;
}

const EMPTY_FORM: CreateForm = {
  name: "",
  role: "",
  description: "",
  voice: "",
  age: "",
  gender: "male",
  traits: "",
};

export default function CharactersPage() {
  const currentProject = useProjectStore((s) => s.currentProject);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const [aiDescription, setAiDescription] = useState("");
  const [aiGenerating, setAiGenerating] = useState(false);
  const [generatingId, setGeneratingId] = useState<string | null>(null);

  const projectId = currentProject?.id ?? null;

  const loadCharacters = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const data = (await characterApi.list(projectId)) as unknown as Character[];
      setCharacters(Array.isArray(data) ? data : []);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "加载角色失败");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (projectId) loadCharacters();
  }, [projectId, loadCharacters]);

  const filtered = characters.filter(
    (c) =>
      !searchTerm ||
      c.name.includes(searchTerm) ||
      c.role.includes(searchTerm) ||
      c.description.includes(searchTerm)
  );

  const handleCreate = async () => {
    if (!projectId) return;
    if (!form.name.trim()) {
      toast.error("请填写角色名");
      return;
    }
    try {
      const payload: Record<string, unknown> = {
        name: form.name.trim(),
        role: form.role.trim() || "配角",
        description: form.description.trim(),
      };
      if (form.voice.trim()) payload.voice = form.voice.trim();
      if (form.age) payload.age = parseInt(form.age, 10) || 0;
      if (form.gender) payload.gender = form.gender;
      if (form.traits.trim()) {
        payload.traits = form.traits
          .split(/[,，、\s]+/)
          .filter(Boolean);
      }
      await characterApi.create(projectId, payload);
      toast.success("角色已创建");
      setShowCreate(false);
      setForm(EMPTY_FORM);
      loadCharacters();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "创建失败");
    }
  };

  const handleAIGenerate = async () => {
    if (!projectId) return;
    if (!aiDescription.trim()) {
      toast.error("请描述你想生成的角色的特征");
      return;
    }
    setAiGenerating(true);
    try {
      await characterApi.aiGenerate(projectId, aiDescription.trim());
      toast.success("AI 角色已生成");
      setAiDescription("");
      loadCharacters();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "AI 生成失败");
    } finally {
      setAiGenerating(false);
    }
  };

  const handleGenerateImage = async (characterId: string) => {
    if (!projectId) return;
    setGeneratingId(characterId);
    try {
      await characterApi.generateImage(projectId, characterId);
      toast.success("形象已生成并追加");
      loadCharacters();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "形象生成失败");
    } finally {
      setGeneratingId(null);
    }
  };

  const handleDelete = async (characterId: string) => {
    if (!projectId) return;
    if (!window.confirm("确定删除该角色？")) return;
    try {
      await characterApi.delete(projectId, characterId);
      toast.success("角色已删除");
      loadCharacters();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  if (!currentProject) {
    return (
      <div className="max-w-7xl mx-auto">
        <div className="card p-10 text-center text-surface-400">
          请先在首页新建或选择一个项目，再进行角色管理
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">角色管理</h1>
          <p className="text-surface-500 mt-1">
            项目《{currentProject.title}》· 创建和管理角色，AI 生成角色形象
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => setShowCreate((v) => !v)}
            className="btn-outline flex items-center gap-2"
          >
            <Plus size={16} />
            新建角色
          </button>
        </div>
      </div>

      {/* AI 生成 */}
      <div className="card p-4 flex gap-3 items-center flex-wrap">
        <Sparkles size={18} className="text-primary-500 flex-shrink-0" />
        <input
          type="text"
          value={aiDescription}
          onChange={(e) => setAiDescription(e.target.value)}
          placeholder="描述你想 AI 生成的角色，如：25岁天才黑客少女，性格倔强，喜欢穿黑色卫衣..."
          className="input-field flex-1 min-w-[260px]"
        />
        <button
          onClick={handleAIGenerate}
          disabled={aiGenerating}
          className="btn-primary flex items-center gap-2 disabled:opacity-60"
        >
          {aiGenerating ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Sparkles size={16} />
          )}
          {aiGenerating ? "生成中..." : "AI 生成角色"}
        </button>
      </div>

      {/* 新建角色表单 */}
      {showCreate && (
        <div className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-surface-800">新建角色</h2>
            <button
              onClick={() => setShowCreate(false)}
              className="p-1 rounded-md hover:bg-surface-100 text-surface-400"
            >
              <X size={16} />
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-surface-500 mb-1">角色名 *</label>
              <input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="如：林小满"
                className="input-field"
              />
            </div>
            <div>
              <label className="block text-xs text-surface-500 mb-1">定位</label>
              <input
                value={form.role}
                onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
                placeholder="如：女主角"
                className="input-field"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs text-surface-500 mb-1">角色描述</label>
              <textarea
                value={form.description}
                onChange={(e) =>
                  setForm((f) => ({ ...f, description: e.target.value }))
                }
                placeholder="性格、背景、外貌等"
                rows={3}
                className="input-field resize-none"
              />
            </div>
            <div>
              <label className="block text-xs text-surface-500 mb-1">声线</label>
              <input
                value={form.voice}
                onChange={(e) => setForm((f) => ({ ...f, voice: e.target.value }))}
                placeholder="如：青年女声·温柔"
                className="input-field"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-surface-500 mb-1">年龄</label>
                <input
                  type="number"
                  value={form.age}
                  onChange={(e) => setForm((f) => ({ ...f, age: e.target.value }))}
                  placeholder="如：22"
                  className="input-field"
                />
              </div>
              <div>
                <label className="block text-xs text-surface-500 mb-1">性别</label>
                <select
                  value={form.gender}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, gender: e.target.value }))
                  }
                  className="input-field"
                >
                  <option value="male">男</option>
                  <option value="female">女</option>
                  <option value="other">其他</option>
                </select>
              </div>
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs text-surface-500 mb-1">
                性格标签（逗号分隔）
              </label>
              <input
                value={form.traits}
                onChange={(e) => setForm((f) => ({ ...f, traits: e.target.value }))}
                placeholder="如：执着, 冷静, 重情义"
                className="input-field"
              />
            </div>
          </div>
          <div className="flex justify-end gap-3 mt-4">
            <button
              onClick={() => setShowCreate(false)}
              className="btn-outline"
            >
              取消
            </button>
            <button onClick={handleCreate} className="btn-primary">
              创建角色
            </button>
          </div>
        </div>
      )}

      {/* 搜索 */}
      <div className="relative max-w-md">
        <Search
          size={18}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-surface-400"
        />
        <input
          type="text"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder="搜索角色名称、定位..."
          className="input-field pl-10"
        />
      </div>

      {/* 角色网格 */}
      {loading ? (
        <div className="flex items-center justify-center py-16 text-surface-400">
          <Loader2 size={20} className="animate-spin mr-2" />
          加载中...
        </div>
      ) : filtered.length === 0 ? (
        <div className="card p-10 text-center text-surface-400">
          {characters.length === 0
            ? "还没有角色，点击上方按钮新建或 AI 生成"
            : "没有匹配的角色"}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((character) => (
            <CharacterCard
              key={character.id}
              character={character}
              traitColors={traitColors}
              onGenerateImage={handleGenerateImage}
              onDelete={handleDelete}
              generating={generatingId === character.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}
