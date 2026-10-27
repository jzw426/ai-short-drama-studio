"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Fingerprint,
  Images,
  Loader2,
  Plus,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { toast } from "sonner";

import {
  CharacterCard,
  VIEW_LABELS,
  type Character,
} from "@/components/CharacterCard";
import { characterApi, mediaUrl } from "@/lib/api";
import { GENDER_OPTIONS, ROLE_OPTIONS, roleLabel } from "@/lib/labels";
import { useCurrentProject } from "@/lib/useCurrentProject";

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
};

interface CharacterForm {
  name: string;
  role: string;
  description: string;
  voice: string;
  age: string;
  gender: string;
  traits: string;
  backstory: string;
}

const EMPTY_FORM: CharacterForm = {
  name: "",
  role: "配角",
  description: "",
  voice: "",
  age: "",
  gender: "other",
  traits: "",
  backstory: "",
};

function parseTraits(raw: string): string[] {
  return raw
    .split(/[,，、\s]+/)
    .map((t) => t.trim())
    .filter(Boolean);
}

export default function CharactersPage() {
  const { project, loading: projectLoading, error: projectError } = useCurrentProject();
  const projectId = project?.id ?? null;

  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Character | null>(null);
  const [form, setForm] = useState<CharacterForm>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);

  const [aiDescription, setAiDescription] = useState("");
  const [aiGenerating, setAiGenerating] = useState(false);
  const [generatingId, setGeneratingId] = useState<string | null>(null);

  // 一致性面板：锁脸 / seed / 三视图
  const [consistencyId, setConsistencyId] = useState<string | null>(null);
  const [seedInput, setSeedInput] = useState("");
  const [promptInput, setPromptInput] = useState("");
  const [locking, setLocking] = useState(false);
  const [viewsGenerating, setViewsGenerating] = useState(false);
  const [viewSelection, setViewSelection] = useState<string[]>([
    "front",
    "side",
    "full",
  ]);

  const loadCharacters = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const data = (await characterApi.list(projectId)) as unknown as Character[];
      setCharacters(Array.isArray(data) ? data : []);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "加载角色失败";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (projectId) void loadCharacters();
    else {
      setCharacters([]);
      setError(null);
    }
  }, [projectId, loadCharacters]);

  const filtered = useMemo(() => {
    const keyword = searchTerm.trim();
    if (!keyword) return characters;
    return characters.filter(
      (c) =>
        c.name.includes(keyword) ||
        roleLabel(c.role).includes(keyword) ||
        c.role.includes(keyword) ||
        c.description.includes(keyword) ||
        (c.traits ?? []).some((t) => t.includes(keyword))
    );
  }, [characters, searchTerm]);

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormOpen(true);
  };

  const openEdit = (character: Character) => {
    setEditing(character);
    setForm({
      name: character.name,
      role: character.role || "配角",
      description: character.description ?? "",
      voice: character.voice ?? "",
      age: character.age ? String(character.age) : "",
      gender: character.gender || "other",
      traits: (character.traits ?? []).join("、"),
      backstory: character.backstory ?? "",
    });
    setFormOpen(true);
  };

  const closeForm = () => {
    if (submitting) return;
    setFormOpen(false);
    setEditing(null);
  };

  const handleSubmit = async () => {
    if (!projectId || submitting) return;
    if (!form.name.trim()) {
      toast.error("请填写角色名");
      return;
    }
    const payload = {
      name: form.name.trim(),
      role: form.role.trim() || "配角",
      description: form.description.trim(),
      voice: form.voice.trim(),
      age: Math.max(0, Math.round(Number(form.age) || 0)),
      gender: form.gender || "other",
      traits: parseTraits(form.traits),
      backstory: form.backstory.trim(),
    };
    setSubmitting(true);
    try {
      if (editing) {
        await characterApi.update(projectId, editing.id, payload);
        toast.success("角色已更新");
      } else {
        await characterApi.create(projectId, payload);
        toast.success("角色已创建");
      }
      setFormOpen(false);
      setEditing(null);
      await loadCharacters();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : editing ? "更新失败" : "创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (characterId: string) => {
    if (!projectId) return;
    const target = characters.find((c) => c.id === characterId);
    if (!window.confirm(`确定删除角色"${target?.name ?? ""}"？`)) return;
    try {
      await characterApi.delete(projectId, characterId);
      toast.success("角色已删除");
      await loadCharacters();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  const handleAIGenerate = async () => {
    if (!projectId || aiGenerating) return;
    const description = aiDescription.trim();
    if (!description) {
      toast.error("请描述你想生成的角色的特征");
      return;
    }
    setAiGenerating(true);
    try {
      await characterApi.aiGenerate(projectId, description);
      toast.success("AI 角色已生成");
      setAiDescription("");
      await loadCharacters();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "AI 生成失败");
    } finally {
      setAiGenerating(false);
    }
  };

  const handleGenerateImage = async (characterId: string) => {
    if (!projectId || generatingId) return;
    setGeneratingId(characterId);
    try {
      await characterApi.generateImage(projectId, characterId);
      toast.success("角色形象已生成");
      await loadCharacters();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "形象生成失败");
    } finally {
      setGeneratingId(null);
    }
  };

  const consistencyChar = consistencyId
    ? characters.find((c) => c.id === consistencyId) ?? null
    : null;

  const openConsistency = (characterId: string) => {
    const target = characters.find((c) => c.id === characterId);
    setConsistencyId(characterId);
    setSeedInput(target?.image_seed != null ? String(target.image_seed) : "");
    setPromptInput(target?.visual_prompt ?? "");
  };

  const closeConsistency = () => {
    if (locking || viewsGenerating) return;
    setConsistencyId(null);
  };

  /** 锁脸：把基准图落到自有存储 + 固定 seed/外观描述。不调用 AI、不占配额。 */
  const handleLockFace = async () => {
    if (!projectId || !consistencyChar || locking) return;
    const source = consistencyChar.avatar_url || consistencyChar.reference_image_url;
    if (!source) {
      toast.error("这个角色还没有任何参考图，先点「AI 生成形象」或上传头像");
      return;
    }
    let seed: number | undefined;
    if (seedInput.trim()) {
      const parsed = Number(seedInput.trim());
      if (!Number.isInteger(parsed) || parsed < 0 || parsed > 4294967295) {
        toast.error("seed 必须是 0 ~ 4294967295 的整数");
        return;
      }
      seed = parsed;
    }
    setLocking(true);
    try {
      await characterApi.lockFace(projectId, consistencyChar.id, {
        source_url: source,
        ...(seed != null ? { seed } : {}),
        ...(promptInput.trim() ? { visual_prompt: promptInput.trim() } : {}),
      });
      toast.success(seed != null ? `已锁定形象 · seed ${seed}` : "已锁定形象");
      await loadCharacters();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "锁脸失败");
    } finally {
      setLocking(false);
    }
  };

  /** 三视图：逐视角调 AI（每视角消耗一次配额，失败由服务端退配额）。 */
  const handleGenerateViews = async () => {
    if (!projectId || !consistencyChar || viewsGenerating) return;
    if (!consistencyChar.reference_image_url) {
      toast.error("请先锁定形象，否则三个视角会是三个不同的人");
      return;
    }
    if (viewSelection.length === 0) {
      toast.error("至少选择一个视角");
      return;
    }
    setViewsGenerating(true);
    try {
      await characterApi.generateViews(projectId, consistencyChar.id, viewSelection);
      toast.success("三视图已生成");
      await loadCharacters();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "三视图生成失败");
    } finally {
      setViewsGenerating(false);
    }
  };

  const toggleView = (key: string) => {
    setViewSelection((prev) =>
      prev.includes(key) ? prev.filter((v) => v !== key) : [...prev, key]
    );
  };

  if (!project) {
    return (
      <div className="max-w-3xl mx-auto mt-20 card p-10 text-center space-y-4">
        <Sparkles size={36} className="mx-auto text-surface-300" />
        <p className="text-surface-500">
          {projectLoading
            ? "正在加载项目列表…"
            : projectError ?? "先在首页新建或选择一个项目，再回来管理角色。"}
        </p>
        <Link href="/" className="btn-primary inline-flex">
          去选择项目
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">角色管理</h1>
          <p className="text-sm text-surface-500 mt-1">
            当前项目：{project.title} · 共 {characters.length} 个角色
          </p>
        </div>
        <button
          onClick={openCreate}
          className="btn-primary flex items-center gap-2 text-sm"
        >
          <Plus size={16} />
          新建角色
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => void loadCharacters()} className="text-xs underline">
            重试
          </button>
        </div>
      )}

      {/* AI 生成角色 */}
      <div className="card p-5 space-y-3">
        <div className="flex items-center gap-2">
          <Sparkles size={18} className="text-primary-600" />
          <h2 className="font-medium text-surface-800">AI 生成角色</h2>
          <span className="text-xs text-surface-400">
            描述角色特征，AI 生成设定与形象（消耗配额）
          </span>
        </div>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            value={aiDescription}
            onChange={(e) => setAiDescription(e.target.value)}
            placeholder="例如：28 岁女律师，冷静理性，因一场旧案与男主重逢"
            maxLength={5000}
            className="input-field flex-1"
            onKeyDown={(e) => {
              if (e.key === "Enter") void handleAIGenerate();
            }}
          />
          <button
            onClick={() => void handleAIGenerate()}
            disabled={aiGenerating || !aiDescription.trim()}
            className="btn-primary flex items-center justify-center gap-2 text-sm disabled:opacity-60"
          >
            {aiGenerating ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Sparkles size={16} />
            )}
            {aiGenerating ? "生成中…" : "生成角色"}
          </button>
        </div>
      </div>

      {/* 搜索 */}
      {characters.length > 0 && (
        <div className="relative max-w-sm">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-surface-400"
          />
          <input
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="搜索角色名、定位、特质…"
            className="input-field w-full pl-9"
          />
        </div>
      )}

      {loading && characters.length === 0 ? (
        <div className="card p-10 flex items-center justify-center gap-2 text-sm text-surface-500">
          <Loader2 size={16} className="animate-spin" />
          加载角色中…
        </div>
      ) : characters.length === 0 ? (
        <div className="card p-10 text-center space-y-3">
          <Sparkles size={30} className="mx-auto text-surface-300" />
          <p className="text-surface-500">还没有角色</p>
          <p className="text-xs text-surface-400">
            用上方 AI 生成，或点击「新建角色」手动创建
          </p>
          <button onClick={openCreate} className="btn-outline inline-flex items-center gap-2 text-sm">
            <Plus size={14} />
            新建角色
          </button>
        </div>
      ) : filtered.length === 0 ? (
        <div className="card p-10 text-center space-y-3">
          <p className="text-surface-500">没有匹配「{searchTerm}」的角色</p>
          <button onClick={() => setSearchTerm("")} className="btn-outline text-sm">
            清除搜索
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filtered.map((character) => (
            <CharacterCard
              key={character.id}
              character={character}
              traitColors={traitColors}
              onEdit={() => openEdit(character)}
              onDelete={handleDelete}
              onGenerateImage={handleGenerateImage}
              onConsistency={openConsistency}
              generating={generatingId === character.id}
            />
          ))}
        </div>
      )}

      {/* 一致性面板：锁脸 / seed / 三视图 */}
      {consistencyChar && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={closeConsistency}
        >
          <div
            className="card w-full max-w-2xl max-h-[90vh] overflow-y-auto p-5 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Fingerprint size={18} className="text-primary-600" />
                <h2 className="font-semibold text-surface-800">
                  角色一致性 · {consistencyChar.name}
                </h2>
              </div>
              <button
                onClick={closeConsistency}
                className="p-1.5 rounded-md hover:bg-surface-100 text-surface-400"
                title="关闭"
              >
                <X size={16} />
              </button>
            </div>

            <p className="text-xs text-surface-500 leading-relaxed">
              锁脸会把当前形象保存为基准图，并固定 <code>seed</code> 与外观描述；
              之后每次出图都走「参考图 + 同 seed」的图生图，角色才不会一集换一张脸。
              锁脸本身不调用 AI、不消耗配额；三视图每生成一个视角消耗一次 AI 配额。
            </p>

            <div className="flex gap-4">
              <div className="w-28 h-28 flex-shrink-0 rounded-lg overflow-hidden bg-surface-100 flex items-center justify-center">
                {consistencyChar.reference_image_url || consistencyChar.avatar_url ? (
                  <img
                    src={mediaUrl(
                      consistencyChar.reference_image_url || consistencyChar.avatar_url
                    )}
                    alt={consistencyChar.name}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <Sparkles size={26} className="text-surface-300" />
                )}
              </div>
              <div className="flex-1 space-y-2">
                <label className="space-y-1 block">
                  <span className="text-xs text-surface-500">
                    seed（留空则自动随机一次，之后固定不变）
                  </span>
                  <input
                    value={seedInput}
                    onChange={(e) => setSeedInput(e.target.value)}
                    inputMode="numeric"
                    placeholder={
                      consistencyChar.image_seed != null
                        ? String(consistencyChar.image_seed)
                        : "例如 123456"
                    }
                    className="input-field w-full"
                  />
                </label>
                <label className="space-y-1 block">
                  <span className="text-xs text-surface-500">
                    外观描述（只写长相/发型/服装，不要写剧情）
                  </span>
                  <textarea
                    value={promptInput}
                    onChange={(e) => setPromptInput(e.target.value)}
                    rows={3}
                    maxLength={2000}
                    placeholder="例如：黑长直，红风衣，丹凤眼，二十五六岁"
                    className="input-field w-full resize-y"
                  />
                </label>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2">
              <button
                onClick={() => void handleLockFace()}
                disabled={locking}
                className="btn-primary flex items-center gap-2 text-sm disabled:opacity-60"
              >
                {locking ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Fingerprint size={14} />
                )}
                {consistencyChar.reference_image_url ? "重新锁定" : "锁定形象"}
              </button>
            </div>

            <div className="pt-3 border-t border-surface-100 space-y-3">
              <div className="flex items-center gap-2">
                <Images size={16} className="text-primary-600" />
                <h3 className="font-medium text-surface-800 text-sm">三视图</h3>
                <span className="text-xs text-surface-400">
                  每视角一次 AI 调用（消耗配额）
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {VIEW_LABELS.map((v) => {
                  const active = viewSelection.includes(v.key);
                  return (
                    <button
                      key={v.key}
                      onClick={() => toggleView(v.key)}
                      className={`text-xs px-2.5 py-1 rounded-full border ${
                        active
                          ? "border-primary-300 bg-primary-50 text-primary-700"
                          : "border-surface-200 text-surface-500"
                      }`}
                    >
                      {v.label}
                    </button>
                  );
                })}
              </div>
              <div className="grid grid-cols-4 gap-2">
                {VIEW_LABELS.map((v) => (
                  <div key={v.key} className="space-y-1">
                    <div className="aspect-[3/4] rounded-md overflow-hidden bg-surface-100 flex items-center justify-center">
                      {consistencyChar.view_images?.[v.key] ? (
                        <img
                          src={mediaUrl(consistencyChar.view_images[v.key])}
                          alt={`${consistencyChar.name} ${v.label}`}
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <span className="text-[10px] text-surface-400">未生成</span>
                      )}
                    </div>
                    <p className="text-[11px] text-center text-surface-500">{v.label}</p>
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-end">
                <button
                  onClick={() => void handleGenerateViews()}
                  disabled={viewsGenerating}
                  className="btn-outline flex items-center gap-2 text-sm disabled:opacity-60"
                >
                  {viewsGenerating ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Images size={14} />
                  )}
                  {viewsGenerating ? "生成中…" : "生成所选视角"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 新建 / 编辑弹窗 */}
      {formOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={closeForm}
        >
          <div
            className="card w-full max-w-2xl max-h-[90vh] overflow-y-auto p-5 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-surface-800">
                {editing ? `编辑角色 · ${editing.name}` : "新建角色"}
              </h2>
              <button
                onClick={closeForm}
                className="p-1.5 rounded-md hover:bg-surface-100 text-surface-400"
                title="关闭"
              >
                <X size={16} />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <label className="space-y-1 block">
                <span className="text-xs text-surface-500">角色名 *</span>
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="角色姓名"
                  className="input-field w-full"
                />
              </label>
              <label className="space-y-1 block">
                <span className="text-xs text-surface-500">角色定位</span>
                <select
                  value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}
                  className="input-field w-full"
                >
                  {ROLE_OPTIONS.map((role) => (
                    <option key={role} value={role}>
                      {role}
                    </option>
                  ))}
                  {form.role &&
                    !ROLE_OPTIONS.includes(form.role as (typeof ROLE_OPTIONS)[number]) && (
                      <option value={form.role}>{roleLabel(form.role)}</option>
                    )}
                </select>
              </label>
              <label className="space-y-1 block">
                <span className="text-xs text-surface-500">性别</span>
                <select
                  value={form.gender}
                  onChange={(e) => setForm({ ...form, gender: e.target.value })}
                  className="input-field w-full"
                >
                  {GENDER_OPTIONS.map((g) => (
                    <option key={g.value} value={g.value}>
                      {g.label}
                    </option>
                  ))}
                  {form.gender &&
                    !GENDER_OPTIONS.some((g) => g.value === form.gender) && (
                      <option value={form.gender}>{form.gender}</option>
                    )}
                </select>
              </label>
              <label className="space-y-1 block">
                <span className="text-xs text-surface-500">年龄</span>
                <input
                  type="number"
                  min={0}
                  value={form.age}
                  onChange={(e) => setForm({ ...form, age: e.target.value })}
                  placeholder="0 表示未设置"
                  className="input-field w-full"
                />
              </label>
              <label className="space-y-1 block">
                <span className="text-xs text-surface-500">音色</span>
                <input
                  value={form.voice}
                  onChange={(e) => setForm({ ...form, voice: e.target.value })}
                  placeholder="例如：低沉磁性"
                  className="input-field w-full"
                />
              </label>
              <label className="space-y-1 block">
                <span className="text-xs text-surface-500">特质（用逗号分隔）</span>
                <input
                  value={form.traits}
                  onChange={(e) => setForm({ ...form, traits: e.target.value })}
                  placeholder="冷静、执着、重情义"
                  className="input-field w-full"
                />
              </label>
            </div>

            <label className="space-y-1 block">
              <span className="text-xs text-surface-500">角色描述</span>
              <textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                rows={3}
                placeholder="外貌、性格、人物关系…"
                className="input-field w-full resize-y"
              />
            </label>

            <label className="space-y-1 block">
              <span className="text-xs text-surface-500">背景故事</span>
              <textarea
                value={form.backstory}
                onChange={(e) => setForm({ ...form, backstory: e.target.value })}
                rows={3}
                placeholder="角色的前史与动机（可选）"
                className="input-field w-full resize-y"
              />
            </label>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button onClick={closeForm} disabled={submitting} className="btn-outline text-sm">
                取消
              </button>
              <button
                onClick={() => void handleSubmit()}
                disabled={submitting || !form.name.trim()}
                className="btn-primary flex items-center gap-2 text-sm disabled:opacity-60"
              >
                {submitting && <Loader2 size={14} className="animate-spin" />}
                {editing ? "保存修改" : "创建角色"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
