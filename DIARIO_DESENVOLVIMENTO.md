# Diário de Desenvolvimento — PJCore Labs

## 2026-07-05

- Definida regra oficial para relatórios de continuidade:
  - os ficheiros `documentation/reports/CONTINUIDADE_PJCORE_LABS_*.md` são temporários;
  - servem apenas para transição entre conversas;
  - não são documentação oficial permanente;
  - foram adicionados ao `.gitignore`;
  - a regra foi registada no `CADERNO_DE_ENCARGOS.md`.

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
