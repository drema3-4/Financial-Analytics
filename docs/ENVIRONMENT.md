# Проверенная среда разработки

Снимок выполнен 2026-10-13 в часовом поясе `Europe/Saratov`. Это описание фактической машины, а не обещание, что все будущие машины имеют те же ресурсы. Нормативные версии находятся в `.tool-versions`, `.python-version` и ADR-008.

## Результат preflight

Core-среда пока **не готова**: Docker/Git доступны, но версии Node.js, pnpm, Python и Poetry не совпадают с baseline, а Corepack отсутствует. Это ожидаемый ненулевой результат `scripts/preflight.ps1` до установки недостающего toolchain.

Local-LLM prerequisites **не блокируют core**. NVIDIA GPU и passthrough в Linux-контейнер проверены успешно. Совместимость vLLM и модели с 6 GiB VRAM здесь не проверялась и не заявляется.

## Фактический снимок хоста

| Компонент | Обнаружено | Baseline / статус |
|---|---|---|
| ОС | Windows 11 Pro, `10.0.26200`, x64 | поддерживается через Docker Desktop + WSL2 |
| CPU | Intel Core 5 210H, 8 cores / 12 logical processors, x64 | достаточно для preflight |
| RAM | 15.63 GiB всего; 2.30 GiB свободно в момент замера | свободная память изменяется во времени |
| Диск репозитория | 279.12 GiB свободно на томе D: | доступно |
| WSL | WSL `2.7.3.0`, kernel `6.6.114.1-1`; `docker-desktop` работает как WSL2 distro | доступно |
| Git | `2.56.0.windows.2` | core: доступно |
| Docker Desktop | `4.54.0.212467` | доступно |
| Docker Engine | client/server `29.1.2`, Linux `x86_64`, 12 vCPU, 7.57 GiB VM RAM | core: доступно после запуска Desktop |
| Docker Compose | `v2.40.3-desktop.1` | core: доступно |
| Node.js | `25.2.1` | core: **расхождение**, нужен `24.21.0` LTS |
| Corepack | команда отсутствует | core: **отсутствует** |
| pnpm | `10.24.0` | core: **расхождение**, нужен `12.12.1` |
| Python launcher / `python` | только `3.14.0` | core: **отсутствует** `3.12.12` |
| Poetry | `2.4.1`; также сообщает о недоступном реальном пути текущего Python | core: **расхождение**, нужен `2.5.1` и исправная привязка |
| NVIDIA GPU | GeForce RTX 3050 6GB Laptop GPU, 6144 MiB | optional local-LLM prerequisite: доступно |
| NVIDIA driver | `577.05` | optional local-LLM prerequisite: доступно |
| `nvidia-ctk` на Windows host | команда отсутствует | не требуется для Docker Desktop WSL2 GPU-PV |

Свободные RAM и disk — оперативный снимок, а не минимальные требования продукта.

## GPU passthrough

Проверка выполнена без скачивания модели:

```text
docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04@sha256:133c78a0575303be34164d0b90137a042172bdf60696af01a3c424ab402d86e2 \
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
```

Результат:

```text
NVIDIA GeForce RTX 3050 6GB Laptop GPU, 577.05, 6144 MiB
```

Это доказывает только доступ контейнера к GPU. Проверка vLLM, загрузка весов, OOM-поведение, допустимый контекст и latency относятся к профильному этапу 09.

## Что обязательно для core

- Git.
- На Windows: WSL2 и Docker Desktop с Linux containers; на Linux: совместимый Docker Engine.
- Docker Compose v2.
- Node.js `24.21.0`, доступный Corepack и pnpm `12.12.1`.
- Python `3.12.12` и Poetry `2.5.1`.

Только для необязательного профиля `local-llm` нужны NVIDIA GPU, совместимый драйвер и рабочий GPU passthrough. Отсутствие любого из них выводит предупреждение, но не меняет exit code core-проверки.

## Как устранить расхождения

Ничего из перечисленного ниже preflight-скрипты не устанавливают и настройки хоста не меняют.

1. Установить менеджер версий, который читает `.tool-versions`, затем из корня репозитория установить ровно указанные версии. На Windows можно использовать совместимый менеджер нативно либо выполнить toolchain в пользовательской WSL2-дистрибуции. После установки проверить `node --version`, `pnpm --version`, выбранный Python и `poetry --version`.
2. Для Node.js использовать официальный `24.21.0` LTS. Включить поставляемый/установленный Corepack и активировать `pnpm@12.12.1`; не использовать плавающий тег.
3. Python `3.12.12` — security-only source release, и официальный Windows installer для него не публиковался. Безопасные варианты: собрать эту версию из официального source release через доверенный version manager в WSL2 либо использовать закреплённый Linux image из ADR-008. Случайный сторонний Windows binary не использовать и не подменять версию на `3.12.15` без отдельного решения.
4. Poetry установить из официального installer или через `pipx` с явной версией `2.5.1` после выбора рабочего Python. Удалять существующую установку автоматически не требуется; важно, чтобы первая команда `poetry` в `PATH` была исправна и имела нужную версию.
5. Docker Desktop должен быть запущен перед preflight. На Windows выбран Linux/WSL2 backend.

## Повторяемые команды

Windows PowerShell:

```powershell
./scripts/preflight.ps1
```

Linux, macOS или WSL:

```bash
./scripts/preflight.sh
```

Обе команды возвращают ненулевой код при отсутствии или несовпадении обязательного core toolchain. Чтобы проверить только core без запуска CUDA-контейнера:

```powershell
./scripts/preflight.ps1 -SkipGpuContainer
```

```bash
./scripts/preflight.sh --skip-gpu-container
```

Ручные безопасные проверки, использованные для снимка:

```text
git --version
wsl --version
wsl --status
wsl --list --verbose
docker version
docker info
docker compose version
node --version
corepack --version
pnpm --version
py -0p
python --version
poetry --version
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
```

Команды версий не печатают секреты. Не добавляйте к диагностике `env`, `set`, `.env`, Docker configs или credential stores.

## Официальные основания

- [Node.js release status](https://nodejs.org/en/about/previous-releases): production должен использовать LTS; `24.21.0` — выбранный LTS patch.
- [pnpm installation and compatibility](https://pnpm.io/installation): pnpm 12 — текущая линия и совместима с Node.js 24.
- [Poetry history](https://python-poetry.org/history/): `2.5.1` — стабильный patch выбранной линии.
- [Python 3.12.12 release](https://www.python.org/downloads/release/python-31212/): версия подтверждена как security-only source release без Windows installers.
- [PostgreSQL versioning policy](https://www.postgresql.org/support/versioning/): `18.6` — текущий поддерживаемый minor PostgreSQL 18 на дату решения.
- Docker Official Images: [Python](https://hub.docker.com/_/python), [Node.js](https://hub.docker.com/_/node), [PostgreSQL](https://hub.docker.com/_/postgres).
- [Docker Desktop GPU support](https://docs.docker.com/desktop/features/gpu/): GPU passthrough в Windows Linux containers требует WSL2 backend и проверяется через `--gpus`.
