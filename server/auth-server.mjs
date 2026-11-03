import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { createAuthStore } from "./auth-store.mjs";

const port = Number(process.env.AUTH_PORT || 3001);
const host = process.env.AUTH_HOST || "0.0.0.0";
const publicUrl = new URL(process.env.AUTH_PUBLIC_BASE_URL || `http://localhost:${port}`);
if (!Number.isInteger(port) || port < 1 || port > 65535 || !["http:", "https:"].includes(publicUrl.protocol) ||
    publicUrl.pathname !== "/" || publicUrl.search || publicUrl.hash || publicUrl.username || publicUrl.password) {
    throw new Error("AUTH_PORT 또는 AUTH_PUBLIC_BASE_URL(origin) 설정을 확인해주세요.");
}
const appRedirect = "jeupjeupsave://login";
const googleId = process.env.GOOGLE_CLIENT_ID?.trim();
const googleSecret = process.env.GOOGLE_CLIENT_SECRET?.trim();
const kakaoAppId = process.env.KAKAO_APP_ID?.trim();
const callbackUri = new URL("/api/auth/oauth/google/callback", publicUrl).toString();
const store = await createAuthStore(fileURLToPath(new URL("../.data/auth.sqlite", import.meta.url)));
const googleStates = new Map();
const appCodes = new Map();
const limits = new Map();

class HttpError extends Error {
    constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}
