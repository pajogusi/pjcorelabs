
(function () {
    "use strict";

    const TEMPO_INATIVIDADE = 2 * 60 * 1000;
    let temporizador = null;
    let ativo = false;

    const overlay = document.createElement("div");
    overlay.className = "blessed-screensaver";
    overlay.setAttribute("aria-hidden", "true");

    overlay.innerHTML = `
        <div class="blessed-screensaver-conteudo">
            <img
                src="/static/blessed-logo.png"
                alt="Blessed"
                class="blessed-screensaver-logo"
            >
            <div class="blessed-screensaver-texto">Toca para continuar</div>
        </div>
    `;

    document.body.appendChild(overlay);

    function formularioEmUso() {
        const el = document.activeElement;

        if (el && (
            el.tagName === "INPUT" ||
            el.tagName === "TEXTAREA" ||
            el.tagName === "SELECT"
        )) {
            return true;
        }

        const modalAberto = document.querySelector(
            '.modal-marcacao:not([hidden]), dialog[open], [role="dialog"]:not([hidden])'
        );

        return !!modalAberto;
    }

    function mostrar() {
        if (formularioEmUso()) {
            reiniciar();
            return;
        }

        ativo = true;
        overlay.classList.add("ativo");
        overlay.setAttribute("aria-hidden", "false");
    }

    function esconder() {
        if (!ativo) return;

        ativo = false;
        overlay.classList.remove("ativo");
        overlay.setAttribute("aria-hidden", "true");
    }

    function reiniciar() {
        esconder();

        clearTimeout(temporizador);
        temporizador = setTimeout(mostrar, TEMPO_INATIVIDADE);
    }

    [
        "pointerdown",
        "touchstart",
        "keydown",
        "mousemove",
        "wheel",
        "scroll"
    ].forEach(function (evento) {
        document.addEventListener(evento, reiniciar, {
            passive: true
        });
    });

    overlay.addEventListener("pointerdown", function (e) {
        e.preventDefault();
        reiniciar();
    });

    document.addEventListener("visibilitychange", function () {
        if (!document.hidden) {
            reiniciar();
        }
    });

    reiniciar();
})();

/*
 * Ajuda comum dos campos de data de nascimento.
 * Aceita escrita compacta (20091970) e com separadores (- / .),
 * apresentando sempre DD/MM/AAAA antes das validações já existentes.
 */
(function () {
    "use strict";

    const SELETORES = "#dataNascimentoVisivel, #nascimentoCliente";

    function formatarDataNascimento(valor) {
        const texto = String(valor || "").trim();
        if (!texto) return "";

        const iso = texto.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (iso) {
            return `${iso[3]}/${iso[2]}/${iso[1]}`;
        }

        const numeros = texto.replace(/\D/g, "").slice(0, 8);
        if (numeros.length <= 2) return numeros;
        if (numeros.length <= 4) {
            return numeros.slice(0, 2) + "/" + numeros.slice(2);
        }
        return (
            numeros.slice(0, 2) + "/" +
            numeros.slice(2, 4) + "/" +
            numeros.slice(4)
        );
    }

    document.addEventListener("input", function (evento) {
        const campo = evento.target.closest && evento.target.closest(SELETORES);
        if (!campo) return;

        const formatado = formatarDataNascimento(campo.value);
        if (campo.value !== formatado) {
            campo.value = formatado;
        }
        campo.setCustomValidity("");
    });

    document.addEventListener("paste", function (evento) {
        const campo = evento.target.closest && evento.target.closest(SELETORES);
        if (!campo || !evento.clipboardData) return;

        const texto = evento.clipboardData.getData("text");
        const formatado = formatarDataNascimento(texto);

        if (/^\d{2}\/\d{2}\/\d{4}$/.test(formatado)) {
            evento.preventDefault();
            campo.value = formatado;
            campo.setCustomValidity("");
            campo.dispatchEvent(new Event("input", { bubbles: true }));
        }
    }, true);
})();
