import { useEffect, useState } from "react";

import { fetchReadiness } from "./api";
import "./styles.css";

type ApiStatus = "checking" | "ready" | "unavailable";

export function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");

  useEffect(() => {
    const controller = new AbortController();
    void fetchReadiness(controller.signal)
      .then(() => {
        setApiStatus("ready");
      })
      .catch(() => {
        setApiStatus("unavailable");
      });
    return () => {
      controller.abort();
    };
  }, []);

  const statusText = {
    checking: "Проверяем core API…",
    ready: "Core API готов",
    unavailable: "Core API недоступен",
  }[apiStatus];

  return (
    <main className="shell">
      <section className="card" aria-labelledby="title">
        <p className="eyebrow">Этап 01 · Bootstrap</p>
        <h1 id="title">Financial Analytics</h1>
        <p>Минимальный каркас приложения запущен. Финансовые функции появятся по этапам.</p>
        <p className={`status status--${apiStatus}`} role="status">
          <span aria-hidden="true" />
          {statusText}
        </p>
      </section>
    </main>
  );
}
