# Semana automática na Multiuser

A agenda sem data escolhida abre a semana seguinte a partir de sexta-feira
às 22:00 e durante sábado/domingo. Segunda-feira passa a ser a semana corrente.
Usa `BLESSED_TIMEZONE` (por defeito `Europe/Lisbon`), incluindo mudanças de hora.
Referência de leitura: `work/equipamentos-semana-sms`; produção não alterada.

Datas escolhidas nas setas ou no seletor de mês mantêm-se. A troca de barbeiro
preserva o modo automático; as setas preservam também a seleção “Todas”.
Numa página aberta, a viragem recarrega a agenda quando estiver visível,
sem diálogos abertos nem campos em edição. O filtro do barbeiro mantém-se.
Sem mudanças na base de dados, no fornecedor SMS ou nos serviços de produção.

Validação com dados sintéticos: sete testes de fronteira horária, fim de
semana, data explícita/inválida, ano novo, mudança de hora, permissões e
navegação. Verificação JavaScript adicional da espera durante edição.

```sh
BLESSED_DISABLE_SMS=1 python3 tests_multiuser.py
BLESSED_DISABLE_SMS=1 python3 -m unittest tests_series.SeriesTests tests_absences.AbsenceTests tests_personal.PersonalTests tests_week.WeekTests
```

A instalação e verificação no Brave são feitas na Multiuser do Sentinela.
