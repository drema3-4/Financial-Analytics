from __future__ import annotations

import uvicorn

from financial_analytics_infra.settings import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "financial_analytics_api.main:app",
        host="0.0.0.0",
        port=8000,
        proxy_headers=bool(settings.trusted_proxy_ips),
        forwarded_allow_ips=",".join(settings.trusted_proxy_ips),
        access_log=False,
        log_config=None,
        timeout_graceful_shutdown=30,
    )


if __name__ == "__main__":
    main()
