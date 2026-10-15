
(() => {
  const $ = id => document.getElementById(id);
  const mostrar = (id, valor) => { if ($(id)) $(id).textContent = valor; };

  function ligacao() {
    mostrar('diag-ligacao', navigator.onLine ? 'Online' : 'Offline');
  }

  function contarDb(nome, store) {
    return new Promise(resolve => {
      try {
        const req = indexedDB.open(nome);
        req.onerror = () => resolve(null);
        req.onupgradeneeded = () => {
          req.transaction.abort();
          resolve(null);
        };
        req.onsuccess = () => {
          const db = req.result;
          if (!db.objectStoreNames.contains(store)) {
            db.close();
            resolve(null);
            return;
          }
          const tx = db.transaction(store, 'readonly');
          const count = tx.objectStore(store).count();
          count.onsuccess = () => resolve(count.result);
          count.onerror = () => resolve(null);
          tx.oncomplete = () => db.close();
        };
      } catch (_) { resolve(null); }
    });
  }

  async function atualizar() {
    ligacao();
    const uid = Number(document.body.dataset.utilizadorId || 0);
    if (uid) {
      const clientes = await contarDb(
        'blessed-clientes-offline-v2-user-' + uid, 'clientes'
      );
      mostrar('diag-clientes', clientes ?? '—');
    }
    const pendentes = await contarDb('blessed-offline', 'marcacoes');
    mostrar('diag-pendentes', pendentes ?? '—');
  }

  window.addEventListener('online', atualizar);
  window.addEventListener('offline', atualizar);
  atualizar();
  setInterval(atualizar, 15000);
})();
