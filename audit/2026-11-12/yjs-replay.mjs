// Run: node audit/2026-11-12/yjs-replay.mjs
// Uses the installed frontend Yjs and real SQLite storage in a temporary dir.
import * as Y from '../../frontend/node_modules/yjs/dist/yjs.mjs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../../', import.meta.url));
const source = new Y.Doc();
const updates = [];
source.on('update', u => updates.push(Buffer.from(u).toString('base64')));
for (let i = 0; i < 1005; i++) source.getText('content').insert(i, 'x');

const result = spawnSync(`${root}/.venv/bin/python`, ['-c', `
import asyncio,base64,json,sys,tempfile
from livepaste.storage import SQLiteStorage
async def main():
    with tempfile.TemporaryDirectory(prefix='lp-yjs-replay-') as directory:
        store=SQLiteStorage(directory)
        await store.startup()
        try:
            for item in json.load(sys.stdin):
                update=base64.b64decode(item)
                await store.append_yupdate('audit',update)
                await store.append_sheet_yupdate('audit','0123456789ab',update)
            print(json.dumps({
                'main':[base64.b64encode(x).decode() for x in await store.get_yupdates('audit')],
                'sheet':[base64.b64encode(x).decode() for x in await store.get_sheet_yupdates('audit','0123456789ab')]
            }))
        finally:
            await store.shutdown()
asyncio.run(main())
`], { cwd: root, input: JSON.stringify(updates), encoding: 'utf8' });
if (result.status !== 0) throw new Error(result.stderr);
const stored = JSON.parse(result.stdout);
const replay = list => {
  const doc = new Y.Doc();
  for (const update of list) Y.applyUpdate(doc, Buffer.from(update, 'base64'));
  const text = doc.getText('content').toString();
  doc.destroy();
  return text;
};
const output = {
  expectedLength: source.getText('content').length,
  fullHistoryReplayLength: replay(updates).length,
  main: { storedUpdates: stored.main.length, replayLength: replay(stored.main).length },
  sheet: { storedUpdates: stored.sheet.length, replayLength: replay(stored.sheet).length },
  afterFullTextHistoryDeletion: { retainedUpdates: updates.length - 1, replayLength: replay(updates.slice(1)).length },
};
console.log(JSON.stringify(output, null, 2));
source.destroy();
// This is an observation script, not a passing regression specification.
// Both replay lengths must equal expectedLength once compaction is repaired.
