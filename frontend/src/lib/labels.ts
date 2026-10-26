/**
 * 后端枚举值 → 中文标签。
 *
 * 后端字段都是自由文本（role str50 / gender str20 / time_of_day str50），
 * 这里只做展示映射，未知值原样展示，绝不丢数据。
 */

export const ROLE_OPTIONS = ["主角", "反派", "配角", "群演"] as const;

const ROLE_LABELS: Record<string, string> = {
  protagonist: "主角",
  antagonist: "反派",
  supporting: "配角",
  extra: "群演",
};

export function roleLabel(role?: string | null): string {
  if (!role) return "配角";
  return ROLE_LABELS[role] ?? role;
}

export const GENDER_OPTIONS: { value: string; label: string }[] = [
  { value: "male", label: "男" },
  { value: "female", label: "女" },
  { value: "other", label: "其他" },
];

export function genderLabel(gender?: string | null): string {
  switch (gender) {
    case "male":
      return "男";
    case "female":
      return "女";
    case "other":
      return "其他";
    default:
      return gender || "未知";
  }
}

/** 时段是自由文本，只提供输入建议 */
export const TIME_OF_DAY_SUGGESTIONS = ["day", "night", "morning", "evening"];

/** 景别建议（AI 返回中文，也允许手填） */
export const CAMERA_ANGLE_SUGGESTIONS = ["全景", "中景", "近景", "特写"];

/** 转场建议（AI 返回中文，也允许手填） */
export const TRANSITION_SUGGESTIONS = ["硬切", "淡入", "溶解", "划像"];
