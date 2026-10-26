"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { Toaster } from "sonner";
import { useProjectStore } from "@/store/useProjectStore";

export default function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000,
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  // 初始化 store 从 localStorage 恢复
  useEffect(() => {
    const stored = localStorage.getItem("ai-drama-studio-store");
    if (stored) {
      try {
        const data = JSON.parse(stored);
        useProjectStore.setState((prev) => ({
          ...prev,
          ...data,
          scriptScenes: data.scriptScenes || [],
          projects: data.projects || [],
        }));
      } catch {
        // 忽略解析错误
      }
    }
  }, []);

  // 监听 store 变化并持久化
  useEffect(() => {
    const unsubscribe = useProjectStore.subscribe((state) => {
      const { scriptScenes, projects, currentProject, workflowSteps } = state;
      localStorage.setItem(
        "ai-drama-studio-store",
        JSON.stringify({ scriptScenes, projects, currentProject, workflowSteps })
      );
    });
    return unsubscribe;
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster position="top-right" richColors closeButton />
    </QueryClientProvider>
  );
}
