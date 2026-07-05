#!/bin/bash

set -e

PROJECT_DIR="$HOME/pjcorelabs"
OUT_DIR="$PROJECT_DIR/documentation/reports"
DATE_ID="$(date '+%Y-%m-%d_%H-%M')"
OUT_FILE="$OUT_DIR/CONTINUIDADE_PJCORE_LABS_$DATE_ID.md"

mkdir -p "$OUT_DIR"

cd "$PROJECT_DIR"

{
  echo "# CONTINUIDADE — PJCore Labs"
  echo
  echo "Gerado automaticamente em: $(date '+%Y-%m-%d %H:%M:%S')"
  echo
  echo "---"
  echo

  echo "## Identificação"
  echo
  echo "Projeto: PJCore Labs"
  echo "Pasta local: ~/pjcorelabs"
  echo "Repositório GitHub: https://github.com/pajogusi/pjcorelabs"
  echo "Site principal: https://pjcorelabs.com"
  echo "Branch atual: $(git branch --show-current)"
  echo

  echo "---"
  echo

  echo "## Estado Git"
  echo
  echo '```bash'
  git status
  echo '```'
  echo

  echo "---"
  echo

  echo "## Últimos commits"
  echo
  echo '```bash'
  git log --oneline -10
  echo '```'
  echo

  echo "---"
  echo

  echo "## Estrutura principal"
  echo
  echo '```bash'
  find . -maxdepth 3 \
    -path "./.git" -prune -o \
    -path "./website/index.html.bak-home-v1" -prune -o \
    -path "./website/css/style.css.bak-home-v1" -prune -o \
    -path "./website/js/language.js.bak-home-v1" -prune -o \
    -print | sort
  echo '```'
  echo

  echo "---"
  echo

  echo "## Ficheiros principais do website"
  echo
  echo '```bash'
  find website -maxdepth 3 -type f | sort
  echo '```'
  echo

  echo "---"
  echo

  for file in \
    README.md \
    CADERNO_DE_ENCARGOS.md \
    DIARIO_DESENVOLVIMENTO.md \
    CHANGELOG.md \
    ROADMAP.md \
    TODO.md \
    DOMINIOS.md
  do
    if [ -f "$file" ]; then
      echo "## $file"
      echo
      echo '```markdown'
      cat "$file"
      echo
      echo '```'
      echo
      echo "---"
      echo
    fi
  done

  echo "## Workflow GitHub Pages"
  echo
  if [ -f ".github/workflows/deploy-pages.yml" ]; then
    echo
    echo '```yaml'
    cat ".github/workflows/deploy-pages.yml"
    echo
    echo '```'
  else
    echo
    echo "Workflow não encontrado."
  fi
  echo

  echo "---"
  echo

  echo "## Regras importantes para a próxima conversa"
  echo
  echo
  echo "- Trabalhar passo a passo."
  echo "- Não enviar vários passos na mesma resposta."
  echo "- Confirmar \`git status\` antes de alterações importantes."
  echo "- Usar o script de fecho de atualização:"
  echo
  echo '```bash'
  echo './scripts/uteis/fechar-atualizacao.sh "Mensagem do commit"'
  echo '```'
  echo
  echo "- Para gerar nova continuidade, usar:"
  echo
  echo '```bash'
  echo './scripts/uteis/muda-o-disco.sh'
  echo '```'
  echo
  echo "- A pasta \`website/\` é publicada via GitHub Actions."
  echo "- Não mover o site para a raiz."
  echo "- Não mexer no DNS às cegas."
  echo

} > "$OUT_FILE"

echo
echo "Continuidade criada:"
echo "$OUT_FILE"
echo

if command -v wl-copy >/dev/null 2>&1; then
  cat "$OUT_FILE" | wl-copy
  echo "Conteúdo copiado para o clipboard com wl-copy."
elif command -v xclip >/dev/null 2>&1; then
  cat "$OUT_FILE" | xclip -selection clipboard
  echo "Conteúdo copiado para o clipboard com xclip."
elif command -v xsel >/dev/null 2>&1; then
  cat "$OUT_FILE" | xsel --clipboard --input
  echo "Conteúdo copiado para o clipboard com xsel."
else
  echo "Clipboard não disponível. Copia manualmente o ficheiro gerado."
fi

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$OUT_FILE" >/dev/null 2>&1 || true
fi
