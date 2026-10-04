(() => {
    const cliente = document.getElementById('formNovaMarcacao');
    const pessoal = document.getElementById('formPessoal');
    const ausencia = document.getElementById('formIndisponibilidade');
    const tipo = document.getElementById('tipoIndisponibilidade');
    const diaInteiro = document.getElementById('diaInteiroIndisponibilidade');
    const modalPeriodo = document.getElementById('modalPeriodo');
    const editar = document.getElementById('formEditarPessoal');
    const eliminar = document.getElementById('eliminarPeriodo');
    let periodoAtual;
    function formatarDataHora(valor) {
        const [data, hora] = valor.split('T');
        return `${data.split('-').reverse().join('/')} ${hora.slice(0,5)}`;
    }
    function mostrarErro(caixa, dados) {
        caixa.replaceChildren();
        const texto = document.createElement('p');
        texto.textContent = dados.erro || 'Não foi possível guardar a alteração.';
        caixa.append(texto);
        if (dados.conflitos && dados.conflitos.length) {
            const lista = document.createElement('ul');
            dados.conflitos.forEach(c => {
                const item = document.createElement('li');
                item.textContent = `${c.data} · ${c.inicio}–${c.fim} · ${c.nome}`;
                lista.append(item);
            });
            caixa.append(lista);
        }
    }
    function atualizarTipo() {
        const global = tipo.value === 'encerramento';
        const barbeiro = document.getElementById('barbeiroIndisponibilidade');
        document.getElementById('campoBarbeiroIndisponibilidade').hidden = global;
        barbeiro.disabled = global;
        barbeiro.required = !global && barbeiro.type !== 'hidden';
        document.getElementById('explicacaoIndisponibilidade').textContent = global
            ? 'Encerramento bloqueia toda a barbearia durante este período.'
            : 'Ausência bloqueia apenas a agenda do profissional durante este período.';
    }
    function atualizarDiaInteiro() {
        document.getElementById('horasIndisponibilidade').hidden = diaInteiro.checked;
        ['horaInicioIndisponibilidade', 'horaFimIndisponibilidade'].forEach(id => {
            document.getElementById(id).required = !diaInteiro.checked;
        });
    }
    window.modoAgenda = 'cliente';
    window.definirModoAgenda = modo => {
        window.modoAgenda = modo;
        cliente.hidden = modo !== 'cliente';
        pessoal.hidden = modo !== 'pessoal';
        ausencia.hidden = modo !== 'indisponibilidade';
        [['modoCliente','cliente'],['modoPessoal','pessoal'],['modoIndisponibilidade','indisponibilidade']].forEach(([id,valor]) => {
            const botao = document.getElementById(id);
            botao.classList.toggle('ativo', modo === valor);
            botao.setAttribute('aria-selected', String(modo === valor));
        });
        document.getElementById('tituloNovaMarcacao').textContent = modo === 'cliente'
            ? 'Nova marcação' : modo === 'pessoal' ? 'Novo compromisso pessoal' : 'Nova ausência / encerramento';
        document.querySelector('#modalMarcacao .navegador-horario').hidden = modo === 'indisponibilidade';
        if (modo === 'indisponibilidade') {
            const data = document.getElementById('dataMarcacao').value;
            document.getElementById('dataInicioIndisponibilidade').value = data;
            document.getElementById('dataFimIndisponibilidade').value = data;
            atualizarTipo(); atualizarDiaInteiro();
        }
        if (typeof verificarDisponibilidade === 'function') verificarDisponibilidade();
    };
    window.reiniciarModosAgenda = () => {
        pessoal.reset(); ausencia.reset();
        document.getElementById('avisoPessoal').replaceChildren();
        document.getElementById('resultadoIndisponibilidade').replaceChildren();
        atualizarTipo(); atualizarDiaInteiro();
        // The existing click handler fills the date/hour and refreshes availability.
        window.modoAgenda = 'cliente';
        cliente.hidden = false; pessoal.hidden = true; ausencia.hidden = true;
        document.querySelector('#modalMarcacao .navegador-horario').hidden = false;
        document.getElementById('tituloNovaMarcacao').textContent = 'Nova marcação';
        ['modoCliente','modoPessoal','modoIndisponibilidade'].forEach((id, i) => {
            const botao = document.getElementById(id);
            botao.classList.toggle('ativo', i === 0);
            botao.setAttribute('aria-selected', String(i === 0));
        });
    };
    document.getElementById('modoCliente').addEventListener('click', () => window.definirModoAgenda('cliente'));
    document.getElementById('modoPessoal').addEventListener('click', () => window.definirModoAgenda('pessoal'));
    document.getElementById('modoIndisponibilidade').addEventListener('click', () => window.definirModoAgenda('indisponibilidade'));
    tipo.addEventListener('change', atualizarTipo);
    diaInteiro.addEventListener('change', atualizarDiaInteiro);
    ['duracaoPessoal','barbeiroPessoal'].forEach(id => document.getElementById(id).addEventListener('change', () => verificarDisponibilidade()));
    async function guardar(form, dados, caixa) {
        const botao = form.querySelector('[type="submit"]');
        botao.disabled = true;
        caixa.textContent = 'A verificar…';
        try {
            const resposta = await fetch(form.action, {method:'POST', body:dados});
            const resultado = await resposta.json();
            if (!resposta.ok || !resultado.ok) { mostrarErro(caixa, resultado); return; }
            const url = new URL(window.location.href);
            if (resultado.data) url.searchParams.set('data', resultado.data);
            if (resultado.barbeiro_id) url.searchParams.set('barbeiro', resultado.barbeiro_id);
            else if (resultado.tipo === 'encerramento') url.searchParams.set('barbeiro', 'todos');
            url.hash = '';
            window.location.href = url.toString();
        } catch (_) {
            mostrarErro(caixa, {erro:'Não foi possível confirmar a alteração. Atualiza a agenda antes de tentar novamente.'});
        } finally { botao.disabled = false; }
    }
    pessoal.addEventListener('submit', event => {
        event.preventDefault();
        const dados = new FormData(pessoal);
        dados.set('inicio', document.getElementById('inicioMarcacao').value);
        guardar(pessoal, dados, document.getElementById('avisoPessoal'));
    });
    ausencia.addEventListener('submit', event => {
        event.preventDefault();
        const dados = new FormData(ausencia);
        const inicio = document.getElementById('dataInicioIndisponibilidade').value;
        const fim = document.getElementById('dataFimIndisponibilidade').value;
        const caixa = document.getElementById('resultadoIndisponibilidade');
        if (!inicio || !fim || fim < inicio) { mostrarErro(caixa,{erro:'A data final não pode ser anterior à data inicial.'}); return; }
        if (diaInteiro.checked) {
            // End dates are inclusive in the form, exclusive in the database.
            const ultimo = new Date(`${fim}T12:00:00`);
            ultimo.setDate(ultimo.getDate()+1);
            const proximo = `${ultimo.getFullYear()}-${String(ultimo.getMonth()+1).padStart(2,'0')}-${String(ultimo.getDate()).padStart(2,'0')}`;
            dados.set('inicio', `${inicio}T00:00`);
            dados.set('fim', `${proximo}T00:00`);
        } else {
            dados.set('inicio', `${inicio}T${document.getElementById('horaInicioIndisponibilidade').value}`);
            dados.set('fim', `${fim}T${document.getElementById('horaFimIndisponibilidade').value}`);
        }
        guardar(ausencia, dados, caixa);
    });
    // Period blocks use their own dialog rather than the client appointment dialog.
    document.addEventListener('click', event => {
        const bloco = event.target.closest('.periodo-agenda');
        if (!bloco) return;
        event.stopImmediatePropagation();
        periodoAtual = bloco.dataset;
        const pessoal = periodoAtual.tipo === 'pessoal';
        const permitido = periodoAtual.podeAlterar === '1';
        document.getElementById('tituloPeriodo').textContent = pessoal ? 'Compromisso pessoal' : periodoAtual.tipo === 'encerramento' ? 'Encerramento' : 'Ausência';
        document.getElementById('resumoPeriodo').textContent = `${formatarDataHora(periodoAtual.inicio)} — ${formatarDataHora(periodoAtual.fim)}${periodoAtual.barbeiro ? ' · '+periodoAtual.barbeiro : ''}`;
        document.getElementById('motivoPeriodo').textContent = periodoAtual.motivo;
        editar.hidden = !pessoal || !permitido;
        eliminar.hidden = !permitido;
        editar.action = `/bloqueios/${periodoAtual.periodoId}/editar`;
        document.getElementById('editarDescricaoPessoal').value = periodoAtual.motivo;
        document.getElementById('editarInicioPessoal').value = periodoAtual.inicio.slice(0,16);
        document.getElementById('editarDuracaoPessoal').value = periodoAtual.duracao;
        document.getElementById('resultadoPeriodo').replaceChildren();
        modalPeriodo.hidden = false;
    }, true);
    editar.addEventListener('submit', event => {
        event.preventDefault(); guardar(editar, new FormData(editar), document.getElementById('resultadoPeriodo'));
    });
    eliminar.addEventListener('click', async () => {
        if (!periodoAtual || !confirm('Eliminar este período e voltar a disponibilizar o horário?')) return;
        eliminar.disabled = true;
        const prefixo = periodoAtual.tipo === 'pessoal' ? 'bloqueios' : 'indisponibilidades';
        try {
            const resposta = await fetch(`/${prefixo}/${periodoAtual.periodoId}/eliminar`, {method:'POST'});
            const dados = await resposta.json();
            if (!resposta.ok || !dados.ok) { mostrarErro(document.getElementById('resultadoPeriodo'), dados); return; }
            window.location.reload();
        } catch (_) { mostrarErro(document.getElementById('resultadoPeriodo'), {erro:'Não foi possível confirmar a eliminação. Atualiza a agenda.'}); }
        finally { eliminar.disabled = false; }
    });
    document.querySelectorAll('[data-fechar-periodo]').forEach(botao => botao.addEventListener('click', () => {modalPeriodo.hidden=true;}));
    document.addEventListener('keydown', event => {if(event.key==='Escape') modalPeriodo.hidden=true;});
    atualizarTipo(); atualizarDiaInteiro();
})();
