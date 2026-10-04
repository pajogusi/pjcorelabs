# Painel de marcações com três separadores

Atualização da Multiuser sobre `work/multiuser-absences` (`9cc4fb9`).
Referência de leitura: interface de `work/equipamentos-semana-sms`.

O painel separado de indisponibilidades foi retirado. A janela que abre ao
clicar num horário contém agora os três separadores, seguindo a interface
de referência: Clientes, Pessoal, Ausência / Encerramento.

- Clientes mantém o formulário existente, as séries e as permissões.
- Pessoal permite descrição e duração de 15 a 240 minutos, em intervalos de 15,
  usando o dia/hora do cabeçalho. Não cria clientes nem comunicações.
- Ausência / Encerramento oferece motivo, data inicial/final, Dia inteiro e horas
  opcionais. Datas finais de dias completos são inclusivas no formulário.
- Compromissos e indisponibilidades aparecem como blocos na grelha. Clicar abre
  detalhes e eliminação; compromissos pessoais também podem ser editados.
- Barbeiros comuns só gerem períodos próprios. Gestor/Admin podem gerir os de
  outros profissionais e os encerramentos globais.

Os bloqueios pessoais respeitam marcações/reservas/ausências/encerramentos e
só afetam o respetivo profissional. São considerados na disponibilidade, todas
as datas de séries, reservas online, alteração de duração e reativação de
marcações canceladas. Alteração/criação e validação usam uma transação SQLite.

Migração: cria a tabela `bloqueios_pessoais` e um índice; preserva as tabelas e
dados existentes. Aplicar apenas a `/home/paulo/Blessed-Multiuser`, serviço
`blessed-multiuser.service`, porta 5003. Produção não é alvo desta alteração.

Validação: 19 verificações existentes, 17 testes de séries, 23 de ausências e
16 de períodos pessoais/interface. Total: 75 sem falhas. Python e JavaScript
compilados/validados; diff verificado. Verificação DOM adicional confirmou as
trocas de separador, formulários independentes, conversão de dia inteiro e
horas opcionais e apresentação segura de conflitos. Não foi possível obter
inspeção visual por navegador nesta sessão; teste no Brave é a verificação
final após instalar.

```sh
BLESSED_DISABLE_SMS=1 python3 tests_multiuser.py
BLESSED_DISABLE_SMS=1 python3 -m unittest tests_series.SeriesTests tests_absences.AbsenceTests tests_personal.PersonalTests
```

O trabalho do worker/timer SMS mantém-se separado e ainda exige confirmação
no Sentinela. Não alterar fornecedores ou serviços da Blessed em produção.
