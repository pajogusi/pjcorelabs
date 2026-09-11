#!/usr/bin/env python3

from datetime import datetime

from app import get_db, enviar_email_brevo


def processar_fila():
    agora = datetime.now().isoformat(timespec="seconds")
    con = get_db()

    emails = con.execute("""
        SELECT
            e.id,
            e.marcacao_id,
            e.email_destino,
            e.assunto,
            e.mensagem,
            e.tentativas,
            m.estado AS marcacao_estado
        FROM email_fila e
        LEFT JOIN marcacoes m ON m.id = e.marcacao_id
        WHERE e.estado = 'pendente'
          AND e.previsto_para IS NOT NULL
          AND e.previsto_para <= ?
        ORDER BY e.previsto_para, e.id
    """, (agora,)).fetchall()

    print(f"EMAIL WORKER: {len(emails)} email(s) para processar")

    for email in emails:
        email_id = email["id"]

        # Um lembrete associado a uma marcação só pode ser enviado
        # enquanto a marcação continuar efetivamente marcada.
        if email["marcacao_id"] is not None and email["marcacao_estado"] != "marcada":
            con.execute("""
                UPDATE email_fila
                SET estado = 'cancelado',
                    erro = ?,
                    ultima_tentativa_em = ?
                WHERE id = ? AND estado = 'pendente'
            """, (
                f"Marcação em estado: {email['marcacao_estado'] or 'inexistente'}",
                agora,
                email_id,
            ))
            con.commit()
            print(f"EMAIL {email_id}: cancelado - marcação não está marcada")
            continue

        enviado = enviar_email_brevo(
            email["email_destino"],
            email["assunto"],
            email["mensagem"],
        )

        if enviado:
            con.execute("""
                UPDATE email_fila
                SET estado = 'enviado',
                    tentativas = tentativas + 1,
                    enviado_em = ?,
                    ultima_tentativa_em = ?,
                    erro = NULL
                WHERE id = ? AND estado = 'pendente'
            """, (agora, agora, email_id))
            con.commit()
            print(f"EMAIL {email_id}: enviado")
        else:
            con.execute("""
                UPDATE email_fila
                SET tentativas = tentativas + 1,
                    ultima_tentativa_em = ?,
                    erro = ?
                WHERE id = ? AND estado = 'pendente'
            """, (
                agora,
                "Falha no envio pela Brevo",
                email_id,
            ))
            con.commit()
            print(f"EMAIL {email_id}: falhou - permanece pendente")

    con.close()


if __name__ == "__main__":
    processar_fila()
