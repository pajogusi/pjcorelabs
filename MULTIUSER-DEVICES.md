# Equipamentos nos registos de atividade da Multiuser

Nova página Equipamento, disponível para cada utilizador pela agenda e também
pelas Definições. Permite dar um nome ao navegador atual (até 80 caracteres).
Cada navegador tem um identificador aleatório persistente e um token próprio
para validar a alteração do seu nome. Um cookie desconhecido é substituído;
o cliente não escolhe o identificador. Cookie HTTP-only, SameSite=Lax,
Secure em HTTPS e validade de um ano. O nome não é autenticação nem prova de
identidade do hardware. Limpar cookies ou trocar de navegador cria outra
identificação. Cookie `blessed_multiuser_equipamento` separado da produção.

Migração aditiva: tabela equipamentos e colunas novas em atividade_log.
Preserva logs antigos. Novos registos capturam o utilizador (ID, nome e
username), equipamento (ID, nome e indicação de navegador novo), categoria de
dispositivo e User-Agent, além dos campos existentes. O nome é guardado no
momento do pedido: renomear não modifica o histórico. Login e logout conservam
o ator correto; passwords, corpo dos pedidos, cookies e tokens não são
registados. Uma falha na identificação/log não impede o pedido principal.

Admin > Logs mostra as novas colunas e mantém o envio por email manual.
Novo atalho Logs na agenda, exclusivo do administrador. CSV exportado inclui
as novas colunas, protegendo texto que poderia ser interpretado como fórmula.
Não foram ativados envios automáticos nem alterações no SMS ou em produção.

Validação em SQLite sintético: 104 verificações sem falhas, incluindo 11 testes
de equipamentos, isolamento entre navegadores, token de alteração, validação,
escaping HTML/CSV, cookies, snapshots de nomes, login/logout, permissões e
migração repetida com logs antigos. Python e diff verificados.
A apresentação no Brave do Sentinela fica para validação após instalar.

```sh
BLESSED_DISABLE_SMS=1 python3 tests_multiuser.py
BLESSED_DISABLE_SMS=1 python3 -m unittest tests_series.SeriesTests tests_absences.AbsenceTests tests_personal.PersonalTests tests_week.WeekTests tests_client_search.ClientSearchTests tests_devices.DeviceTests
```
