"use client";

import { User, Edit2, Mic, MoreHorizontal, ImagePlus, Loader2 } from "lucide-react";

/** 与后端 CharacterResponse 字段对齐（snake_case） */
export interface Character {
  id: string;
  name: string;
  role: string;
  description: string;
  avatar_url: string | null;
  voice: string;
  age: number;
  traits: string[];
  gender: "male" | "female" | "other";
  backstory: string;
  generated_images?: string[];
}

interface CharacterCardProps {
  character: Character;
  traitColors: Record<string, string>;
  onGenerateImage?: (characterId: string) => void;
  onDelete?: (characterId: string) => void;
  generating?: boolean;
}

export function CharacterCard({
  character,
  traitColors,
  onGenerateImage,
  onDelete,
  generating,
}: CharacterCardProps) {
  return (
    <div className="card p-5 group">
      <div className="flex items-start justify-between mb-3">
        {/* 头像 */}
        <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-primary-100 to-primary-200 flex items-center justify-center overflow-hidden">
          {character.avatar_url ? (
            <img
              src={character.avatar_url}
              alt={character.name}
              className="w-full h-full rounded-xl object-cover"
            />
          ) : (
            <User size={26} className="text-primary-500" />
          )}
        </div>
        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {onGenerateImage && (
            <button
              onClick={() => onGenerateImage(character.id)}
              disabled={generating}
              title="AI 生成形象"
              className="p-1.5 rounded-md hover:bg-surface-100 text-surface-400 hover:text-primary-600 disabled:opacity-50"
            >
              {generating ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <ImagePlus size={14} />
              )}
            </button>
          )}
          <button className="p-1.5 rounded-md hover:bg-surface-100 text-surface-400 hover:text-primary-600">
            <Edit2 size={14} />
          </button>
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
        <span className="text-xs text-primary-600 font-medium bg-primary-50 px-2 py-0.5 rounded-full">
          {character.role}
        </span>
      </div>

      {/* 描述 */}
      <p className="text-sm text-surface-500 line-clamp-3 mb-3">
        {character.description}
      </p>

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
