#!/usr/bin/env python3

from datetime import datetime

from app import get_db, enviar_sms_do_barbeiro


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
            s.tipo,
            m.serie_id,
            m.barbeiro_id,
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
        # Confirmações de série abrangem apenas as ocorrências ainda ativas.
        if not sms["barbeiro_id"] or (not serie_ativa and sms["marcacao_estado"] != "marcada") or (sms["tipo"] == "confirmacao_serie" and not serie_ativa):
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
