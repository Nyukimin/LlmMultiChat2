document.addEventListener('DOMContentLoaded', () => {
  const qEl = document.getElementById('q');
  const kindEls = Array.from(document.querySelectorAll('input[name="kind"]'));
  const listEl = document.getElementById('list');
  const detailEl = document.getElementById('detail');
  const searchBtn = document.getElementById('search');
  const clearBtn = document.getElementById('clear');

  const logList = (msg) => { listEl.textContent += msg + "\n"; listEl.scrollTop = listEl.scrollHeight; };
  const logDetail = (msg) => { detailEl.textContent += msg + "\n"; detailEl.scrollTop = detailEl.scrollHeight; };
  const clearAll = () => { listEl.textContent=''; detailEl.textContent=''; };

  const fetchJSON = async (url) => {
    const res = await fetch(url);
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
});