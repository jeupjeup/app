import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const backend = resolve(root, 'jupjup-web-backend-mobile');
const command = process.argv[2] || 'all';
const env = { ...process.env, JUPJUP_AUTH_BACKEND: 'app_session', JUPJUP_ADMIN_API_ENABLED: 'false', JUPJUP_APP_BRIDGE_ENABLED: 'true' };
env.JUPJUP_API_ORIGIN ||= `http://127.0.0.1:${process.env.JUPJUP_API_PORT || '8000'}`;
const children = new Set();
let stopping = false;
function stop(code = 0) {
    if (stopping) return;
    stopping = true;
    for (const child of children) {
        try {
            if (process.platform === 'win32') child.kill('SIGTERM');
            else process.kill(-child.pid, 'SIGTERM');
        } catch (error) { if (error.code !== 'ESRCH') console.error(error.message); }
    }
    process.exitCode = code;
}
function run(bin, args, cwd = root) {
    const child = spawn(bin, args, { cwd, env, stdio: 'inherit', detached: process.platform !== 'win32' });
    children.add(child);
    child.on('error', error => { console.error(error.message); stop(1); });
    child.on('exit', code => { children.delete(child); if (!stopping) stop(code ?? 1); });
}
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => stop());
if (!['all', 'api', 'web'].includes(command)) throw new Error('Expected all, api, or web');
if (command !== 'web') {
    const executable = resolve(backend, '.venv/bin/jupjup');
    if (!existsSync(executable)) throw new Error('Run uv sync --project jupjup-web-backend-mobile first');
    const host = process.env.JUPJUP_API_HOST || '127.0.0.1';
    const args = ['api', 'serve', '--host', host, '--port', process.env.JUPJUP_API_PORT || '8000', '--with-worker'];
    if (!['127.0.0.1', 'localhost', '::1'].includes(host)) args.push('--allow-external-bind');
    run(executable, args, backend);
}
if (command !== 'api') run('npm', ['run', 'dev'], resolve(backend, 'frontend'));
if (command === 'all') run('bunx', ['expo', 'start', ...process.argv.slice(3)]);
