from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast


@dataclass(frozen=True, slots=True)
class FakeResponse:
    status: int
    body: object
    headers: dict[str, str] = field(default_factory=dict)
    delay_seconds: float = 0


class FakeOpenAIServer:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                with outer._lock:
                    outer.requests.append(json.loads(raw))
                    response = outer.responses.pop(0)
                if response.delay_seconds:
                    time.sleep(response.delay_seconds)
                encoded = (
                    response.body
                    if isinstance(response.body, bytes)
                    else json.dumps(response.body).encode()
                )
                try:
                    self.send_response(response.status)
                    self.send_header("Content-Type", "application/json")
                    for name, value in response.headers.items():
                        self.send_header(name, value)
                    self.end_headers()
                    self.wfile.write(encoded)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = cast(tuple[str, int], self._server.server_address)
        return f"http://{host}:{port}/v1"

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


@contextmanager
def fake_openai_server(responses: list[FakeResponse]) -> Iterator[FakeOpenAIServer]:
    server = FakeOpenAIServer(responses)
    server.start()
    try:
        yield server
    finally:
        server.close()


def chat_completion(content: object) -> dict[str, object]:
    encoded = content if isinstance(content, str) else json.dumps(content)
    return {"choices": [{"message": {"role": "assistant", "content": encoded}}]}