function json(response, status, value) {
    response.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    response.end(status === 204 ? undefined : JSON.stringify(value));
}
function redirect(response, location) {
    response.writeHead(302, { "Location": location, "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" });
    response.end();
}
function appCallback(state, values) {
    const url = new URL(appRedirect);
    url.searchParams.set("state", state);
    for (const [key, value] of Object.entries(values)) url.searchParams.set(key, value);
    return url.toString();
}
async function readJson(request) {
    if (request.headers["content-type"]?.split(";")[0].trim() !== "application/json") {
        throw new HttpError(415, "UNSUPPORTED_MEDIA_TYPE", "JSON 요청이 필요합니다.");
    }
    const chunks = [];
    let size = 0;
    for await (const chunk of request) {
        size += chunk.length;
        if (size > 16_384) throw new HttpError(413, "PAYLOAD_TOO_LARGE", "요청 본문이 너무 큽니다.");
        chunks.push(chunk);
    }
    let body;
    try { body = JSON.parse(Buffer.concat(chunks).toString("utf8")); }
    catch { throw new HttpError(400, "INVALID_JSON", "JSON 요청 형식이 올바르지 않습니다."); }
    if (!body || typeof body !== "object" || Array.isArray(body)) throw new HttpError(400, "VALIDATION_ERROR", "객체 형식의 요청이 필요합니다.");
    return body;
}
function authenticated(request) {
    const match = request.headers.authorization?.match(/^Bearer ([a-f0-9]{64})$/);
    const user = match ? store.session(match[1]) : null;
    if (!user) throw new HttpError(401, "UNAUTHORIZED", "로그인이 만료되었습니다. 다시 로그인해주세요.");
    return { user, token: match[1] };
}
function rateLimit(request) {
    const key = request.socket.remoteAddress;
    let entry = limits.get(key);
    if (!entry || entry.expiresAt <= Date.now()) {
        entry = { count: 0, expiresAt: Date.now() + 60_000 };
        limits.set(key, entry);
    }
    if (++entry.count > 60) throw new HttpError(429, "RATE_LIMITED", "로그인 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.");
}
async function providerJson(url, options = {}) {
    let response;
    try { response = await fetch(url, { ...options, signal: AbortSignal.timeout(5000), redirect: "error" }); }
    catch { throw new HttpError(502, "PROVIDER_UNAVAILABLE", "소셜 인증 서버에 연결하지 못했습니다."); }
    if (!response.ok) {
        if (response.status >= 500 || response.status === 429) throw new HttpError(502, "PROVIDER_UNAVAILABLE", "소셜 인증 서버가 응답하지 않습니다.");
        throw new HttpError(401, "INVALID_PROVIDER_TOKEN", "소셜 인증이 만료되었거나 유효하지 않습니다.");
    }
    return response.json();
}
async function nativeProfile(provider, token) {
    const headers = { "Authorization": `Bearer ${token}` };
    if (provider === "naver") {
        const data = await providerJson("https://openapi.naver.com/v1/nid/me", { headers });
        const profile = data.response;
        if (data.resultcode !== "00" || typeof profile?.id !== "string" || !profile.id) {
            throw new HttpError(401, "INVALID_PROVIDER_TOKEN", "네이버 사용자 정보를 확인하지 못했습니다.");
        }
        return { provider, id: profile.id, name: profile.nickname || profile.name, email: profile.email };
    }
    if (!kakaoAppId) throw new HttpError(503, "PROVIDER_NOT_CONFIGURED", "서버에 KAKAO_APP_ID(숫자 앱 ID)를 설정해주세요.");
    const info = await providerJson("https://kapi.kakao.com/v1/user/access_token_info", { headers });
    if (String(info.app_id) !== kakaoAppId || !(info.expires_in > 0)) {
        throw new HttpError(401, "INVALID_PROVIDER_TOKEN", "이 앱에서 발급받은 카카오 인증 토큰이 아닙니다.");
    }
    const data = await providerJson("https://kapi.kakao.com/v2/user/me", { headers });
    if (!data.id || String(data.id) !== String(info.id)) throw new HttpError(401, "INVALID_PROVIDER_TOKEN", "카카오 사용자 정보를 확인하지 못했습니다.");
    return { provider, id: String(data.id), name: data.kakao_account?.profile?.nickname, email: data.kakao_account?.is_email_verified ? data.kakao_account.email : "" };
}
function googleAuthorize(url, response) {
    const params = url.searchParams;
    for (const key of ["state", "redirect_uri", "code_challenge", "code_challenge_method", "keep_me_logged_in"]) {
        if (params.getAll(key).length !== 1) throw new HttpError(400, "INVALID_OAUTH_REQUEST", "로그인 요청을 확인할 수 없습니다.");
    }
    const state = params.get("state"), challenge = params.get("code_challenge");
    if (!/^[a-f0-9]{64}$/.test(state || "") || params.get("redirect_uri") !== appRedirect ||
        !/^[A-Za-z0-9_-]{43}$/.test(challenge || "") || params.get("code_challenge_method") !== "S256" ||
        !["true", "false"].includes(params.get("keep_me_logged_in"))) {
        throw new HttpError(400, "INVALID_OAUTH_REQUEST", "callback, state 또는 PKCE 설정을 확인해주세요.");
    }
    if (!googleId || !googleSecret) throw new HttpError(503, "PROVIDER_NOT_CONFIGURED", "서버에 GOOGLE_CLIENT_ID와 GOOGLE_CLIENT_SECRET을 설정해주세요.");
    const serverState = randomBytes(32).toString("hex");
    googleStates.set(serverState, { state, challenge, remember: params.get("keep_me_logged_in") === "true", expiresAt: Date.now() + 10 * 60_000 });
    const target = new URL("https://accounts.google.com/o/oauth2/v2/auth");
    for (const [key, value] of Object.entries({ "client_id": googleId, "redirect_uri": callbackUri, "response_type": "code", "scope": "openid email profile", "state": serverState, "prompt": "select_account" })) {
        target.searchParams.set(key, value);
    }
    redirect(response, target.toString());
}
async function googleCallback(url, response) {
    const params = url.searchParams;
    const state = params.getAll("state").length === 1 ? googleStates.get(params.get("state")) : null;
    if (!state || state.expiresAt <= Date.now()) throw new HttpError(400, "INVALID_OAUTH_STATE", "인증 요청이 만료되었습니다. 다시 로그인해주세요.");
    googleStates.delete(params.get("state"));
    if (params.has("error")) {
        return redirect(response, appCallback(state.state, { error: params.get("error") === "access_denied" ? "access_denied" : "server_error" }));
    }
    if (params.getAll("code").length !== 1 || !params.get("code")) {
        return redirect(response, appCallback(state.state, { error: "server_error" }));
    }
    try {
        const token = await providerJson("https://oauth2.googleapis.com/token", {
            method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: new URLSearchParams({ "code": params.get("code"), "client_id": googleId, "client_secret": googleSecret, "redirect_uri": callbackUri, "grant_type": "authorization_code" })
        });
        if (typeof token.access_token !== "string" || !token.access_token) throw new Error("Missing Google token");
        const profile = await providerJson("https://openidconnect.googleapis.com/v1/userinfo", { headers: { "Authorization": `Bearer ${token.access_token}` } });
        if (typeof profile.sub !== "string" || !profile.sub) throw new Error("Missing Google identity");
        const code = randomBytes(32).toString("hex");
        appCodes.set(code, { ...state, expiresAt: Date.now() + 5 * 60_000, profile: { provider: "google", id: profile.sub, name: profile.name, email: profile.email_verified ? profile.email : "" } });
        redirect(response, appCallback(state.state, { code }));
    } catch {
        redirect(response, appCallback(state.state, { error: "server_error" }));
    }
}
async function googleExchange(request, response) {
    const body = await readJson(request);
    if (typeof body.code !== "string" || typeof body.state !== "string" ||
        typeof body.code_verifier !== "string" || !/^[A-Za-z0-9._~-]{43,128}$/.test(body.code_verifier) || body.redirect_uri !== appRedirect) {
        throw new HttpError(400, "VALIDATION_ERROR", "인증 코드 교환 요청을 확인해주세요.");
    }
    const pending = appCodes.get(body.code);
    const challenge = createHash("sha256").update(body.code_verifier).digest("base64url");
    if (!pending || pending.expiresAt <= Date.now() || pending.state !== body.state ||
        !timingSafeEqual(Buffer.from(challenge), Buffer.from(pending.challenge))) {
        throw new HttpError(401, "INVALID_OAUTH_CODE", "인증 코드가 유효하지 않거나 만료되었습니다.");
    }
    appCodes.delete(body.code);
    json(response, 200, store.createSession(store.socialUser(pending.profile), pending.remember));
}

