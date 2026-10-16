import type { ReactNode } from "react";

import { Button } from "./Button";

export function LoadingState({ label = "Загружаем данные" }: { label?: string }) {
  return (
    <section className="state state--loading" aria-live="polite" aria-busy="true">
      <span className="state__loader" aria-hidden="true" />
      <div>
        <p className="state__title">{label}</p>
        <p>Это займёт всего несколько секунд.</p>
      </div>
    </section>
  );
}

export function EmptyState({
  action,
  description,
  title,
}: {
  action?: ReactNode;
  description: string;
  title: string;
}) {
  return (
    <section className="state state--empty">
      <span className="state__mark" aria-hidden="true">
        ○
      </span>
      <div>
        <h2 className="state__title">{title}</h2>
        <p>{description}</p>
        {action}
      </div>
    </section>
  );
}

export function ErrorState({
  message,
  onRetry,
  title = "Не удалось загрузить приложение",
}: {
  message: string;
  onRetry?: (() => void) | undefined;
  title?: string;
}) {
  return (
    <section className="state state--error" role="alert">
      <span className="state__mark" aria-hidden="true">
        !
      </span>
      <div>
        <h2 className="state__title">{title}</h2>
        <p>{message}</p>
        {onRetry === undefined ? null : (
          <Button onClick={onRetry} variant="secondary">
            Попробовать снова
          </Button>
        )}
      </div>
    </section>
  );
}
