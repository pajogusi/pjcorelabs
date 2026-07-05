#!/bin/bash

set -e

PROJETO="$HOME/pjcorelabs"

echo "A criar estrutura PJCore Labs em: $PROJETO"

mkdir -p "$PROJETO"/{website,brand,logos,assets,legal,domains,roadmap,products,scripts,documentation,notes}

mkdir -p "$PROJETO/website"/{css,js,img,pages}
mkdir -p "$PROJETO/brand"/{colors,typography,voice,templates}
mkdir -p "$PROJETO/products"/{workstation-os,repositorio-solicitadoria,ai-tools}
mkdir -p "$PROJETO/scripts"/{uteis,deploy,backup}
mkdir -p "$PROJETO/documentation"/{decisions,reports}

cat > "$PROJETO/README.md" <<'EOF'
# PJCore Labs

PJCore Labs é a marca central para projetos digitais, software, IA, automação, ferramentas web e experiências técnicas criadas por Paulo Silva.

## Domínios

- pjcorelabs.com
- pjcorelabs.co.uk

## Objetivo

Albergar o site institucional da PJCore Labs e organizar a identidade, documentação, produtos e scripts úteis da marca.
EOF

cat > "$PROJETO/CADERNO_DE_ENCARGOS.md" <<'EOF'
# Caderno de Encargos — PJCore Labs

## Missão

Criar uma identidade digital central para projetos de software, IA, automação e ferramentas úteis.

## Regras

- Não desenvolver diretamente sobre produção.
- Criar documentação clara desde o início.
- Manter domínio, marca, scripts e produtos organizados.
- Separar website, identidade visual, produtos e documentação.
- Fazer commit antes e depois de alterações importantes.
EOF

cat > "$PROJETO/DIARIO_DESENVOLVIMENTO.md" <<'EOF'
# Diário de Desenvolvimento — PJCore Labs

## 2026-07-05

- Registados os domínios principais:
  - pjcorelabs.com
  - pjcorelabs.co.uk
- Criada estrutura inicial do projeto PJCore Labs.
EOF

cat > "$PROJETO/CHANGELOG.md" <<'EOF'
# Changelog — PJCore Labs

## v0.1.0 — Estrutura Inicial

- Criada estrutura base do projeto.
- Adicionadas pastas principais.
- Adicionados documentos oficiais iniciais.
EOF

cat > "$PROJETO/ROADMAP.md" <<'EOF'
# Roadmap — PJCore Labs

## Fase 1

- Criar estrutura base.
- Criar site institucional simples.
- Ligar domínio pjcorelabs.com ao GitHub Pages.
- Criar email profissional.

## Fase 2

- Definir identidade visual.
- Criar página de produtos.
- Integrar projetos existentes.

## Fase 3

- Criar ferramentas públicas.
- Criar documentação de marca.
- Preparar presença profissional.
EOF

cat > "$PROJETO/TODO.md" <<'EOF'
# TODO — PJCore Labs

- [ ] Criar repositório GitHub pjcorelabs.
- [ ] Criar site institucional.
- [ ] Configurar GitHub Pages.
- [ ] Apontar pjcorelabs.com para GitHub Pages.
- [ ] Apontar pjcorelabs.co.uk para pjcorelabs.com.
- [ ] Criar email geral@pjcorelabs.com.
- [ ] Guardar dados dos domínios em DOMINIOS.md.
- [ ] Criar identidade visual oficial.
EOF

cat > "$PROJETO/DOMINIOS.md" <<'EOF'
# Domínios — PJCore Labs

## Domínio principal

- Domínio: pjcorelabs.com
- Registrador: Porkbun
- Data de aquisição: 2026-07-05
- Renovação: anual

## Domínio Reino Unido

- Domínio: pjcorelabs.co.uk
- Registrador: Porkbun
- Data de aquisição: 2026-07-05
- Renovação: anual

## Emails previstos

- geral@pjcorelabs.com
- hello@pjcorelabs.com
- contact@pjcorelabs.com
- support@pjcorelabs.com
EOF

cat > "$PROJETO/website/index.html" <<'EOF'
<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="UTF-8">
  <title>PJCore Labs</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="css/style.css">
</head>
<body>
  <main class="hero">
    <h1>PJCore Labs</h1>
    <p>Software, IA, automação e ferramentas digitais.</p>
    <p class="small">Site em construção.</p>
  </main>
</body>
</html>
EOF

cat > "$PROJETO/website/css/style.css" <<'EOF'
* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family: system-ui, Arial, sans-serif;
  background: #0f1117;
  color: #f5f5f5;
}

.hero {
  min-height: 100vh;
  display: grid;
  place-content: center;
  text-align: center;
  padding: 2rem;
}

h1 {
  font-size: clamp(3rem, 8vw, 7rem);
  margin: 0;
  letter-spacing: 0.08em;
}

p {
  font-size: 1.25rem;
  color: #c9c9c9;
}

.small {
  font-size: 0.95rem;
  opacity: 0.7;
}
EOF

cat > "$PROJETO/.gitignore" <<'EOF'
.DS_Store
Thumbs.db
*.log
.env
node_modules/
dist/
build/
EOF

cd "$PROJETO"

git init
git add .
git commit -m "Initial PJCore Labs structure"

echo ""
echo "Estrutura criada com sucesso."
echo "Pasta: $PROJETO"
echo ""
echo "Próximo passo:"
echo "cd ~/pjcorelabs"
