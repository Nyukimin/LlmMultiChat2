import sys, asyncio, json
sys.path.append('LLM')
from ingest_mode import run_ingest_mode

async def main():
    r = await run_ingest_mode(
        '吉沢亮 国宝 映画',
        '映画',
        1,
        'KB/media.db',
        expand=True,
        strict=True,
        log_callback=lambda m: print('[log]', m)
    )
    summary = {k: len(v) for k, v in r.items() if isinstance(v, list) and k in ('persons','works','credits','external_ids','unified')}
    print('RESULT', json.dumps(summary, ensure_ascii=False))

if __name__ == '__main__':
    asyncio.run(main())
