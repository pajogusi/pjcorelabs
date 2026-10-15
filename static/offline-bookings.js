(function () {
    'use strict';

    const DB_NAME = 'blessed-offline';
    const DB_VERSION = 1;
    const STORE = 'marcacoes';
    const form = document.getElementById('formNovaMarcacao');
    const estado = document.getElementById('estadoOfflineBlessed');
    if (!form) return;

    const body = document.body;
    const utilizadorId = Number(body.dataset.utilizadorId || 0);
    const papel = body.dataset.utilizadorPapel || '';
    const eAdmin = body.dataset.utilizadorAdmin === '1';
    const barbeiroAgenda = Number(body.dataset.barbeiroAgenda || 0);
    const botaoMarcar = form.querySelector('[type="submit"]');
    const estadoDisponibilidade = document.getElementById('estadoDisponibilidade');
    let aSincronizar = false;

    function mostrarEstado(texto, erro) {
        if (!estado) return;
        estado.hidden = !texto;
        estado.textContent = texto || '';
        estado.style.cssText = texto
            ? 'position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:9999;padding:10px 16px;border-radius:10px;background:' +
              (erro ? '#8b1e1e' : '#243b20') + ';color:white;font-weight:700;box-shadow:0 4px 18px rgba(0,0,0,.25)'
            : '';
    }

    // Nunca desbloquear marcações sem verificar a cópia local da agenda.
    async function validarAgendaLocal(item) {
        if (item.repetir_semanalmente === '1') throw new Error('Marcações semanais precisam de verificação online.');
        const resultado = await window.BlessedAgendaOffline?.verificar(
            item.inicio, Number(item.duracao), item.barbeiro_id, item.offline_id);
        if (!resultado?.seguro) throw new Error(resultado?.motivo || 'Agenda offline não disponível.');
    }

    function abrirDb() {
        return new Promise(function (resolve, reject) {
            const req = indexedDB.open(DB_NAME, DB_VERSION);
            req.onupgradeneeded = function () {
                const db = req.result;
                if (!db.objectStoreNames.contains(STORE)) {
                    db.createObjectStore(STORE, {keyPath: 'offline_id'});
                }
            };
            req.onsuccess = function () { resolve(req.result); };
            req.onerror = function () { reject(req.error); };
        });
    }

    async function guardarLocal(item) {
        const db = await abrirDb();
        await new Promise(function (resolve, reject) {
            const tx = db.transaction(STORE, 'readwrite');
            tx.objectStore(STORE).put(item);
            tx.oncomplete = resolve;
            tx.onerror = function () { reject(tx.error); };
        });
        db.close();
    }

    async function listarLocais() {
        const db = await abrirDb();
        const itens = await new Promise(function (resolve, reject) {
            const req = db.transaction(STORE, 'readonly').objectStore(STORE).getAll();
            req.onsuccess = function () { resolve(req.result || []); };
            req.onerror = function () { reject(req.error); };
        });
        db.close();
        return itens;
    }

    async function listarLocaisDoUtilizador() {
        const itens = await listarLocais();
        return itens.filter(function (item) {
            return Number(item.utilizador_id || 0) === utilizadorId;
        });
    }

    async function apagarLocal(id) {
        const db = await abrirDb();
        await new Promise(function (resolve, reject) {
            const tx = db.transaction(STORE, 'readwrite');
            tx.objectStore(STORE).delete(id);
            tx.oncomplete = resolve;
            tx.onerror = function () { reject(tx.error); };
        });
        db.close();
    }

    window.BlessedOfflineBookings = {listarPendentes: listarLocaisDoUtilizador};

    function idOffline() {
        if (crypto.randomUUID) return crypto.randomUUID();
        return 'offline-' + Date.now() + '-' + Math.random().toString(16).slice(2);
    }

    function dadosDoFormulario() {
        const fd = new FormData(form);
        const alvo = Number(fd.get('barbeiro_id') || barbeiroAgenda || 0);
        if (!alvo) throw new Error('Abre primeiro uma agenda individual.');
        if (!(papel === 'gestor' || eAdmin || alvo === utilizadorId)) {
            throw new Error('Só podes criar marcações na tua própria agenda.');
        }
        return {
            offline_id: idOffline(),
            utilizador_id: utilizadorId,
            barbeiro_id: alvo,
            nome: String(fd.get('nome') || '').trim(),
            telefone: String(fd.get('telefone') || '').trim(),
            email: String(fd.get('email') || '').trim(),
            cliente_id: String(fd.get('cliente_id') || '').trim(),
            data_nascimento: String(fd.get('data_nascimento') || '').trim(),
            observacoes: String(fd.get('observacoes') || '').trim(),
            inicio: String(fd.get('inicio') || '').trim(),
            duracao: String(fd.get('duracao') || '30'),
            repetir_semanalmente: String(fd.get('repetir_semanalmente') || '0'),
            repeticoes: String(fd.get('repeticoes') || '1'),
            guardada_em: new Date().toISOString()
        };
    }

    function validarMinimo(d) {
        if (!d.nome || !d.telefone || !d.inicio) {
            throw new Error('Preenche nome, telefone, data e hora.');
        }
    }

    async function enviar(item) {
        const r = await fetch('/marcacoes/offline/sincronizar', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
            body: JSON.stringify(item),
            credentials: 'same-origin'
        });

        if (r.redirected && new URL(r.url).pathname === '/login') {
            const e = new Error('Sessão expirada. Volta a entrar; a marcação continua guardada.');
            e.status = 401;
            throw e;
        }

        let dados = {};
        try { dados = await r.json(); } catch (_) {}
        if (!r.ok || !dados.ok) {
            const e = new Error(dados.erro || ('Erro ' + r.status));
            e.status = r.status;
            throw e;
        }
        return dados;
    }

    async function sincronizar() {
        if (aSincronizar || !navigator.onLine) return;
        aSincronizar = true;

        try {
            const itens = await listarLocaisDoUtilizador();
            if (!itens.length) return;

            mostrarEstado('A sincronizar ' + itens.length + ' marcação' + (itens.length === 1 ? '' : 'ões') + '…', false);
            let conflitos = 0;

            for (const item of itens) {
                try {
                    await enviar(item);
                    await apagarLocal(item.offline_id);
                } catch (e) {
                    if (!e.status) break;
                    conflitos++;
                    item.erro_sync = e.message;
                    await guardarLocal(item);
                }
            }

            const restantes = await listarLocaisDoUtilizador();
            if (!restantes.length) {
                mostrarEstado('Marcações offline sincronizadas.', false);
                setTimeout(function () { window.location.reload(); }, 900);
            } else if (conflitos) {
                mostrarEstado(restantes.length + ' marcação(ões) pendente(s): conflito ou validação necessária.', true);
            } else {
                mostrarEstado(restantes.length + ' marcação(ões) ainda pendente(s).', true);
            }
        } finally {
            aSincronizar = false;
        }
    }

    form.addEventListener('submit', async function (ev) {
        ev.preventDefault();
        let item;

        try {
            item = dadosDoFormulario();
            validarMinimo(item);
        } catch (e) {
            mostrarEstado(e.message, true);
            return;
        }

        if (botaoMarcar) botaoMarcar.disabled = true;

        try {
            if (!navigator.onLine) {
                await validarAgendaLocal(item);
                await guardarLocal(item);
                mostrarEstado('Marcação guardada offline. Será validada ao sincronizar.', false);
                document.getElementById('modalMarcacao').hidden = true;
                form.reset();
                return;
            }
            await enviar(item);
            window.location.reload();
        } catch (e) {
            // Sem resposta do servidor: guardar localmente. Erros HTTP reais ficam visíveis.
            if (!e.status) {
                try { await validarAgendaLocal(item); }
                catch (conflito) { mostrarEstado(conflito.message, true); return; }
                await guardarLocal(item);
                mostrarEstado('Sem ligação ao servidor — marcação guardada neste dispositivo para sincronizar.', false);
                document.getElementById('modalMarcacao').hidden = true;
                form.reset();

            } else {
                mostrarEstado(e.message, true);
            }
        } finally {
            if (botaoMarcar) botaoMarcar.disabled = false;
        }
    });

    window.addEventListener('online', function () {
        sincronizar().catch(function () {});
    });

    window.addEventListener('offline', function () {
        mostrarEstado('Sem ligação — horários sujeitos à agenda guardada.', false);
    });

    // Cobre também o caso de haver Internet mas o VPS/servidor ter estado indisponível.
    // Quando regressa, a fila é tentada novamente sem depender de um evento "online".
    setInterval(function () {
        if (navigator.onLine) sincronizar().catch(function () {});
    }, 15000);

    if (!navigator.onLine) {
        mostrarEstado('Sem ligação — horários sujeitos à agenda guardada.', false);
    } else {
        sincronizar().catch(function () {});
    }
})();