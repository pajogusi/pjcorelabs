#!/usr/bin/env python3

import os
from datetime import datetime

from app import get_db, enviar_sms_do_barbeiro


def processar_fila():
    if os.environ.get("BLESSED_DISABLE_SMS") == "1":
        print("SMS WORKER: bloqueado por BLESSED_DISABLE_SMS; fila não alterada")
        return

    agora = datetime.now().isoformat(timespec="seconds")
    con = get_db()

    mensagens = con.execute("""
        SELECT
            s.id,
            s.marcacao_id,
            s.telefone_destino,
            s.mensagem,
            s.tentativas,
            s.tipo,
            m.serie_id,
            m.barbeiro_id,
            m.estado AS marcacao_estado
        FROM sms_fila s
        LEFT JOIN marcacoes m ON m.id = s.marcacao_id
        WHERE s.estado = 'pendente'
          AND s.previsto_para IS NOT NULL
          AND s.previsto_para <= ?
          AND s.tentativas < 3
        ORDER BY s.previsto_para, s.id
    """, (agora,)).fetchall()

    print(f"SMS WORKER: {len(mensagens)} SMS para processar")

    for sms in mensagens:
        sms_id = sms["id"]

        mensagem = sms["mensagem"]
        serie_ativa = False
        if sms["tipo"] == "confirmacao_serie":
            ocorrencias = con.execute("""
                SELECT m.inicio, c.nome FROM marcacoes m JOIN clientes c ON c.id = m.cliente_id
                WHERE m.serie_id = ? AND m.barbeiro_id = ? AND m.estado = 'marcada' AND m.inicio >= ?
                ORDER BY m.inicio
            """, (sms["serie_id"], sms["barbeiro_id"], agora)).fetchall()
            serie_ativa = bool(ocorrencias)
            if serie_ativa:
                datas = ", ".join(datetime.fromisoformat(item["inicio"]).strftime("%d/%m/%Y") for item in ocorrencias)
                hora = datetime.fromisoformat(ocorrencias[0]["inicio"]).strftime("%H:%M")
                mensagem = f"Blessed Barbearia: Ola {ocorrencias[0]['nome']}, confirmamos as suas marcacoes para os dias {datas}, sempre as {hora}."
        # Validar a mensagem de acordo com o tipo.
        #
        # - cancelamento: a marcação deve estar cancelada;
        # - confirmacao_serie: deve existir pelo menos uma ocorrência ativa;
        # - restantes SMS: a marcação deve continuar marcada.
        if sms["tipo"] == "cancelamento":
            sms_valido = bool(
                sms["barbeiro_id"]
                and sms["marcacao_estado"] == "cancelada"
            )
        elif sms["tipo"] == "confirmacao_serie":
            sms_valido = bool(
                sms["barbeiro_id"]
                and serie_ativa
            )
        else:
            sms_valido = bool(
                sms["barbeiro_id"]
                and sms["marcacao_estado"] == "marcada"
            )

        if not sms_valido:
            con.execute("""
                UPDATE sms_fila
                SET estado = 'cancelado',
                    erro = ?,
                    ultima_tentativa_em = ?
                WHERE id = ? AND estado = 'pendente'
            """, (
                f"Marcação em estado: {sms['marcacao_estado'] or 'inexistente'}",
                agora,
                sms_id,
            ))
            con.commit()
            print(f"SMS {sms_id}: cancelado - marcação não está marcada")
            continue

        enviado = enviar_sms_do_barbeiro(
            sms["barbeiro_id"],
            sms["telefone_destino"],
            mensagem,
        )

        if enviado:
            con.execute("""
                UPDATE sms_fila
                SET estado = 'enviado',
                    tentativas = tentativas + 1,
                    enviado_em = ?,
                    ultima_tentativa_em = ?,
                    erro = NULL
                WHERE id = ? AND estado = 'pendente'
            """, (agora, agora, sms_id))
            con.commit()
            print(f"SMS {sms_id}: enviado")
        else:
            novas_tentativas = sms["tentativas"] + 1
            novo_estado = "falhou" if novas_tentativas >= 3 else "pendente"

            con.execute("""
                UPDATE sms_fila
                SET tentativas = ?,
                    estado = ?,
                    ultima_tentativa_em = ?,
                    erro = ?
                WHERE id = ? AND estado = 'pendente'
            """, (
                novas_tentativas,
                novo_estado,
                agora,
                "Falha no envio pelo fornecedor SMS",
                sms_id,
            ))
            con.commit()

            if novo_estado == "falhou":
                print(f"SMS {sms_id}: falhou definitivamente após 3 tentativas")
            else:
                print(
                    f"SMS {sms_id}: falhou - "
                    f"tentativa {novas_tentativas}/3"
                )

    con.close()


if __name__ == "__main__":
    processar_fila()
