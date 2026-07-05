# CONTINUIDADE — PJCore Labs

Gerado automaticamente em: 2026-07-05 19:53:14

---

## Identificação

Projeto: PJCore Labs
Pasta local: ~/pjcorelabs
Repositório GitHub: https://github.com/pajogusi/pjcorelabs
Site principal: https://pjcorelabs.com
Branch atual: main

---

## Estado Git

```bash
On branch main
Your branch is up-to-date with 'origin/main'.

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	documentation/
	scripts/uteis/muda-o-disco.sh

nothing added to commit but untracked files present (use "git add" to track)
```

---

## Últimos commits

```bash
5619315 Document update closing script rule
9972fe9 Add update closing script
54b073f Update PJCore Labs documentation after homepage v1
ec894e7 Trigger clean Pages deploy
0b5b7be Build PJCore Labs homepage v1
593c5a6 Backup homepage before v1 redesign
f8fc0e9 Add bilingual language detection
685491f Add GitHub Pages deploy workflow
9536f65 Move setup script out of project repository
4ad40d0 Initial PJCore Labs structure
```

---

## Estrutura principal

```bash
.
./assets
./brand
./brand/colors
./brand/templates
./brand/typography
./brand/voice
./CADERNO_DE_ENCARGOS.md
./CHANGELOG.md
./DIARIO_DESENVOLVIMENTO.md
./documentation
./documentation/decisions
./documentation/reports
./documentation/reports/CONTINUIDADE_PJCORE_LABS_2026-07-05_19-53.md
./domains
./DOMINIOS.md
./.github
./.github/workflows
./.github/workflows/deploy-pages.yml
./.gitignore
./legal
./logos
./notes
./products
./products/ai-tools
./products/repositorio-solicitadoria
./products/workstation-os
./README.md
./roadmap
./ROADMAP.md
./scripts
./scripts/backup
./scripts/deploy
./scripts/uteis
./scripts/uteis/fechar-atualizacao.sh
./scripts/uteis/muda-o-disco.sh
./TODO.md
./website
./website/css
./website/css/style.css
./website/img
./website/img/pjcorelabs-logo.png
./website/img/pjcorelabs-symbol-clean.png
./website/index.html
./website/js
./website/js/language.js
./website/pages
```

---

## Ficheiros principais do website

```bash
website/css/style.css
website/css/style.css.bak-home-v1
website/img/pjcorelabs-logo.png
website/img/pjcorelabs-symbol-clean.png
website/index.html
website/index.html.bak-home-v1
website/js/language.js
website/js/language.js.bak-home-v1
```

---

## README.md

```markdown
# PJCore Labs

PJCore Labs é a marca central para projetos digitais, software, IA, automação, ferramentas web e experiências técnicas criadas por Paulo Silva.

## Domínios

- pjcorelabs.com
- pjcorelabs.co.uk

## Objetivo

Albergar o site institucional da PJCore Labs e organizar a identidade, documentação, produtos e scripts úteis da marca.

```

---

## CADERNO_DE_ENCARGOS.md

```markdown
# Caderno de Encargos — PJCore Labs

## Missão

Criar uma identidade digital central para projetos de software, IA, automação e ferramentas úteis.

## Regras

- Não desenvolver diretamente sobre produção.
- Criar documentação clara desde o início.
- Manter domínio, marca, scripts e produtos organizados.
- Separar website, identidade visual, produtos e documentação.
- Fazer commit antes e depois de alterações importantes.
- Para fechar atualizações, usar `./scripts/uteis/fechar-atualizacao.sh "Mensagem do commit"` em vez de repetir manualmente `git add`, `git commit` e `git push`.

```

---

## DIARIO_DESENVOLVIMENTO.md

