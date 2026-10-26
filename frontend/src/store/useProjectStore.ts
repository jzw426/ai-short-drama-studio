import { create } from "zustand";
import type { Project } from "@/types";

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

export const useProjectStore = create<ProjectState>((set, get) => ({
  currentProject: null,
  projects: [],

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

export const selectCanUndo = (state: ProjectState) =>
  state.storyboardUndoStack.length > 0;

export const selectCanRedo = (state: ProjectState) =>
  state.storyboardRedoStack.length > 0;
