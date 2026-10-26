import { create } from "zustand";
import type { Project } from "@/types";

// ===== 剧本编辑器本地类型 =====

export interface DialogueLine {
  id: string;
  type: "dialogue" | "action" | "narration";
  character?: string;
  content: string;
}

export interface ScriptScene {
  id: string;
  sceneNumber: number;
  title: string;
  location: string;
  timeOfDay: "morning" | "afternoon" | "evening" | "night";
  interior: boolean;
  dialogues: DialogueLine[];
  sortOrder: number;
}

// ===== 分镜画布本地类型 =====

export interface StoryboardObjectInfo {
  id: string;
  type: string;
  left: number;
  top: number;
  width: number;
  height: number;
  scaleX: number;
  scaleY: number;
  angle: number;
  opacity: number;
}

// ===== Store 接口 =====

interface ProjectState {
  currentProject: Project | null;
  projects: Project[];

  workflowSteps: {
    script: boolean;
    storyboard: boolean;
    characters: boolean;
    render: boolean;
  };

  scriptScenes: ScriptScene[];
  scriptSaveStatus: "idle" | "saved" | "unsaved" | "saving";
  scriptLoading: boolean;
  scriptError: string | null;

  storyboardCanvasState: string | null;
  storyboardUndoStack: string[];
  storyboardRedoStack: string[];
  storyboardSelectedObject: StoryboardObjectInfo | null;
  storyboardIsModified: boolean;

  sidebarCollapsed: boolean;

  setCurrentProject: (project: Project | null) => void;
  setProjects: (projects: Project[]) => void;
  addProject: (project: Project) => void;
  updateProject: (id: string, data: Partial<Project>) => void;
  removeProject: (id: string) => void;

  setWorkflowStep: (step: keyof ProjectState["workflowSteps"], completed: boolean) => void;

  setScriptScenes: (scenes: ScriptScene[]) => void;
  addScene: (afterIndex?: number) => void;
  updateScene: (sceneId: string, data: Partial<Omit<ScriptScene, "id" | "dialogues">>) => void;
  deleteScene: (sceneId: string) => void;
  reorderScenes: (fromIndex: number, toIndex: number) => void;
  addDialogueLine: (sceneId: string, type: DialogueLine["type"], afterIndex?: number) => void;
  updateDialogueLine: (sceneId: string, lineId: string, data: Partial<DialogueLine>) => void;
  deleteDialogueLine: (sceneId: string, lineId: string) => void;
  reorderDialogueLines: (sceneId: string, fromIndex: number, toIndex: number) => void;
  setScriptSaveStatus: (status: ProjectState["scriptSaveStatus"]) => void;
  setScriptLoading: (loading: boolean) => void;
  setScriptError: (error: string | null) => void;

  setStoryboardCanvasState: (state: string | null) => void;
  pushStoryboardUndo: (state: string) => void;
  undoStoryboard: () => string | null;
  redoStoryboard: () => string | null;
  clearStoryboardHistory: () => void;
  setStoryboardSelectedObject: (obj: StoryboardObjectInfo | null) => void;
  setStoryboardIsModified: (modified: boolean) => void;

  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
}

// ===== 内部工具 =====

