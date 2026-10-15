(function () {
    'use strict';

    const DB_NAME = 'blessed-clientes-offline-v2-user-' + Number(document.body.dataset.utilizadorId || 0);
    const DB_VERSION = 1;
    const STORE = 'clientes';
    const utilizadorId = Number(document.body.dataset.utilizadorId || 0);

    function abrirDb() {
        return new Promise((resolve, reject) => {
            const req = indexedDB.open(DB_NAME, DB_VERSION);
            req.onupgradeneeded = () => {
                const db = req.result;
                if (!db.objectStoreNames.contains(STORE)) {
                    db.createObjectStore(STORE, {keyPath: 'id'});
                }
            };
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
    }

    async function guardarClientes(clientes) {
        if (!utilizadorId) throw new Error('Utilizador não identificado.');
        const db = await abrirDb();
        try {
            await new Promise((resolve, reject) => {
                const tx = db.transaction(STORE, 'readwrite');
                const store = tx.objectStore(STORE);
                store.clear();
                for (const cliente of clientes) {
                    store.put({
                        id: cliente.id,
                        nome: cliente.nome,
                        telefone: cliente.telefone || ''
                    });
                }
                tx.oncomplete = resolve;
                tx.onerror = () => reject(tx.error);
                tx.onabort = () => reject(tx.error);
            });
        } finally {
            db.close();
        }
    }

    async function listarClientes() {
        if (!utilizadorId) return [];
        const db = await abrirDb();
        try {
            return await new Promise((resolve, reject) => {
                const req = db.transaction(STORE, 'readonly')
                    .objectStore(STORE).getAll();
                req.onsuccess = () => resolve(req.result || []);
                req.onerror = () => reject(req.error);
            });
        } finally {
            db.close();
        }
    }


    async function sincronizarClientes() {
        if (!utilizadorId || !navigator.onLine) return false;

        try {
            const resposta = await fetch('/api/clientes/offline', {
                credentials: 'same-origin',
                cache: 'no-store',
                headers: {'Accept': 'application/json'}
            });

            if (!resposta.ok ||
                !resposta.headers.get('content-type')?.includes('application/json')) {
                return false;
            }

            const dados = await resposta.json();

            if (!dados.ok || !Array.isArray(dados.clientes)) {
                return false;
            }

            await guardarClientes(dados.clientes);
            return true;
        } catch (erro) {
            return false;
        }
    }


    function normalizar(texto) {
        return String(texto || '').normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '').toLowerCase();
    }

    async function pesquisarNomeOffline(nome) {
        const termo = normalizar(nome).trim();
        if (termo.length < 2) return [];
        const clientes = await listarClientes();
        return clientes.filter(c => normalizar(c.nome).includes(termo))
            .slice(0, 30);
    }

    async function pesquisarTelefoneOffline(telefone) {
        const numero = String(telefone || '').replace(/\D/g, '');
        if (numero.length < 6) return null;
        const clientes = await listarClientes();
        return clientes.find(c =>
            String(c.telefone || '').replace(/\D/g, '') === numero
        ) || null;
    }

    async function obterClienteOffline(id) {
        const clientes = await listarClientes();
        const cliente = clientes.find(c => Number(c.id) === Number(id));
        return cliente ? {...cliente, offline: true} : null;
    }

    // Atualizar a lista apenas quando existe uma sessão online válida.
    // Nunca apagar marcações offline pendentes.
    window.addEventListener('online', sincronizarClientes);

    if (utilizadorId && navigator.onLine) {
        sincronizarClientes();
    }


    async function limparClientesOffline() {
        const db = await abrirDb();
        try {
            await new Promise((resolve, reject) => {
                const tx = db.transaction(STORE, 'readwrite');
                tx.objectStore(STORE).clear();
                tx.oncomplete = resolve;
                tx.onerror = () => reject(tx.error);
                tx.onabort = () => reject(tx.error);
            });
        } finally {
            db.close();
        }
    }

    document.querySelector('a[href="/logout"]')?.addEventListener(
        'click', async function (evento) {
            evento.preventDefault();
            try {
                await limparClientesOffline();
                window.location.assign(this.href);
            } catch (erro) {
                alert('Não foi possível limpar os clientes locais. Tenta novamente.');
            }
        }
    );

    window.BlessedClientesOffline = {
        guardarClientes,
        listarClientes,
        sincronizarClientes,
        pesquisarNomeOffline,
        pesquisarTelefoneOffline,
        obterClienteOffline,
        limparClientesOffline
    };
})();
