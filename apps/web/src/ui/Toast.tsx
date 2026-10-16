import { useCallback, useMemo, useState, type ReactNode } from "react";

import { ToastContext, type ToastTone } from "./toast-context";

interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const announce = useCallback((message: string, tone: ToastTone = "info") => {
    const id = Date.now();
    setToasts((current) => [...current, { id, message, tone }].slice(-3));
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 5000);
  }, []);
  const value = useMemo(() => ({ announce }), [announce]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-region" aria-live="polite" aria-relevant="additions">
        {toasts.map((toast) => (
          <div className={`toast toast--${toast.tone}`} key={toast.id}>
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
