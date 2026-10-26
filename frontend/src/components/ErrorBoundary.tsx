"use client";

import React from "react";

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
}

interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

/**
 * 全局 ErrorBoundary - 捕获客户端JavaScript错误并显示详细信息
 */
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return {
      hasError: true,
      error,
    };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("[ErrorBoundary] 捕获到错误:", error);
    console.error("[ErrorBoundary] 错误堆栈:", errorInfo.componentStack);

    this.setState({
      errorInfo,
    });
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="min-h-screen flex items-center justify-center bg-red-50 p-6">
          <div className="max-w-2xl w-full bg-white rounded-lg shadow-lg p-6 border border-red-200">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
                <span className="text-red-600 text-xl">!</span>
              </div>
              <div>
                <h1 className="text-lg font-semibold text-red-700">
                  客户端运行时错误
                </h1>
                <p className="text-sm text-red-500">
                  应用程序遇到了一个问题
                </p>
              </div>
            </div>

            <div className="bg-gray-50 rounded-md p-4 mb-4 border border-gray-200">
              <p className="text-xs font-semibold text-gray-500 mb-1">错误信息:</p>
              <p className="text-sm text-gray-800 font-mono break-all">
                {this.state.error?.message || "未知错误"}
              </p>
            </div>

            {this.state.error?.stack && (
              <details className="mb-4">
                <summary className="text-xs font-semibold text-gray-500 cursor-pointer hover:text-gray-700">
                  查看错误堆栈
                </summary>
                <pre className="mt-2 text-xs text-gray-600 bg-gray-50 rounded-md p-3 overflow-auto max-h-64 border border-gray-200">
                  {this.state.error.stack}
                </pre>
              </details>
            )}

            {this.state.errorInfo?.componentStack && (
              <details className="mb-4">
                <summary className="text-xs font-semibold text-gray-500 cursor-pointer hover:text-gray-700">
                  查看组件堆栈
                </summary>
                <pre className="mt-2 text-xs text-gray-600 bg-gray-50 rounded-md p-3 overflow-auto max-h-64 border border-gray-200">
                  {this.state.errorInfo.componentStack}
                </pre>
              </details>
            )}

            <div className="flex gap-2">
              <button
                onClick={() => window.location.reload()}
                className="px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 transition-colors"
              >
                重新加载页面
              </button>
              <button
                onClick={() => {
                  localStorage.removeItem("ai-drama-studio-store");
                  window.location.reload();
                }}
                className="px-4 py-2 bg-gray-200 text-gray-700 rounded-md text-sm font-medium hover:bg-gray-300 transition-colors"
              >
                清除数据并重载
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
