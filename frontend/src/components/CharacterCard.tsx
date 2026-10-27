"use client";

import {
  User,
  Edit2,
  Mic,
  MoreHorizontal,
  ImagePlus,
  Loader2,
  Fingerprint,
} from "lucide-react";

import { mediaUrl, type CharacterDto } from "@/lib/api";
import { roleLabel } from "@/lib/labels";

/** 与后端 CharacterResponse 字段对齐（snake_case） */
export type Character = CharacterDto;

/** 三视图视角顺序与中文名（与后端 VIEW_PROMPTS 保持一致） */
export const VIEW_LABELS: { key: string; label: string }[] = [
  { key: "front", label: "正面" },
  { key: "side", label: "侧面" },
  { key: "full", label: "全身" },
  { key: "back", label: "背面" },
];

interface CharacterCardProps {
  character: Character;
  traitColors: Record<string, string>;
  onEdit?: (characterId: string) => void;
  onGenerateImage?: (characterId: string) => void;
  onDelete?: (characterId: string) => void;
  /** 打开「一致性」面板：锁脸 / seed / 三视图 */
  onConsistency?: (characterId: string) => void;
  generating?: boolean;
}

export function CharacterCard({
  character,
  traitColors,
  onEdit,
  onGenerateImage,
  onDelete,
  onConsistency,
  generating,
}: CharacterCardProps) {
  const views = character.view_images ?? {};
  const viewEntries = VIEW_LABELS.filter((v) => views[v.key]);
  const locked = Boolean(character.reference_image_url);

  return (
    <div className="card p-5 group">
      <div className="flex items-start justify-between mb-3">
        {/* 头像 */}
        <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-primary-100 to-primary-200 flex items-center justify-center overflow-hidden">
          {character.avatar_url ? (
            <img
              src={mediaUrl(character.avatar_url)}
              alt={character.name}
              className="w-full h-full rounded-xl object-cover"
            />
          ) : (
            <User size={26} className="text-primary-500" />
          )}
        </div>
        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {onConsistency && (
            <button
              onClick={() => onConsistency(character.id)}
              title="一致性：锁脸 / 种子 / 三视图"
              className="p-1.5 rounded-md hover:bg-surface-100 text-surface-400 hover:text-primary-600"
            >
              <Fingerprint size={14} />
            </button>
          )}
          {onGenerateImage && (
            <button
              onClick={() => onGenerateImage(character.id)}
              disabled={generating}
              title={locked ? "按锁定形象重新出图" : "AI 生成形象"}
              className="p-1.5 rounded-md hover:bg-surface-100 text-surface-400 hover:text-primary-600 disabled:opacity-50"
            >
              {generating ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <ImagePlus size={14} />
              )}
            </button>
          )}
          {onEdit && (
            <button
              onClick={() => onEdit(character.id)}
              title="编辑角色"
              className="p-1.5 rounded-md hover:bg-surface-100 text-surface-400 hover:text-primary-600"
            >
              <Edit2 size={14} />
            </button>
          )}
          {onDelete && (
            <button
              onClick={() => onDelete(character.id)}
              title="删除角色"
              className="p-1.5 rounded-md hover:bg-surface-100 text-surface-400 hover:text-red-600"
            >
              <MoreHorizontal size={14} />
            </button>
          )}
        </div>
      </div>

      {/* 姓名和角色 */}
      <div className="mb-2">
        <h3 className="font-semibold text-surface-800 text-lg">
          {character.name}
        </h3>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-primary-600 font-medium bg-primary-50 px-2 py-0.5 rounded-full">
            {roleLabel(character.role)}
          </span>
          {locked ? (
            <span
              className="text-xs text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full"
              title={`seed ${character.image_seed ?? "-"} · 出图走参考图图生图`}
            >
              已锁脸 · seed {character.image_seed ?? "-"}
            </span>
          ) : (
            <span
              className="text-xs text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full"
              title="未锁脸时每次出图都是独立随机，人物长相会变"
            >
              未锁脸
            </span>
          )}
        </div>
      </div>

      {/* 描述 */}
      <p className="text-sm text-surface-500 line-clamp-3 mb-3">
        {character.description}
      </p>

      {/* 三视图缩略图 */}
      {viewEntries.length > 0 && (
        <div className="flex gap-1.5 mb-3">
          {viewEntries.map((v) => (
            <div key={v.key} className="w-11 h-11 rounded-md overflow-hidden bg-surface-100">
              <img
                src={mediaUrl(views[v.key])}
                alt={`${character.name} ${v.label}`}
                title={v.label}
                className="w-full h-full object-cover"
              />
            </div>
          ))}
        </div>
      )}

      {/* 标签 */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {(character.traits || []).map((trait) => (
          <span
            key={trait}
            className={`text-xs px-2 py-0.5 rounded-full ${
              traitColors[trait] || "bg-surface-100 text-surface-600"
            }`}
          >
            {trait}
          </span>
        ))}
      </div>

      {/* 底部信息 */}
      <div className="flex items-center justify-between pt-3 border-t border-surface-100">
        <div className="flex items-center gap-1.5 text-xs text-surface-400">
          <Mic size={13} />
          <span>{character.voice || "未设置"}</span>
        </div>
        <span className="text-xs text-surface-400">
          {character.age ? `${character.age}岁` : "年龄未知"}
        </span>
      </div>
    </div>
  );
}