let _idCounter = 0;
function generateId(): string {
  _idCounter += 1;
  return `${Date.now().toString(36)}_${_idCounter.toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function createEmptyScene(sceneNumber: number, sortOrder: number): ScriptScene {
  return {
    id: generateId(),
    sceneNumber,
    title: `场景 ${sceneNumber}`,
    location: "",
    timeOfDay: "morning",
    interior: true,
    dialogues: [
      {
        id: generateId(),
        type: "action",
        content: "（在此处添加场景描述或动作...）",
      },
    ],
    sortOrder,
  };
}

function renumberScenes(scenes: ScriptScene[]): ScriptScene[] {
  return scenes.map((s, i) => ({ ...s, sceneNumber: i + 1 }));
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  currentProject: null,
  projects: [],

  workflowSteps: {
    script: false,
    storyboard: false,
    characters: false,
    render: false,
  },

  scriptScenes: [],
  scriptSaveStatus: "idle",
  scriptLoading: false,
  scriptError: null,

  storyboardCanvasState: null,
  storyboardUndoStack: [],
  storyboardRedoStack: [],
  storyboardSelectedObject: null,
  storyboardIsModified: false,

  sidebarCollapsed: false,

  // ----- 项目 -----
  setCurrentProject: (project) =>
    set({
      currentProject: project,
      scriptScenes: [],
      scriptSaveStatus: "idle",
      scriptError: null,
      storyboardCanvasState: null,
      storyboardUndoStack: [],
      storyboardRedoStack: [],
      storyboardSelectedObject: null,
      storyboardIsModified: false,
    }),

  setProjects: (projects) => set({ projects }),

  addProject: (project) =>
    set((state) => ({ projects: [project, ...state.projects] })),

  updateProject: (id, data) =>
    set((state) => ({
      projects: state.projects.map((p) => (p.id === id ? { ...p, ...data } : p)),
      currentProject:
        state.currentProject?.id === id
          ? { ...state.currentProject, ...data }
          : state.currentProject,
    })),

  removeProject: (id) =>
    set((state) => ({
      projects: state.projects.filter((p) => p.id !== id),
      currentProject: state.currentProject?.id === id ? null : state.currentProject,
    })),

  // ----- 工作流 -----
  setWorkflowStep: (step, completed) =>
    set((state) => ({
      workflowSteps: { ...state.workflowSteps, [step]: completed },
    })),

  // ----- 剧本 -----
  setScriptScenes: (scenes) =>
    set({ scriptScenes: scenes, scriptSaveStatus: "saved" }),

  addScene: (afterIndex) =>
    set((state) => {
      const scenes = [...state.scriptScenes];
      const insertAt = afterIndex !== undefined ? afterIndex + 1 : scenes.length;
      const newScene = createEmptyScene(insertAt + 1, insertAt);
      scenes.splice(insertAt, 0, newScene);
      return { scriptScenes: renumberScenes(scenes), scriptSaveStatus: "unsaved" };
    }),

  updateScene: (sceneId, data) =>
    set((state) => ({
      scriptScenes: state.scriptScenes.map((s) =>
        s.id === sceneId ? { ...s, ...data } : s
      ),
      scriptSaveStatus: "unsaved",
    })),

  deleteScene: (sceneId) =>
    set((state) => {
      if (state.scriptScenes.length <= 1) return state;
      return {
        scriptScenes: renumberScenes(state.scriptScenes.filter((s) => s.id !== sceneId)),
        scriptSaveStatus: "unsaved",
      };
    }),

  reorderScenes: (fromIndex, toIndex) =>
    set((state) => {
      const scenes = [...state.scriptScenes];
      const [moved] = scenes.splice(fromIndex, 1);
      scenes.splice(toIndex, 0, moved);
      return { scriptScenes: renumberScenes(scenes), scriptSaveStatus: "unsaved" };
    }),

  addDialogueLine: (sceneId, type, afterIndex) =>
    set((state) => ({
      scriptScenes: state.scriptScenes.map((s) => {
        if (s.id !== sceneId) return s;
        const dialogues = [...s.dialogues];
        const insertAt = afterIndex !== undefined ? afterIndex + 1 : dialogues.length;
        dialogues.splice(insertAt, 0, {
          id: generateId(),
          type,
          character: type === "dialogue" ? "" : undefined,
          content: "",
        });
        return { ...s, dialogues };
      }),
      scriptSaveStatus: "unsaved",
    })),

  updateDialogueLine: (sceneId, lineId, data) =>
    set((state) => ({
      scriptScenes: state.scriptScenes.map((s) => {
        if (s.id !== sceneId) return s;
        return {
          ...s,
          dialogues: s.dialogues.map((d) =>
            d.id === lineId ? { ...d, ...data } : d
          ),
        };
      }),
      scriptSaveStatus: "unsaved",
    })),

  deleteDialogueLine: (sceneId, lineId) =>
    set((state) => ({
      scriptScenes: state.scriptScenes.map((s) => {
        if (s.id !== sceneId || s.dialogues.length <= 1) return s;
        return { ...s, dialogues: s.dialogues.filter((d) => d.id !== lineId) };
      }),
      scriptSaveStatus: "unsaved",
    })),

  reorderDialogueLines: (sceneId, fromIndex, toIndex) =>
    set((state) => ({
      scriptScenes: state.scriptScenes.map((s) => {
        if (s.id !== sceneId) return s;
        const dialogues = [...s.dialogues];
        const [moved] = dialogues.splice(fromIndex, 1);
        dialogues.splice(toIndex, 0, moved);
        return { ...s, dialogues };
      }),
      scriptSaveStatus: "unsaved",
    })),

  setScriptSaveStatus: (status) => set({ scriptSaveStatus: status }),
  setScriptLoading: (loading) => set({ scriptLoading: loading }),
  setScriptError: (error) => set({ scriptError: error }),

  // ----- 分镜 -----
  setStoryboardCanvasState: (state) =>
    set({ storyboardCanvasState: state, storyboardIsModified: !!state }),

  pushStoryboardUndo: (state) =>
    set((prev) => ({
      storyboardUndoStack: [...prev.storyboardUndoStack, state],
      storyboardRedoStack: [],
    })),

  undoStoryboard: () => {
    const { storyboardUndoStack, storyboardRedoStack, storyboardCanvasState } = get();
    if (storyboardUndoStack.length === 0) return null;
    const prevState = storyboardUndoStack[storyboardUndoStack.length - 1];
    set({
      storyboardUndoStack: storyboardUndoStack.slice(0, -1),
      storyboardRedoStack: storyboardCanvasState
        ? [...storyboardRedoStack, storyboardCanvasState]
        : storyboardRedoStack,
      storyboardCanvasState: prevState,
    });
    return prevState;
  },

  redoStoryboard: () => {
    const { storyboardRedoStack, storyboardUndoStack, storyboardCanvasState } = get();
    if (storyboardRedoStack.length === 0) return null;
    const nextState = storyboardRedoStack[storyboardRedoStack.length - 1];
    set({
      storyboardRedoStack: storyboardRedoStack.slice(0, -1),
      storyboardUndoStack: storyboardCanvasState
        ? [...storyboardUndoStack, storyboardCanvasState]
        : storyboardUndoStack,
      storyboardCanvasState: nextState,
    });
    return nextState;
  },

  clearStoryboardHistory: () =>
    set({ storyboardUndoStack: [], storyboardRedoStack: [] }),

  setStoryboardSelectedObject: (obj) => set({ storyboardSelectedObject: obj }),
  setStoryboardIsModified: (modified) => set({ storyboardIsModified: modified }),

  // ----- UI -----
  toggleSidebar: () =>
    set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
  setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
}));

// ===== Selectors =====

export const selectScriptStats = (state: ProjectState) => {
  let totalChars = 0;
  let dialogueCount = 0;
  let actionCount = 0;

  for (const scene of state.scriptScenes) {
    totalChars += scene.title.length + scene.location.length;
    for (const line of scene.dialogues) {
      totalChars += line.content.length + (line.character?.length ?? 0);
      if (line.type === "dialogue") dialogueCount++;
      else if (line.type === "action") actionCount++;
    }
  }

  return {
    sceneCount: state.scriptScenes.length,
    totalChars,
    dialogueCount,
    actionCount,
    wordCount: totalChars,
  };
};

export const selectCanUndo = (state: ProjectState) =>
  state.storyboardUndoStack.length > 0;

export const selectCanRedo = (state: ProjectState) =>
  state.storyboardRedoStack.length > 0;
