let temporizadorNomeCliente = null;

function limparResultadosClientes() {
    const resultados = document.getElementById('resultadosClientes');
    resultados.replaceChildren();
    resultados.hidden = true;
    nomeCliente.setAttribute('aria-expanded', 'false');
    document.getElementById('avisoPesquisaClientes').textContent = '';
}

function invalidarPesquisaCliente(limparSelecao = true) {
    versaoPesquisaCliente++;
    clearTimeout(temporizadorTelefone);
    clearTimeout(temporizadorNomeCliente);
    if (limparSelecao) document.getElementById('clienteMarcacaoId').value = '';
    limparResultadosClientes();
}

async function escolherClienteMarcacao(id) {
    const versao = ++versaoPesquisaCliente;
    clearTimeout(temporizadorTelefone);
    clearTimeout(temporizadorNomeCliente);
    document.getElementById('clienteMarcacaoId').value = '';
    try {
        const resposta = await fetch(`/api/clientes/${id}/marcacao`);
        const resultado = await resposta.json();
        if (versao !== versaoPesquisaCliente || modal.hidden) return;
        if (!resposta.ok || !resultado.ok) throw new Error();
        preencherClienteMarcacao(resultado.cliente);
    } catch (erro) {
        if (versao !== versaoPesquisaCliente || modal.hidden) return;
        const local = await window.BlessedClientesOffline?.obterClienteOffline(id);
        if (versao !== versaoPesquisaCliente || modal.hidden) return;
        if (local) {
            preencherClienteMarcacao(local);
        } else {
            document.getElementById('avisoPesquisaClientes').textContent =
                'Cliente indisponível offline. Liga à Internet para atualizar.';
        }
    }
}

async function procurarClientesPorNome() {
    const nome = nomeCliente.value.trim(), versao = versaoPesquisaCliente;
    if (nome.length < 2) return;
    const aviso = document.getElementById('avisoPesquisaClientes');
    aviso.textContent = 'A procurar clientes...';
    if(!navigator.onLine){
        try{
            const clientes=await window.BlessedClientesOffline?.pesquisarNomeOffline(nome)||[];
            if(versao!==versaoPesquisaCliente||modal.hidden)return;
            const resultados=document.getElementById('resultadosClientes');
            resultados.replaceChildren();
            for(const cliente of clientes){
                const botao=document.createElement('button');
                botao.type='button';
                botao.textContent=`${cliente.nome} · ${cliente.telefone||'Sem telefone'}`;
                botao.addEventListener('click',async()=>{
                    const local=await window.BlessedClientesOffline.obterClienteOffline(cliente.id);
                    if(local)preencherClienteMarcacao(local);
                });
                resultados.appendChild(botao);
            }
            resultados.hidden=!clientes.length;
            nomeCliente.setAttribute('aria-expanded',String(!!clientes.length));
            aviso.textContent=clientes.length
                ? 'Clientes guardados no dispositivo.'
                : 'Sem resultados offline. Confirma com Internet antes de criar um cliente.';
        }catch(e){
            aviso.textContent='Lista offline indisponível.';
        }
        return;
    }
    try {
        const resposta = await fetch('/api/clientes/por-nome?' + new URLSearchParams({nome}));
        const resultado = await resposta.json();
        if (versao !== versaoPesquisaCliente || modal.hidden) return;
        if (!resposta.ok || !resultado.ok) throw new Error();
        const resultados = document.getElementById('resultadosClientes');
        resultados.replaceChildren();
        for (const cliente of resultado.clientes) {
            const botao = document.createElement('button');
            botao.type = 'button';
            botao.textContent = `${cliente.nome} · ${cliente.telefone || 'Sem telefone'} `;
            botao.addEventListener('click', () => escolherClienteMarcacao(cliente.id));
            resultados.appendChild(botao);
        }
        resultados.hidden = resultado.clientes.length === 0;
        nomeCliente.setAttribute('aria-expanded', String(!resultados.hidden));
        aviso.textContent = resultado.clientes.length === 0
            ? 'Nenhum cliente encontrado. Podes preencher os dados para criar um novo.'
            : resultado.mais_resultados ? 'Há mais resultados. Escreve mais do nome para restringir a pesquisa.' : 'Escolhe o cliente pelo nome e telefone.';
    } catch (erro) {
        if (versao !== versaoPesquisaCliente || modal.hidden) return;
        limparResultadosClientes();
        const clientes = await window.BlessedClientesOffline?.pesquisarNomeOffline(nome) || [];
        if (versao !== versaoPesquisaCliente || modal.hidden) return;
        const resultados = document.getElementById('resultadosClientes');
        resultados.replaceChildren();
        for (const cliente of clientes) {
            const botao = document.createElement('button');
            botao.type = 'button';
            botao.textContent = `${cliente.nome} · ${cliente.telefone || 'Sem telefone'}`;
            botao.addEventListener('click', () => escolherClienteMarcacao(cliente.id));
            resultados.appendChild(botao);
        }
        resultados.hidden = clientes.length === 0;
        nomeCliente.setAttribute('aria-expanded', String(!resultados.hidden));
        aviso.textContent = clientes.length
            ? 'Resultados guardados no equipamento (offline).'
            : 'Sem resultados na lista offline. Confirma com Internet antes de criar uma ficha.';
    }
}

nomeCliente.addEventListener('input', () => {
    invalidarPesquisaCliente();
    estadoCliente.textContent = '';
    if (nomeCliente.value.trim().length >= 2) {
        temporizadorNomeCliente = setTimeout(procurarClientesPorNome, 350);
    }
});
nomeCliente.addEventListener('keydown', evento => {
    if (evento.key === 'ArrowDown') {
        const primeiro = document.querySelector('#resultadosClientes button');
        if (primeiro) { evento.preventDefault(); primeiro.focus(); }
    }
    if (evento.key === 'Escape') limparResultadosClientes();
});
