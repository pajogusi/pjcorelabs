# Ausências e encerramentos — Multiuser

Base remota: `work/multiuser-series`, commit `ce95fbec5045a45e27fe5c0d300450da0e07bb21`.
Esta branch inclui as marcações em série anteriores.

## Funcionamento

Na agenda semanal, clicar num horário e escolher o separador «Ausência /
Encerramento», junto dos separadores «Clientes» e «Pessoal». Escolher tipo,
profissional (para ausências), motivo, data inicial e data final. «Dia inteiro»
inclui todas as datas selecionadas. Ao desmarcá-lo, indicar as horas inicial e
final. O período pode atravessar várias datas.

- Barbeiros comuns criam/eliminam apenas ausências próprias.
- Gestor/Admin gerem ausências de qualquer profissional e encerramentos globais.
- As ausências só ocupam a agenda do profissional respetivo.
- Encerramentos ocupam todas as agendas.
- A existência de marcações ou reservas online válidas provoca conflito: nada é
  cancelado, deslocado ou criado automaticamente.
- A grelha mostra os períodos como blocos, incluindo os dias intermediários.
- Clicar num bloco abre os detalhes; eliminar volta a disponibilizar o horário.
- Os limites dos intervalos não se sobrepõem: uma visita pode terminar exatamente
  quando a ausência começa ou começar exatamente quando termina.

As verificações abrangem marcações individuais, todas as datas das séries,
disponibilidade, reservas públicas/primeiro disponível, edição de duração e
reativação de marcações canceladas. Forçar a duração não permite ultrapassar
uma ausência ou encerramento.

A reserva pública verifica e grava o horário dentro da mesma transação SQLite
usada pelas novas indisponibilidades, impedindo que ambos ocupem o mesmo horário
por uma corrida entre pedidos. Admins não aparecem como profissionais na reserva
pública.

## Migração e instalação

A migração cria a tabela própria `indisponibilidades` e índice, sem apagar dados
existentes. Não importar as indisponibilidades/BD da produção para a Multiuser.

Destinado apenas a `/home/paulo/Blessed-Multiuser`, serviço
`blessed-multiuser.service`, porta 5003. Instalação e teste funcional no Sentinela
continuam pendentes: esta sessão não tem acesso a esse servidor.
Antes de instalar: confirmar branch/alterações locais e `BLESSED_DB` efetivo,
fazer backup SQLite da BD própria, aplicar os commits de séries e ausências,
testar e reiniciar apenas o serviço Multiuser. Confirmar também o worker/timer
da fila SMS conforme `MULTIUSER-SERIES.md`.

## Validação

```sh
BLESSED_DISABLE_SMS=1 python3 tests_multiuser.py
BLESSED_DISABLE_SMS=1 python3 tests_series.py
BLESSED_DISABLE_SMS=1 python3 tests_absences.py
```

19 verificações existentes + 17 testes de séries + 23 testes de indisponibilidades:
59 sem falhas, com dados sintéticos e SMS simulados. Compilação Python,
JavaScript da agenda/indisponibilidades e `git diff --check` também verificados.
A interface foi renderizada nos testes Flask; inspeção visual num navegador e
validação no equipamento real permanecem pendentes.

Bloqueios pessoais por barbeiro também disponíveis; ver `MULTIUSER-TABS.md`.
