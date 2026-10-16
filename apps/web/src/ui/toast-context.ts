import { createContext, useContext } from "react";

export type ToastTone = "success" | "info";

export interface ToastContextValue {
  announce: (message: string, tone?: ToastTone) => void;
}

export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const value = useContext(ToastContext);
  if (value === null) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return value;
}
