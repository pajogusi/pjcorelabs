(function () {
    'use strict';
    const uid = Number(document.body.dataset.utilizadorId || 0);
    const DB = 'blessed-agenda-offline-user-' + uid;
    const STORE = 'snapshot';
    let aAtualizar = false;
    function abrir() {
        return new Promise((resolve, reject) => {
            const req = indexedDB.open(DB, 1);
            req.onupgradeneeded = () => req.result.createObjectStore(STORE);
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
    }
    async function gravar(dados) {
        const db = await abrir();
        try {
            await new Promise((resolve, reject) => {
                const tx = db.transaction(STORE, 'readwrite');
                tx.objectStore(STORE).put(dados, 'atual');
                tx.oncomplete = resolve;
                tx.onerror = () => reject(tx.error);
                tx.onabort = () => reject(tx.error);
            });
        } finally { db.close(); }
    }
    async function ler() {
        const db = await abrir();
        try {
            return await new Promise((resolve, reject) => {
                const req = db.transaction(STORE, 'readonly').objectStore(STORE).get('atual');
                req.onsuccess = () => resolve(req.result || null);
                req.onerror = () => reject(req.error);
            });
        } finally { db.close(); }
    }
    async function atualizar() {
        if (!uid || !navigator.onLine || aAtualizar) return false;
        aAtualizar = true;
        try {
            const resposta = await fetch('/api/agenda/offline', {credentials:'same-origin',cache:'no-store',
                headers:{Accept:'application/json'}, signal:typeof AbortSignal.timeout === 'function' ? AbortSignal.timeout(8000) : undefined});
            if (!resposta.ok || !resposta.headers.get('content-type')?.includes('application/json')) return false;
            const dados = await resposta.json();
            if (!dados.ok || !Array.isArray(dados.intervalos)) return false;
            await gravar(dados);
            return true;
        } catch (_) { return false; }
        finally { aAtualizar = false; }
    }
    function sobrepoe(a,b,c,d) { return a < d && b > c; }
    function formatarFim(inicio, minutos) {
        const d = new Date(new Date(inicio).getTime() + minutos * 60000);
        return [d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-') +
            'T' + String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
    }
    async function verificar(inicio, duracao, barbeiroId, ignorarId) {
        const dados = await ler();
        if (!dados || !dados.desde || !dados.ate) return {seguro:false, motivo:'Sem cópia local da agenda. Liga à Internet para atualizar.'};
        const dia = inicio.slice(0,10);
        if (dia < dados.desde || dia > dados.ate) return {seguro:false, motivo:'Data fora do período guardado offline.'};
        const fim = new Date(new Date(inicio).getTime() + Number(duracao) * 60000);
        if (!Number.isFinite(fim.getTime()) || !barbeiroId) return {seguro:false, motivo:'Data, duração ou barbeiro inválidos.'};
        const fimLocal = [fim.getFullYear(),String(fim.getMonth()+1).padStart(2,'0'),String(fim.getDate()).padStart(2,'0')].join('-') +
            'T' + String(fim.getHours()).padStart(2,'0') + ':' + String(fim.getMinutes()).padStart(2,'0');
        if (fimLocal.slice(0,10) > dados.ate) return {seguro:false, motivo:'Horário fora do período guardado.'};
        if (dados.intervalos.some(p => (p.barbeiro_id === null || Number(p.barbeiro_id) === Number(barbeiroId)) &&
                sobrepoe(inicio, fimLocal, p.inicio, p.fim))) {
            return {seguro:false, motivo:'Horário ocupado na última agenda guardada.'};
        }
        const pendentes = await window.BlessedOfflineBookings?.listarPendentes?.() || [];
        if (pendentes.some(p => p.offline_id !== ignorarId && Number(p.barbeiro_id) === Number(barbeiroId) &&
            sobrepoe(inicio, fimLocal, p.inicio,
                formatarFim(p.inicio, Number(p.duracao))))) {
            return {seguro:false, motivo:'Conflito com outra marcação pendente neste equipamento.'};
        }
        return {seguro:true, motivo:'Livre na última cópia da agenda · sujeito a confirmação ao sincronizar.'};
    }
    window.BlessedAgendaOffline = {atualizar, verificar};
    window.addEventListener('online', atualizar);
    window.addEventListener('pageshow', atualizar);
    document.addEventListener('visibilitychange', () => {if (!document.hidden) atualizar();});
    if (navigator.onLine) atualizar();
})();
