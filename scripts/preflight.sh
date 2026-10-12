#!/usr/bin/env bash

set -u

EXPECTED_NODE="24.21.0"
EXPECTED_PNPM="12.12.1"
EXPECTED_PYTHON="3.12.12"
EXPECTED_POETRY="2.5.1"
CUDA_IMAGE="nvidia/cuda:12.8.1-base-ubuntu24.04@sha256:133c78a0575303be34164d0b90137a042172bdf60696af01a3c424ab402d86e2"

failures=0
warnings=0
docker_ready=0
skip_gpu_container=0

if [[ "${1:-}" == "--skip-gpu-container" ]]; then
  skip_gpu_container=1
elif [[ $# -gt 0 ]]; then
  printf '[FAIL] Unknown argument: %s\n' "$1"
  exit 2
fi

pass() {
  printf '[PASS] %s\n' "$1"
}

fail() {
  failures=$((failures + 1))
  printf '[FAIL] %s\n' "$1"
}

warn() {
  warnings=$((warnings + 1))
  printf '[WARN] %s\n' "$1"
}

command_output() {
  local command_name="$1"
  shift
  if ! command -v "$command_name" >/dev/null 2>&1; then
    return 1
  fi
  "$command_name" "$@" 2>/dev/null
}

printf 'Financial Analytics preflight\n'
printf 'Core failures exit non-zero; local-LLM/GPU checks are warnings only.\n\n'
printf 'OS: %s\n' "$(uname -srm)"

if [[ -r /proc/meminfo ]]; then
  awk '/MemTotal/ { printf "RAM total: %.2f GiB\n", $2 / 1024 / 1024 }' /proc/meminfo
else
  warn "Could not read total RAM."
fi

if df -Pk . >/dev/null 2>&1; then
  df -Pk . | awk 'NR == 2 { printf "Workspace volume free: %.2f GiB\n", $4 / 1024 / 1024 }'
else
  warn "Could not read free space for the workspace volume."
fi

git_version="$(command_output git --version || true)"
if [[ -n "$git_version" ]]; then
  pass "$git_version"
else
  fail "Git is missing or unusable."
fi

if command -v docker >/dev/null 2>&1; then
  docker_version="$(command_output docker version --format '{{.Server.Version}}' || true)"
  if [[ -n "$docker_version" ]]; then
    docker_os="$(command_output docker info --format '{{.OSType}}' || true)"
    if [[ "$docker_os" == "linux" ]]; then
      docker_ready=1
      pass "Docker Engine $docker_version is reachable in Linux container mode."
    else
      fail "Docker Engine $docker_version is reachable, but Linux container mode is required."
    fi
  else
    fail "Docker CLI exists, but the Linux Docker Engine is not reachable."
  fi

  compose_version="$(command_output docker compose version --short || true)"
  if [[ "$compose_version" =~ ^2\. ]]; then
    pass "Docker Compose $compose_version is available."
  else
    fail "Docker Compose v2 is missing or unusable."
  fi
else
  fail "Docker CLI is missing."
  fail "Docker Compose v2 is unavailable because Docker is missing."
fi

node_version="$(command_output node --version || true)"
if [[ "$node_version" == "v$EXPECTED_NODE" ]]; then
  pass "Node.js $EXPECTED_NODE matches the baseline."
elif [[ -n "$node_version" ]]; then
  fail "Node.js $node_version is installed; expected v$EXPECTED_NODE."
else
  fail "Node.js $EXPECTED_NODE is missing."
fi

corepack_version="$(command_output corepack --version || true)"
if [[ -n "$corepack_version" ]]; then
  pass "Corepack $corepack_version is available."
else
  fail "Corepack is missing or unusable."
fi

pnpm_version="$(command_output pnpm --version || true)"
if [[ "$pnpm_version" == "$EXPECTED_PNPM" ]]; then
  pass "pnpm $EXPECTED_PNPM matches the baseline."
elif [[ -n "$pnpm_version" ]]; then
  fail "pnpm $pnpm_version is installed; expected $EXPECTED_PNPM."
else
  fail "pnpm $EXPECTED_PNPM is missing."
fi

python_version=""
python_invocation=""
for candidate in python3 python; do
  candidate_version="$(command_output "$candidate" -c 'import platform; print(platform.python_version())' || true)"
  if [[ -n "$candidate_version" ]]; then
    python_version="$candidate_version"
    python_invocation="$candidate"
    break
  fi
done

if [[ "$python_version" == "$EXPECTED_PYTHON" ]]; then
  pass "Python $EXPECTED_PYTHON matches the baseline ($python_invocation)."
elif [[ -n "$python_version" ]]; then
  fail "Python $python_version is available through $python_invocation; expected $EXPECTED_PYTHON."
else
  fail "Python $EXPECTED_PYTHON is missing."
fi

poetry_output="$(command_output poetry --version || true)"
poetry_version="$(printf '%s' "$poetry_output" | sed -n 's/^Poetry (version \([0-9.]*\))$/\1/p')"
if [[ "$poetry_version" == "$EXPECTED_POETRY" ]]; then
  pass "Poetry $EXPECTED_POETRY matches the baseline."
elif [[ -n "$poetry_version" ]]; then
  fail "Poetry $poetry_version is installed; expected $EXPECTED_POETRY."
else
  fail "Poetry $EXPECTED_POETRY is missing or unusable."
fi

nvidia_output="$(command_output nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || true)"
if [[ -n "$nvidia_output" ]]; then
  pass "Optional NVIDIA host GPU: $nvidia_output"
else
  warn "Optional NVIDIA GPU/driver was not detected; core remains usable."
fi

if [[ $skip_gpu_container -eq 1 ]]; then
  warn "Optional GPU container check was skipped by request."
elif [[ $docker_ready -eq 1 && -n "$nvidia_output" ]]; then
  gpu_output="$(docker run --rm --gpus all "$CUDA_IMAGE" nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>/dev/null || true)"
  if [[ -n "$gpu_output" ]]; then
    pass "Optional GPU passthrough works: $gpu_output"
  else
    warn "Optional GPU passthrough check failed; core remains usable."
  fi
else
  warn "Optional GPU passthrough check was not run because Docker or NVIDIA GPU is unavailable."
fi

printf '\nSummary: %d core failure(s), %d warning(s).\n' "$failures" "$warnings"
if [[ $failures -gt 0 ]]; then
  exit 1
fi

exit 0
