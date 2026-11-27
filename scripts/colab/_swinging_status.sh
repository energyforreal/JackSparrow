#!/usr/bin/env bash
export PATH="${HOME}/.local/bin:${PATH}"
colab sessions
echo "--- status ---"
colab status -s swinging || true
echo "--- ls data ---"
colab ls -s swinging JackSparrow/data/BTCUSD || true