```markdown
# Diário de Desenvolvimento — PJCore Labs

## 2026-07-05

- Registados os domínios principais:
  - pjcorelabs.com
  - pjcorelabs.co.uk
- Criada estrutura inicial do projeto PJCore Labs.
- Configurado deploy por GitHub Actions para publicação da pasta website/.
- Configurado domínio principal pjcorelabs.com no GitHub Pages.
- Confirmado HTTPS funcional.
- Implementado sistema bilingue PT/EN com deteção automática do idioma do browser e escolha manual guardada no localStorage.
- Criada e publicada a homepage oficial v1.0 do PJCore Labs.
- Integrado o logo oficial no header.
- Criado ficheiro otimizado para o símbolo do header:
  - website/img/pjcorelabs-symbol-clean.png
- Mantido o logo original completo:
  - website/img/pjcorelabs-logo.png
- Confirmado funcionamento da homepage em PC, tablet e telemóvel.
- Resolvido problema de deploy causado por re-run do GitHub Actions, que criou múltiplos artifacts chamados "github-pages".
- Feito commit vazio para disparar deploy limpo:
  - Trigger clean Pages deploy
- Deploy final confirmado como verde.

```

---

## CHANGELOG.md

```markdown
# Changelog — PJCore Labs

## v1.0.0 — Homepage Oficial

- Publicada a homepage oficial do PJCore Labs em https://pjcorelabs.com.
- Confirmado funcionamento em PC, tablet e telemóvel.
- Implementada estrutura bilingue PT/EN.
- Adicionadas secções principais:
  - Header
  - Hero
  - Sobre
  - Projetos
  - Valores
  - Roadmap
  - Contacto
  - Footer
- Integrado logo oficial no header.
- Mantidos ficheiros de imagem principais:
  - website/img/pjcorelabs-logo.png
  - website/img/pjcorelabs-symbol-clean.png
- Deploy final confirmado com sucesso via GitHub Actions.

## v0.1.0 — Estrutura Inicial

- Criada estrutura base do projeto.
- Adicionadas pastas principais.
- Adicionados documentos oficiais iniciais.

```

---

## ROADMAP.md

```markdown
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

```

---

## TODO.md

```markdown
# TODO — PJCore Labs

## Concluído

- [x] Criar repositório GitHub pjcorelabs.
- [x] Criar site institucional.
- [x] Configurar GitHub Pages.
- [x] Apontar pjcorelabs.com para GitHub Pages.
- [x] Guardar dados dos domínios em DOMINIOS.md.
- [x] Criar homepage oficial v1.0.
- [x] Implementar sistema bilingue PT/EN.
- [x] Integrar logo oficial no site.

## Pendente

- [ ] Apontar pjcorelabs.co.uk para pjcorelabs.com.
- [ ] Criar email geral@pjcorelabs.com.
- [ ] Finalizar identidade visual oficial completa.
- [ ] Criar páginas dedicadas para os projetos principais.
- [ ] Criar página Workstation OS.
- [ ] Criar página Repositório de Solicitadoria.
- [ ] Criar página Leis UK para Portugueses.
- [ ] Criar página AI Encyclopedia.

```

---

## DOMINIOS.md

```markdown
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

```

---

## Workflow GitHub Pages


```yaml
name: Deploy PJCore Labs Website

on:
  push:
    branches:
      - main
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}

    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Pages
        uses: actions/configure-pages@v5

      - name: Upload website folder
        uses: actions/upload-pages-artifact@v3
        with:
          path: website

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4

```

---

## Regras importantes para a próxima conversa


- Trabalhar passo a passo.
- Não enviar vários passos na mesma resposta.
- Confirmar `git status` antes de alterações importantes.
- Usar o script de fecho de atualização:

```bash
./scripts/uteis/fechar-atualizacao.sh "Mensagem do commit"
```

- Para gerar nova continuidade, usar:

```bash
./scripts/uteis/muda-o-disco.sh
```

- A pasta `website/` é publicada via GitHub Actions.
- Não mover o site para a raiz.
- Não mexer no DNS às cegas.

