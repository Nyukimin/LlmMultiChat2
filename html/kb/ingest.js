document.addEventListener('DOMContentLoaded', () => {
  const logEl = document.getElementById('log');
  const summaryEl = document.getElementById('summary');
  const topicEl = document.getElementById('topic');
  const topicTypeEls = Array.from(document.querySelectorAll('input[name="topicType"]'));
  const domainEl = document.getElementById('domain');
  const roundsEl = document.getElementById('rounds');
  const strictEl = document.getElementById('strict');
  const runBtn = document.getElementById('run');
  const clearBtn = document.getElementById('clear');
  const suggestQEl = document.getElementById('suggest-q');
  const suggestBtn = document.getElementById('suggest-btn');
  const suggestListEl = document.getElementById('suggest-list');

  const log = (msg) => {
    const ts = new Date().toLocaleTimeString('ja-JP');
    logEl.textContent += `[${ts}] ${msg}\n`;
    logEl.scrollTop = logEl.scrollHeight;
  };

  const runIngest = async () => {
    const topic = (topicEl.value || '').trim();
    const topicType = (topicTypeEls.find(r => r.checked)?.value) || 'unknown';
    const domain = domainEl.value;
    const rounds = parseInt(roundsEl.value || '1', 10) || 1;
    const strict = !!strictEl.checked;
    if (!topic) { log('トピックが未入力です'); return; }

    log(`呼び出し開始 topic='${topic}', type=${topicType}, domain='${domain}', rounds=${rounds}, strict=${strict}`);

    try {
      const res = await fetch('/api/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, domain, rounds, strict, topicType })
      });
      const data = await res.json();
      if (!data || !data.ok) {
        log('エラー: サーバ応答が不正です');
        summaryEl.textContent = JSON.stringify(data, null, 2);
        return;
      }
      (data.logs || []).forEach(line => log(`[ingest] ${line}`));
      log('完了: DB登録済み');
      summaryEl.textContent = JSON.stringify({
        persons: (data.result.persons || []).length,
        works: (data.result.works || []).length,
        credits: (data.result.credits || []).length,
        external_ids: (data.result.external_ids || []).length,
        unified: (data.result.unified || []).length,
      }, null, 2);
    } catch (e) {
      log(`ネットワークエラー: ${e}`);
    }
  };

  runBtn.addEventListener('click', runIngest);
  clearBtn.addEventListener('click', () => { logEl.textContent=''; summaryEl.textContent=''; });

  const renderSuggest = (items=[]) => {
    suggestListEl.innerHTML = '';
    items.forEach(it => {
      const li = document.createElement('li');
      const a = document.createElement('a');
      a.href = it.url || '#';
      a.target = '_blank';
      a.textContent = it.title || it.url;
      li.appendChild(a);
      const pick = document.createElement('button');
      pick.textContent = '→ トピックに反映';
      pick.addEventListener('click', () => {
        // タイトルの主要部をトピックに反映
        const t = (it.title || '').replace(/\s*[:：-].*$/, '').trim();
        topicEl.value = t || (it.url || '');
      });
      li.appendChild(pick);
      suggestListEl.appendChild(li);
    });
  };

  const runSuggest = async () => {
    const type = (topicTypeEls.find(r => r.checked)?.value) || 'unknown';
    const q = (suggestQEl.value || topicEl.value || '').trim();
    if (!q) { log('サジェストのクエリが未入力です'); return; }
    try {
      const res = await fetch(`/api/suggest?type=${encodeURIComponent(type)}&q=${encodeURIComponent(q)}`);
      const data = await res.json();
      if (!data || !data.ok) {
        log('サジェスト取得エラー');
        renderSuggest([]);
        return;
      }
      renderSuggest(data.items || []);
    } catch (e) {
      log(`サジェストのネットワークエラー: ${e}`);
    }
  };

  suggestBtn.addEventListener('click', runSuggest);
});