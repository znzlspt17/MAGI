// 테스트용 WASM PostgreSQL 연결. 실제 사용자 DB 설정을 사용하지 않는다.
import {createRequire} from 'node:module';
import {createInterface} from 'node:readline';
import {join} from 'node:path';
const require = createRequire(join(process.argv[2], 'package.json'));
const {PGlite} = require('@electric-sql/pglite');
const {vector} = require('@electric-sql/pglite-pgvector');
const db = await PGlite.create({extensions: {vector}});
await db.exec('CREATE EXTENSION vector');
process.stdout.write('{"ready":true}\n');
for await (const line of createInterface({input: process.stdin, crlfDelay: Infinity})) {
    try {
        const {sql, params} = JSON.parse(line);
        let result;
        if (!params.length && sql.trim().split(';').filter(Boolean).length > 1) {
            await db.exec(sql); result = {rows: []};
        } else result = await db.query(sql, params);
        process.stdout.write(JSON.stringify({rows: result.rows}) + '\n');
    } catch (error) {
        process.stdout.write(JSON.stringify({error: error.message}) + '\n');
    }
}
await db.close();
