// 테스트마다 완전히 독립된 메모리 PostgreSQL wire 서버를 연다.
import {createRequire} from 'node:module';
import {join} from 'node:path';

const require = createRequire(join(process.argv[2], 'package.json'));
const {PGlite} = require('@electric-sql/pglite');
const {vector} = require('@electric-sql/pglite-pgvector');
const {PGLiteSocketServer} = require('@electric-sql/pglite-socket');

const db = await PGlite.create({extensions: {vector}});
await db.exec('CREATE EXTENSION vector');
await db.exec('CREATE ROLE ci_service LOGIN NOSUPERUSER NOBYPASSRLS');
await db.exec('GRANT USAGE,CREATE ON SCHEMA public TO ci_service');
await db.exec("DO $$ BEGIN EXECUTE format('GRANT CREATE ON DATABASE %I TO ci_service', current_database()); END $$");
const server = new PGLiteSocketServer({db, host: '127.0.0.1', port: 0, maxConnections: 12});
await server.start();
process.stdout.write(JSON.stringify({ready: true, address: server.getServerConn()}) + '\n');
process.stdin.resume();
process.stdin.on('end', async () => {
    await server.stop();
    await db.close();
});
