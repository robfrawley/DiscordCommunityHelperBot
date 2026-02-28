#!/usr/bin/env zsh

SELF_PATH="${(%):-%x}"
LOAD_VENV=0

cd "$(dirname "$SELF_PATH")/.."

if [[ -z "$VIRTUAL_ENV" ]]; then
    if [[ ! -d ".venv" ]]; then
        python3 -m venv .venv
    fi

    . .venv/bin/activate

    LOAD_VENV=1
fi

pip install -r requirements.txt
python -m spacy download en_core_web_trf

if [[ ${LOAD_VENV} -eq 1 ]]; then
    deactivate
fi
