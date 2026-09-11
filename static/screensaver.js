
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
