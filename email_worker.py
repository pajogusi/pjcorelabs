#!/usr/bin/env python3

from datetime import datetime

from app import get_db, enviar_sms_smsgate


def processar_fila():
    agora = datetime.now().isoformat(timespec="seconds")
    con = get_db()

    mensagens = con.execute("""
        SELECT
            s.id,
            s.marcacao_id,
            s.telefone_destino,
            s.mensagem,
            s.tentativas,
            m.estado AS marcacao_estado
        FROM sms_fila s
        LEFT JOIN marcacoes m ON m.id = s.marcacao_id
        WHERE s.estado = 'pendente'
          AND s.previsto_para IS NOT NULL
          AND s.previsto_para <= ?
        ORDER BY s.previsto_para, s.id
    """, (agora,)).fetchall()

    print(f"SMS WORKER: {len(mensagens)} SMS para processar")

    for sms in mensagens:
        sms_id = sms["id"]

        # Não enviar lembrete se a marcação já não estiver marcada.
        if sms["marcacao_id"] is not None and sms["marcacao_estado"] != "marcada":
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

        enviado = enviar_sms_smsgate(
            sms["telefone_destino"],
            sms["mensagem"],
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
            con.execute("""
                UPDATE sms_fila
                SET tentativas = tentativas + 1,
                    ultima_tentativa_em = ?,
                    erro = ?
                WHERE id = ? AND estado = 'pendente'
            """, (
                agora,
                "Falha no envio pelo SMSGate",
                sms_id,
            ))
            con.commit()
            print(f"SMS {sms_id}: falhou - permanece pendente")

    con.close()


if __name__ == "__main__":
    processar_fila()