const server = createServer(async (request, response) => {
    try {
        const url = new URL(request.url, publicUrl);
        const path = url.pathname;
        if (request.method === "GET" && path === "/api/health") {
            return json(response, 200, { status: "ok", service: "jeupjeup-example-auth", googleConfigured: !!(googleId && googleSecret), kakaoConfigured: !!kakaoAppId });
        }
        if (path.startsWith("/api/auth/")) rateLimit(request);
        if (request.method === "POST" && path === "/api/auth/login") {
            const body = await readJson(request);
            if (typeof body.email !== "string" || !body.email.trim() || body.email.length > 254 || typeof body.password !== "string" || !body.password || body.password.length > 128) {
                throw new HttpError(400, "VALIDATION_ERROR", "이메일과 비밀번호를 입력해주세요.");
            }
            const user = await store.login(body.email, body.password);
            if (!user) throw new HttpError(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호가 틀렸습니다.");
            return json(response, 200, store.createSession(user));
        }
        if (request.method === "POST" && path === "/api/auth/logout") {
            store.logout(authenticated(request).token);
            return json(response, 204);
        }
        if (request.method === "GET" && path === "/api/auth/oauth/google/authorize") return googleAuthorize(url, response);
        if (request.method === "GET" && path === "/api/auth/oauth/google/callback") return await googleCallback(url, response);
        if (request.method === "POST" && path === "/api/auth/oauth/google/exchange") return await googleExchange(request, response);
        const native = path.match(/^\/api\/auth\/oauth\/(naver|kakao)\/exchange$/);
        if (request.method === "POST" && native) {
            const body = await readJson(request);
            if (typeof body.access_token !== "string" || body.access_token.length < 10 || body.access_token.length > 8192 || /\s/.test(body.access_token) || typeof body.keep_me_logged_in !== "boolean") {
                throw new HttpError(400, "VALIDATION_ERROR", "소셜 인증 토큰 요청을 확인해주세요.");
            }
            const profile = await nativeProfile(native[1], body.access_token);
            return json(response, 200, store.createSession(store.socialUser(profile), body.keep_me_logged_in));
        }
        if (request.method === "GET" && ["/api/state", "/api/me"].includes(path)) {
            const { user } = authenticated(request);
            return json(response, 200, path === "/api/me" ? user : { user, contents: [], notices: [], searchHistory: [], savedCount: 0 });
        }
        throw new HttpError(501, "NOT_IMPLEMENTED", "로그인 전용 예시 서버입니다. 이 기능은 구현되지 않았습니다.");
    } catch (error) {
        if (response.headersSent || response.destroyed) return;
        if (!(error instanceof HttpError)) console.error("Auth request failed:", error.message);
        json(response, error instanceof HttpError ? error.status : 500, { error: { code: error instanceof HttpError ? error.code : "INTERNAL_ERROR", message: error instanceof HttpError ? error.message : "인증 서버에서 오류가 발생했습니다." } });
    }
});
server.requestTimeout = 15_000;
const cleanup = setInterval(() => {
    for (const map of [googleStates, appCodes, limits]) {
        for (const [key, value] of map) if (value.expiresAt <= Date.now()) map.delete(key);
    }
    store.cleanup();
}, 60_000);
cleanup.unref();
server.on("error", error => { console.error(`Auth server could not listen: ${error.message}`); clearInterval(cleanup); store.close(); process.exitCode = 1; });
server.listen(port, host, () => {
    console.log(`Example auth API: http://${host}:${port}/api`);
    console.log(`Demo email: ${store.demoEmail}`);
    console.log(`Google callback: ${callbackUri} (${googleId && googleSecret ? "configured" : "credentials required"})`);
});
for (const signal of ["SIGINT", "SIGTERM"]) process.once(signal, () => {
    clearInterval(cleanup);
    server.close(() => { store.close(); process.exit(0); });
});
