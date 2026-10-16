from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DISCLAIMER = (
    "Это информационное объяснение, а не финансовая гарантия или индивидуальная рекомендация."
)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self.send_error(404)
            return
        self._json(200, {"status": "ok"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        request: Any = json.loads(self.rfile.read(length))
        serialized = json.dumps(request, ensure_ascii=False)
        evidence_id = "forecast:result"
        if "forecast:result" not in serialized:
            self.send_error(422)
            return
        content = {
            "summary": "Детерминированный прогноз доступен для сверки.",
            "observations": [
                {
                    "text": "Итог прогноза основан только на переданных агрегатах.",
                    "evidence_ids": [evidence_id],
                }
            ],
            "suggestions": ["Сравните базовый и изменённый сценарии."],
            "assumptions": ["Использованы только агрегированные метрики."],
            "risks": ["Будущий результат не гарантирован."],
            "confidence": "medium",
            "disclaimer": DISCLAIMER,
        }
        self._json(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(content, ensure_ascii=False),
                        }
                    }
                ]
            },
        )

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _json(self, status: int, value: object) -> None:
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8010), Handler).serve_forever()
