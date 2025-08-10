document.addEventListener('DOMContentLoaded', () => {
  const logEl = document.getElementById('log');
  const summaryEl = document.getElementById('summary');
  const topicEl = document.getElementById('topic');
  const domainEl = document.getElementById('domain');
  const roundsEl = document.getElementById('rounds');
  const strictEl = document.getElementById('strict');
  const runBtn = document.getElementById('run');
  const clearBtn = document.getElementById('clear');

  const log = (msg) => {
    const ts = new Date().toLocaleTimeString('ja-JP');
    logEl.textContent += `[${ts}] ${msg}\n`;
    logEl.scrollTop = logEl.scrollHeight;
  };

  const runIngest = async () => {
    const topic = (topicEl.value || '').trim();
    const domain = domainEl.value;
    const rounds = parseInt(roundsEl.value || '1', 10) || 1;
    const strict = !!strictEl.checked;
    if (!topic) { log('トピックが未入力です'); return; }

    log(`呼び出し開始 topic='${topic}', domain='${domain}', rounds=${rounds}, strict=${strict}`);

    try {
      const res = await fetch('/api/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, domain, rounds, strict })
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
});