#!/bin/sh
# Keyless setup for the dedicated Linux development host; no VM or model request.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
test "$(uname -s)" = Linux
cd "$root"
python=${PYTHON:-python3.12}
"$python" -c 'import sys; assert (3,12) <= sys.version_info[:2] < (3,14), "Python 3.12 or 3.13 required"'
mkdir -p ../work
clone_pin() {
    name=$1
    remote=$2
    pin=$3
    if [ ! -d "../work/$name/.git" ]; then
        git init -q "../work/$name"
        git -C "../work/$name" remote add origin "$remote"
        git -C "../work/$name" fetch --depth 1 origin "$pin"
        git -C "../work/$name" checkout --detach FETCH_HEAD
    fi
    test "$(git -C "../work/$name" rev-parse HEAD)" = "$pin"
}
clone_pin hermes-agent https://github.com/NousResearch/hermes-agent.git a9a54245b2311c705d29050b7f9868c015917aec
clone_pin SkillEvaluator https://github.com/NVIDIA/SkillEvaluator.git 33eb9dc74a09280bebf6fb4c921d290a0f874713
clone_pin SkillSpector https://github.com/NVIDIA/SkillSpector.git ec6633e3eaf94d9884c0fe5b14a4de7a50ab5a62
"$python" -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pip install -c config/evaluator-constraints.txt -e '../work/SkillEvaluator[tier3,security]'
"$python" -m venv ../work/semgrep-venv
../work/semgrep-venv/bin/pip install semgrep==1.178.0
"$python" -m venv ../work/skillspector-venv
../work/skillspector-venv/bin/pip install -e ../work/SkillSpector
mkdir -p ../work/bin
curl -fLsS https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz -o ../work/gitleaks.tar.gz
echo '551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb  ../work/gitleaks.tar.gz' | sha256sum -c -
tar -xzf ../work/gitleaks.tar.gz -C ../work/bin gitleaks
