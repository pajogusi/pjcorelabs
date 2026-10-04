# Marcações em série — Multiuser

Base: `dev/multiusers-isolamento`, commit `dd3dfc47c532ef59844966a17c041884f3a9d525`.
Referência de leitura: `work/equipamentos-semana-sms`.

Implementação destinada exclusivamente a `/home/paulo/Blessed-Multiuser`, serviço
`blessed-multiuser.service`, porta 5003. Não instalar na Blessed em produção.

## Comportamento

- Nova marcação: escolher «Repetir semanalmente» e o total, incluindo a primeira.
- Até 52 ocorrências, todas com o mesmo barbeiro, cliente, dia da semana e hora.
- Todas as datas são verificadas ao guardar. Um conflito impede a criação completa.
- A validação e criação usam uma transação SQLite para impedir séries simultâneas
  sobrepostas na mesma agenda; outras agendas continuam independentes.
- Reservas online ainda válidas também ocupam o horário.
- A série gera uma confirmação SMS na fila com todas as datas; cada ocorrência
  mantém lembretes próprios às 18:00 do dia anterior e uma hora antes.
- O worker volta a consultar a autorização SMS do barbeiro antes do envio.
- Cancelar a série a partir de uma ocorrência mantém as anteriores e cancela
  apenas as futuras ainda marcadas. Os respetivos SMS e emails pendentes são
  cancelados. Uma confirmação ainda pendente usa só as datas que continuam ativas.
- Gestor/Admin podem escolher outra agenda; barbeiros comuns mantêm as permissões
  e a propriedade de clientes existentes.
- Migração aditiva: coluna `serie_id` e índice; dados existentes são preservados.

O ficheiro `email_worker.py` desta branch é o worker de **SMS**, apesar do nome.
É necessário confirmar no Sentinela qual o timer/serviço que o executa na
Multiuser antes de afirmar que a confirmação em fila está operacional.

## Validação

Executados numa cópia isolada com dados sintéticos e envios simulados:

```sh
BLESSED_DISABLE_SMS=1 python3 tests_multiuser.py
BLESSED_DISABLE_SMS=1 python3 tests_series.py
python3 -m py_compile app.py email_worker.py tests_series.py
```

Resultado: 19 verificações existentes + 17 testes de séries, zero falhas.
JavaScript da agenda validado com `node --check`; diff validado com `git diff --check`.
`tests_blessed.py` não foi executado: exige a BD de produção, indisponível aqui.

## Instalação pendente

A alteração está guardada no GitHub, sem alteração de serviços ou BD no Sentinela.
Antes de instalar, confirmar branch/alterações locais, o `BLESSED_DB` efetivo e o
worker/timer da Multiuser. Fazer backup SQLite da BD própria, aplicar o commit,
executar os testes e só depois reiniciar `blessed-multiuser.service`.
Não copiar bases de dados nem reiniciar serviços da Blessed em produção.

## Próximas funcionalidades

Ausências/encerramentos, bloqueios pessoais por barbeiro, semana automática,
identificação de equipamentos e logs completos permanecem por transportar.
