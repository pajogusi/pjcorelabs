# Pesquisa de clientes na marcação

O campo Cliente procura a partir de duas letras, com espera de 350 ms.
Aceita parte do nome, sem distinguir maiúsculas/minúsculas ou acentos.
Mostra até 20 resultados com nome e telefone, pedindo mais texto se houver mais.
Os resultados nunca são escolhidos automaticamente: cada botão identifica
uma ficha. Tab/Enter permitem escolher; seta para baixo sai do campo para
o primeiro resultado. Sem resultados, continua possível criar um novo cliente.

Ao escolher, preenche nome, telefone, email e nascimento e abre o histórico
existente. Nome e telefone partilham o mesmo preenchimento. Respostas antigas
ou recebidas depois de fechar o diálogo não alteram os dados.
O identificador da ficha acompanha o POST para resolver nomes/telefones iguais.
Cliente sem telefone pode receber o seu primeiro telefone sem criar uma ficha
duplicada. Mudança do telefone de uma ficha já identificada é recusada para
obrigar a uma nova pesquisa.

Pesquisa, detalhe e histórico respeitam o dono do cliente. Barbeiros normais
acedem apenas à sua carteira e às suas visitas. Gestor/admin podem pesquisar
todas as carteiras. A pesquisa antiga por telefone também passa a aplicar
estas restrições. O POST revalida a autorização e a identidade escolhida.

Validação: 93 verificações Python em BD sintética, incluindo 11 novos testes
de pesquisa, permissões, identidade e dados repetidos. Verificação DOM com
respostas simuladas: preenchimento, histórico, telefone, conteúdo seguro,
ausência de resultados e respostas atrasadas. Sintaxe Python/JavaScript e diff
verificados. Verificação visual no Brave do Sentinela permanece por fazer.
Sem mudanças de esquema ou configuração SMS. Produção não alterada.

```sh
BLESSED_DISABLE_SMS=1 python3 tests_multiuser.py
BLESSED_DISABLE_SMS=1 python3 -m unittest tests_series.SeriesTests tests_absences.AbsenceTests tests_personal.PersonalTests tests_week.WeekTests tests_client_search.ClientSearchTests
```
