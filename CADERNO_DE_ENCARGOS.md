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

## Continuidade entre conversas

- O script `./scripts/uteis/muda-o-disco.sh` gera relatórios temporários de continuidade.
- Estes relatórios servem apenas para transportar contexto entre conversas.
- Os ficheiros `documentation/reports/CONTINUIDADE_PJCORE_LABS_*.md` não são documentação oficial permanente.
- Depois de a informação importante estar integrada nos documentos oficiais, estes relatórios podem ser apagados.
- A documentação oficial do projeto continua a ser composta por:
  - README.md
  - CADERNO_DE_ENCARGOS.md
  - DIARIO_DESENVOLVIMENTO.md
  - CHANGELOG.md
  - ROADMAP.md
  - TODO.md
  - DOMINIOS.md


## Regra — Contador de visitas

Todas as novas páginas HTML dentro de `website/` devem incluir o contador GoatCounter próprio do PJCore Labs antes de `</body>`:

```html
<script data-goatcounter="https://pjcorelabs.goatcounter.com/count"
        async src="//gc.zgo.at/count.js"></script>
```

Antes de fechar qualquer atualização que crie ou altere páginas HTML, correr:

```bash
./scripts/uteis/verificar-contador.sh
```

Nenhuma nova página pública deve ser publicada sem contador.
