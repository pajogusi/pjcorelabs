(() => {
    const form = document.getElementById('formIndisponibilidade');
    if (!form) return;
    const tipo = document.getElementById('tipoIndisponibilidade');
    const campoBarbeiro = document.getElementById('campoBarbeiroIndisponibilidade');
    const barbeiro = document.getElementById('barbeiroIndisponibilidade');
    const resultado = document.getElementById('resultadoIndisponibilidade');
    function escolherTipo() {
        const encerramento = tipo.value === 'encerramento';
        if (campoBarbeiro) campoBarbeiro.hidden = encerramento;
        if (barbeiro) {
            barbeiro.disabled = encerramento;
            barbeiro.required = !encerramento;
        }
    }
    tipo.addEventListener('change', escolherTipo);
    escolherTipo();
    function mostrarErro(dados) {
        resultado.replaceChildren();
        const texto = document.createElement('p');
        texto.textContent = dados.erro || 'Não foi possível guardar a alteração.';
        resultado.append(texto);
        if (dados.conflitos && dados.conflitos.length) {
            const lista = document.createElement('ul');
            dados.conflitos.forEach(conflito => {
                const item = document.createElement('li');
                item.textContent = `${conflito.data} · ${conflito.inicio}–${conflito.fim} · ${conflito.nome}`;
                lista.append(item);
            });
            resultado.append(lista);
        }
        resultado.classList.add('periodo-erro');
    }
    form.addEventListener('submit', async event => {
        event.preventDefault();
        const botao = form.querySelector('[type="submit"]');
        botao.disabled = true;
        resultado.textContent = 'A verificar o período…';
        resultado.classList.remove('periodo-erro');
        try {
            const resposta = await fetch(form.action, {method: 'POST', body: new FormData(form)});
            const dados = await resposta.json();
            if (!resposta.ok || !dados.ok) { mostrarErro(dados); return; }
            const url = new URL(window.location.href);
            url.searchParams.set('data', dados.data);
            url.searchParams.set('barbeiro', dados.barbeiro_id || 'todos');
            url.hash = 'painelPeriodos';
            window.location.href = url.toString();
        } catch (_) {
            mostrarErro({erro: 'Não foi possível confirmar a alteração. Atualiza a agenda antes de tentar novamente.'});
        } finally {
            botao.disabled = false;
        }
    });
    document.querySelectorAll('.eliminar-periodo').forEach(botao => {
        botao.addEventListener('click', async () => {
            if (!confirm('Eliminar este período e voltar a disponibilizar o horário?')) return;
            botao.disabled = true;
            try {
                const resposta = await fetch(`/indisponibilidades/${botao.dataset.periodoId}/eliminar`, {method: 'POST'});
                const dados = await resposta.json();
                if (!resposta.ok || !dados.ok) { mostrarErro(dados); return; }
                window.location.reload();
            } catch (_) {
                mostrarErro({erro: 'Não foi possível confirmar a eliminação. Atualiza a agenda.'});
            } finally {
                botao.disabled = false;
            }
        });
    });
    if (window.location.hash === '#painelPeriodos') document.getElementById('painelPeriodos').open = true;
})();
