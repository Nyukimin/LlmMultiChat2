document.addEventListener('DOMContentLoaded', () => {
  const qEl = document.getElementById('q');
  const kindEls = Array.from(document.querySelectorAll('input[name="kind"]'));
  const listEl = document.getElementById('list');
  const detailEl = document.getElementById('detail');
  const searchBtn = document.getElementById('search');
  const clearBtn = document.getElementById('clear');
  const cleanupBtn = document.getElementById('cleanup');
  const cleanupDryRunEl = document.getElementById('cleanup-dryrun');
  const cleanupVacuumEl = document.getElementById('cleanup-vacuum');
  const cleanupStatusEl = document.getElementById('cleanup-status');

  const logList = (msg) => { listEl.textContent += msg + "\n"; listEl.scrollTop = listEl.scrollHeight; };
  const logDetail = (msg) => { detailEl.textContent += msg + "\n"; detailEl.scrollTop = detailEl.scrollHeight; };
  const clearAll = () => { listEl.textContent=''; detailEl.textContent=''; };

  const fetchJSON = async (url) => {
    const res = await fetch(url);
    return await res.json();
  };

  const postJSON = async (url, body) => {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
    return await res.json();
  };

  const renderWorks = async (items=[]) => {
    listEl.textContent = '';
    if (!items.length) { logList('(no work)'); return; }
    items.forEach(w => {
      const a = document.createElement('a');
      a.href = '#';
      a.textContent = `${w.title} (${w.year || '-'})`;
      a.addEventListener('click', async () => {
        detailEl.textContent = '';
        const d = await fetchJSON(`/api/db/works/${w.id}`);
        logDetail(JSON.stringify(d.item, null, 2));
        const cast = await fetchJSON(`/api/db/works/${w.id}/cast`);
        logDetail('--- cast/staff ---');
        (cast.items || []).forEach(r => logDetail(`- ${r.name} [${r.role}]` + (r.character ? ` as ${r.character}` : '')));
      });
      listEl.appendChild(a);
      listEl.appendChild(document.createElement('br'));
    });
  };

  const renderPersons = async (items=[]) => {
    listEl.textContent = '';
    if (!items.length) { logList('(no person)'); return; }
    items.forEach(p => {
      const a = document.createElement('a');
      a.href = '#';
      a.textContent = `${p.name}`;
      a.addEventListener('click', async () => {
        detailEl.textContent = '';
        const d = await fetchJSON(`/api/db/persons/${p.id}`);
        logDetail(JSON.stringify(d.item, null, 2));
        const cr = await fetchJSON(`/api/db/persons/${p.id}/credits`);
        logDetail('--- credits ---');
        (cr.items || []).forEach(r => logDetail(`- ${r.title}${r.year ? ' ('+r.year+')':''} [${r.role}]` + (r.character ? ` as ${r.character}` : '')));
      });
      listEl.appendChild(a);
      listEl.appendChild(document.createElement('br'));
    });
  };

  const renderFTS = (items=[]) => {
    listEl.textContent = '';
    if (!items.length) { logList('(no match)'); return; }
    items.forEach(it => {
      const a = document.createElement('a');
      a.href = '#';
      a.textContent = `${it.kind}#${it.ref_id} :: ${it.snippet}`;
      listEl.appendChild(a);
      listEl.appendChild(document.createElement('br'));
    });
  };

  const doSearch = async () => {
    const q = (qEl.value || '').trim();
    const kind = (kindEls.find(r => r.checked)?.value) || 'work';
    clearAll();
    if (!q) { logList('キーワード未入力'); return; }
    try {
      if (kind === 'work') {
        const d = await fetchJSON(`/api/db/works?keyword=${encodeURIComponent(q)}`);
        await renderWorks(d.items || []);
      } else if (kind === 'person') {
        const d = await fetchJSON(`/api/db/persons?keyword=${encodeURIComponent(q)}`);
        await renderPersons(d.items || []);
      } else {
        const d = await fetchJSON(`/api/db/fts?q=${encodeURIComponent(q)}`);
        renderFTS(d.items || []);
      }
    } catch (e) {
      logList(`エラー: ${e}`);
    }
  };

  searchBtn.addEventListener('click', doSearch);
  clearBtn.addEventListener('click', clearAll);

  const runCleanup = async () => {
    const dry = !!cleanupDryRunEl?.checked;
    const vac = !!cleanupVacuumEl?.checked;
    const first = dry ? 'Dry-runで重複クリーンアップを実行します。よろしいですか？' : 'バックアップを作成し、重複クリーンアップを実行します。よろしいですか？';
    if (!confirm(first)) return;
    // 進行表示とロック
    let t0 = Date.now();
    const tick = () => { const sec = Math.floor((Date.now()-t0)/1000); cleanupStatusEl.textContent = `実行中... ${sec}s`; };
    const timer = setInterval(tick, 500);
    cleanupBtn.disabled = true;
    cleanupStatusEl.textContent = '実行中...';
    detailEl.textContent = '';
    listEl.textContent = '';
    try {
      const res = await postJSON('/api/kb/cleanup', { dry_run: dry, vacuum: vac });
      if (!res.ok) {
        logList(`cleanup error: ${res.error || 'unknown error'}`);
        cleanupStatusEl.textContent = 'エラー';
        return;
      }
      if (res.backup_path) logDetail(`backup: ${res.backup_path}`);
      if (res.stats) logDetail(JSON.stringify(res.stats, null, 2));
      (res.logs || []).forEach(line => logList(line));
      cleanupStatusEl.textContent = '完了';
      if (dry) {
        if (confirm('Dry-runが完了しました。本実行しますか？（バックアップが作成されます）')) {
          // 再度進行表示
          t0 = Date.now(); cleanupStatusEl.textContent = '実行中...';
          const res2 = await postJSON('/api/kb/cleanup', { dry_run: false, vacuum: vac });
          if (!res2.ok) {
            logList(`cleanup error(exec): ${res2.error || 'unknown error'}`);
            cleanupStatusEl.textContent = 'エラー';
          } else {
            if (res2.backup_path) logDetail(`backup: ${res2.backup_path}`);
            if (res2.stats) logDetail(JSON.stringify(res2.stats, null, 2));
            (res2.logs || []).forEach(line => logList(line));
            cleanupStatusEl.textContent = '完了';
          }
        }
      }
    } catch (e) {
      logList(`cleanup exception: ${e}`);
      cleanupStatusEl.textContent = 'エラー';
    } finally {
      clearInterval(timer);
      cleanupBtn.disabled = false;
    }
  };

  cleanupBtn.addEventListener('click', runCleanup);
});