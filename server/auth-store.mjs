import { createHash, randomBytes, randomUUID, scrypt, timingSafeEqual } from "node:crypto";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { promisify } from "node:util";

const deriveKey = promisify(scrypt);
const hash = value => createHash("sha256").update(value).digest("hex");

export async function createAuthStore(filename) {
    mkdirSync(dirname(filename), { recursive: true, mode: 0o700 });
    const db = new DatabaseSync(filename);
    db.exec(`
        PRAGMA journal_mode = WAL;
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, identity TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL, nickname TEXT NOT NULL,
            password_hash TEXT, password_salt TEXT
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
            expires_at INTEGER NOT NULL
        );
    `);
    const user = row => ({ id: row.id, email: row.email, nickname: row.nickname, notificationsEnabled: false });
    const find = identity => db.prepare("SELECT * FROM users WHERE identity = ?").get(identity);
    const demoEmail = (process.env.AUTH_DEMO_EMAIL || "demo@jeupjeup.local").trim().toLowerCase();
    const demoPassword = process.env.AUTH_DEMO_PASSWORD || "Jeupjeup123!";
    const identity = `email:${demoEmail}`;
    if (!find(identity)) {
        const salt = randomBytes(16).toString("hex");
        const key = await deriveKey(demoPassword, salt, 64);
        db.prepare("INSERT INTO users (id, identity, email, nickname, password_hash, password_salt) VALUES (?, ?, ?, ?, ?, ?)")
            .run(randomUUID(), identity, demoEmail, "예시 사용자", key.toString("hex"), salt);
    }

    return {
        demoEmail,
        async login(email, password) {
            const row = find(`email:${email.trim().toLowerCase()}`);
            // Hash even unknown accounts to avoid a fast account-existence response.
            const key = await deriveKey(password, row?.password_salt || "unknown-account", 64);
            const expected = Buffer.from(row?.password_hash || "00".repeat(64), "hex");
            return row?.password_hash && timingSafeEqual(key, expected) ? user(row) : null;
        },
        socialUser(profile) {
            const identity = `${profile.provider}:${profile.id}`;
            let row = find(identity);
            if (!row) {
                db.prepare("INSERT INTO users (id, identity, email, nickname) VALUES (?, ?, ?, ?)")
                    .run(randomUUID(), identity, profile.email || "", (profile.name || `${profile.provider} 사용자`).slice(0, 25));
                row = find(identity);
            }
            // Provider identity owns the account; matching emails never link accounts.
            return user(row);
        },
        createSession(account, remember = true) {
            const token = randomBytes(32).toString("hex");
            const expiry = Date.now() + (remember ? 30 : 7) * 24 * 60 * 60 * 1000;
            db.prepare("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)").run(hash(token), account.id, expiry);
            return { token, expiresAt: new Date(expiry).toISOString(), user: account };
        },
        session(token) {
            const row = db.prepare("SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id WHERE token_hash = ? AND expires_at > ?")
                .get(hash(token), Date.now());
            return row ? user(row) : null;
        },
        logout(token) { db.prepare("DELETE FROM sessions WHERE token_hash = ?").run(hash(token)); },
        cleanup() { db.prepare("DELETE FROM sessions WHERE expires_at <= ?").run(Date.now()); },
        close() { db.close(); }
    };
}
