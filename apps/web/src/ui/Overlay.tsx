import { useEffect, useId, useRef, type ReactNode } from "react";

import { Button } from "./Button";

interface DialogProps {
  children: ReactNode;
  description?: string | undefined;
  onClose: () => void;
  open: boolean;
  title: string;
  variant?: "dialog" | "drawer";
}

export function Dialog({
  children,
  description,
  onClose,
  open,
  title,
  variant = "dialog",
}: DialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const id = useId();
  const titleId = `${id}-title`;
  const descriptionId = `${id}-description`;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) {
      return;
    }
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
      }
    } else if (!open && dialog.open) {
      if (typeof dialog.close === "function") {
        dialog.close();
      } else {
        dialog.removeAttribute("open");
      }
    }
  }, [open]);

  return (
    <dialog
      aria-describedby={description === undefined ? undefined : descriptionId}
      aria-labelledby={titleId}
      className={`overlay overlay--${variant}`}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClose={onClose}
      ref={dialogRef}
    >
      <div className="overlay__header">
        <div>
          <p className="eyebrow">Личное пространство</p>
          <h2 id={titleId}>{title}</h2>
          {description === undefined ? null : <p id={descriptionId}>{description}</p>}
        </div>
        <Button aria-label="Закрыть" className="icon-button" onClick={onClose} variant="quiet">
          <span aria-hidden="true">×</span>
        </Button>
      </div>
      {children}
    </dialog>
  );
}
