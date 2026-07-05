#!/bin/bash

set -e

if [ -z "$1" ]; then
  echo "Erro: falta a mensagem do commit."
  echo "Uso:"
  echo "  ./scripts/uteis/fechar-atualizacao.sh \"Mensagem do commit\""
  exit 1
fi

echo "== PJCore Labs — Fechar atualização =="
echo

echo "A verificar estado do repositório..."
git status --short

if [ -z "$(git status --short)" ]; then
  echo
  echo "Nada para guardar. Working tree limpo."
  exit 0
fi

echo
echo "A adicionar alterações..."
git add .

echo
echo "A criar commit..."
git commit -m "$1"

echo
echo "A enviar para GitHub..."
git push

echo
echo "Estado final:"
git status

echo
echo "Atualização fechada com sucesso."
