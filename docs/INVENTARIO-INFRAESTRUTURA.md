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

## Atualização do site — 2026-10-01

- Fonte: `pajogusi/pjcorelabs/website/`.
- Página principal: `website/index.html` (secção PJCore Agenda adicionada).
- Portefólio: `website/pages/projects.html` (cartão PJCore Agenda).
- Produto: `website/pages/pjcore-agenda.html`.
- Demonstração independente: `website/pages/pjcore-agenda-demo.html` (dados fictícios apenas, sem envio real de SMS e sem integração com produção).
- Condições divulgadas: £12/mês, 200 SMS/mês, 15 dias de teste com 50 SMS. Confirmar operacionalização do registo/teste antes de prometer ativação automática.
- **Deploy público ainda por confirmar**: commits no GitHub não garantem que Cloudflare publique automaticamente. Verificar configuração Pages e depois URL público.
