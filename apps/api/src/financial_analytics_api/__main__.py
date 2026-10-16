from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "financial_analytics_api.main:app",
        host="0.0.0.0",
        port=8000,
        proxy_headers=False,
        access_log=False,
        log_config=None,
        timeout_graceful_shutdown=30,
    )


if __name__ == "__main__":
    main()
