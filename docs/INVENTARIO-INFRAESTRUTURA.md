# Inventário técnico — PJCore Labs

Atualizado: 2026-10-01. Registar apenas informações verificadas; distinguir hipóteses de factos.

## Servidor Sentinela — verificado por comandos SSH

- Utilizador: `paulo`; acesso a partir do Overdrive: `ssh paulo@sentinela`.
- `cloudflared` ativo, configuração em `/etc/cloudflared/config.yml`.
- Rotas confirmadas do túnel:
  - `blessed.pjcorelabs.com` → `http://127.0.0.1:5001`.
  - `contas-atlas.pjcorelabs.com` → `http://127.0.0.1:8504`.
  - Outras rotas neste túnel → HTTP 404.
- Porta 8504: servidor Python `http.server`, diretório `/home/paulo/contas-atlas-web`, título HTML «Contas Atlas».
- Porta 8502: servidor Python `http.server`; projeto Pajó Agenda em `/home/paulo/PajoAgenda` (associação baseada na instalação do projeto e serviço conhecido; confirmar cwd se necessário).
- `nginx` e `apache2` inativos na verificação.

## Página institucional pjcorelabs.com

- O domínio principal **não está configurado** nas rotas do túnel Cloudflare do Sentinela acima.
- O repositório GitHub `pajogusi/pjcorelabs` existe, ramo `main`, e continha README institucional; a página está na subpasta `website/`, não na raiz: `website/index.html`, `website/pages/chairflow.html`, `website/css/style.css` e `website/js/language.js` (confirmado no GitHub em 2026-10-01).
- **Código-fonte localizado no GitHub:** `pajogusi/pjcorelabs/website/`. O alojamento e o mecanismo de deploy ainda não estão confirmados. Antes de assumir publicação automática, confirmar em Cloudflare projeto Pages/Workers, domínio e origem Git. Não editar Sentinela às cegas.

## Próximo trabalho

- Código-fonte identificado: `website/` no repositório `pajogusi/pjcorelabs`. Confirmar alojamento real de `pjcorelabs.com` e configuração de deploy.
- Identificar repositório/fonte e mecanismo de publicação da página.
- Só então atualizar o site institucional com o produto acordado, após confirmar o texto e as condições comerciais atuais.

## Procedimento de manutenção

1. Antes de diagnosticar um serviço, consultar este inventário e o README do respetivo projeto.
2. Quando se confirmar uma alteração de porta, domínio, serviço, diretório, repositório ou deploy, atualizar imediatamente este ficheiro no mesmo trabalho.
3. Nunca registar palavras-passe, tokens, segredos ou chaves privadas.

## Atualização corrigida do site — 2026-10-01

- Página principal `website/index.html` restaurada sem promoção adicional.
- Demonstração interativa incorporada em `website/pages/projects.html`, junto do portefólio existente; não foi criado um segundo produto comercial.
- Código da demonstração: `website/js/projects-demo.js`; estilos: `website/css/style.css`; textos PT/EN: `website/js/language.js`.
- A simulação é fictícia e local ao navegador, não envia SMS nem altera a Blessed; impede coincidências exatas de data/hora (não é um motor completo de gestão de duração de serviços).
- Páginas autónomas erradas `pjcore-agenda.html` e `pjcore-agenda-demo.html` eliminadas.
- Não divulgar preços nem condições comerciais até confirmar a apresentação final.
- **Por confirmar:** se o Cloudflare publica automaticamente o conteúdo de `website/`; verificar no painel e testar site público após deploy.

## Software comercial — estrutura confirmada 2026-10-01

- Nova secção `Software` no menu principal e na página de Projetos.
- Catálogo `website/pages/software.html` com duas utilizações do PJCore Agenda: barbearias e profissionais de manicura/pedicura.
- Páginas de produto: `website/pages/agenda-barbers.html` e `website/pages/agenda-nails.html`, cada uma com simulação própria (serviços adequados à atividade) e preçário **por baixo**.
- Simulação partilhada `website/js/projects-demo.js`; traduções PT/EN `website/js/language.js`; estilos `website/css/style.css`.
- Plano Basic: €10/mês em PT; £12/mês em EN; 200 SMS/mês; teste de 15 dias e 50 SMS; extras de 100 SMS a €2 (equivalente GBP **não definido**, confirmar antes de apresentar outro valor).
- Pedidos de teste por email; **não existe ativação automática** implementada nesta página.
- Demonstração simplificada e fictícia: não representa todas as funcionalidades comerciais, não envia SMS nem tem ligação à base de dados real.
- Página `website/pages/chairflow.html` mantida como legado sem link no portefólio; não eliminar sem confirmação.
- Publicação Cloudflare: confirmar visualmente as novas rotas após deploy.

- 2026-10-01: acrescentada vista semanal interativa (7 dias, semanas anterior/seguinte/atual, criar e editar por clique) às duas demonstrações, com traduções PT/EN e grelha responsiva. Código em `website/js/projects-demo.js` e estilos em `website/css/style.css`.
