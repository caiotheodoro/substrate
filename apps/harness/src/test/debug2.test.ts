import { it } from 'vitest';
import { recordCorpusRun, GOLDEN_SPECS } from '../golden-corpus/generator';
import { goldenCorpusDir } from '../replay/golden';
import { spawnSync } from 'node:child_process';

it('dump recorded golden events', async () => {
  const dir = '/tmp/golden-debug-corpus';
  for (const spec of GOLDEN_SPECS) {
    await recordCorpusRun(spec, dir);
    const out = spawnSync('sh', ['-c', `python3 -c "import json,sys\nfor l in open('${dir}/${spec.id}.golden.jsonl'):\n l=l.strip()\n if not l or l.startswith('#'): continue\n e=json.loads(l)\n print(e['family'].ljust(10), e.get('kind','').ljust(22), e['idempotencyKey'], e['seq'])"`], { encoding: 'utf8' });
    console.log('---', spec.id, '---');
    console.log(out.stdout);
  }
});