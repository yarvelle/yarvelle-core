// Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
// Copyright 2026 Spectrayan (https://spectrayan.com)
//
// Licensed under the PolyForm Noncommercial License 1.0.0 and the
// Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
// Personal and household local use only. Commercial use, hosted service
// offering, rebranding, white-labeling, and redistribution of modified
// forks are prohibited without a written commercial license from Spectrayan.
//
// Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

import * as React from 'react';
import { cn } from '../lib/cn.js';

export interface ToastItem {
  id: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  variant?: 'info' | 'success' | 'warn' | 'danger';
  duration?: number;
}

interface ToastContextValue {
  toasts: ToastItem[];
  addToast: (toast: Omit<ToastItem, 'id'>) => string;
  removeToast: (id: string) => void;
}

const ToastContext = React.createContext<ToastContextValue | null>(null);

export function useToast() {
  const ctx = React.useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used within a ToastProvider or Toaster');
  }
  return ctx;
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<ToastItem[]>([]);

  const removeToast = React.useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = React.useCallback(
    (toast: Omit<ToastItem, 'id'>) => {
      const id = Math.random().toString(36).substring(2, 9);
      const newToast: ToastItem = { ...toast, id };
      setToasts((prev) => [...prev, newToast]);

      const duration = toast.duration ?? 5000;
      if (duration > 0) {
        setTimeout(() => {
          removeToast(id);
        }, duration);
      }
      return id;
    },
    [removeToast]
  );

  return (
    <ToastContext.Provider value={{ toasts, addToast, removeToast }}>
      {children}
    </ToastContext.Provider>
  );
}

const variantStyles: Record<NonNullable<ToastItem['variant']>, string> = {
  info: 'border-info-border bg-surface text-fg',
  success: 'border-success-border bg-surface text-fg',
  warn: 'border-warn-border bg-surface text-fg',
  danger: 'border-danger-border bg-surface text-fg',
};

export interface ToasterProps {
  className?: string;
  position?: 'top-start' | 'top-end' | 'bottom-start' | 'bottom-end';
}

export function Toaster({ className, position = 'bottom-end' }: ToasterProps) {
  const ctx = React.useContext(ToastContext);
  const toasts = ctx ? ctx.toasts : [];
  const removeToast = ctx ? ctx.removeToast : () => {};

  const positionClass =
    position === 'bottom-end'
      ? 'bottom-4 end-4'
      : position === 'bottom-start'
      ? 'bottom-4 start-4'
      : position === 'top-end'
      ? 'top-4 end-4'
      : 'top-4 start-4';

  return (
    <div
      data-slot="toaster"
      role="region"
      aria-live="polite"
      aria-label="Notifications"
      className={cn('yc-Toaster-root fixed z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none', positionClass, className)}
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="status"
          data-slot="toast"
          data-variant={toast.variant || 'info'}
          className={cn(
            'yc-Toaster-toast pointer-events-auto flex w-full items-start justify-between rounded-lg p-3 shadow-2 border transition-all duration-normal',
            variantStyles[toast.variant || 'info']
          )}
        >
          <div className="flex-1 pe-2">
            <h4 className="yc-Toaster-title text-sm font-medium" data-slot="title">
              {toast.title}
            </h4>
            {toast.description && (
              <p className="yc-Toaster-description mt-0.5 text-xs text-fg-muted" data-slot="description">
                {toast.description}
              </p>
            )}
          </div>
          <button
            type="button"
            data-slot="close"
            className="yc-Toaster-close text-fg-muted hover:text-fg text-xs p-1"
            onClick={() => removeToast(toast.id)}
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
