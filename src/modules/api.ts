import type { Registration, Session, Snapshot, User } from "@/types/api";
import type { SavedContent } from "@/types/content";

type RecordValue = Record<string, unknown>;
const record = (value: unknown): value is RecordValue => !!value && typeof value === "object" && !Array.isArray(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(v => typeof v === "string");
const date = (value: unknown) => typeof value === "string" && Number.isFinite(Date.parse(value));
const userShape = (value: unknown) => record(value) && [value.id, value.email, value.nickname].every(v => typeof v === "string") && typeof value.notificationsEnabled === "boolean";
const contentShape = (v: unknown) => record(v) && [v.id, v.title, v.url, v.memo, v.source, v.description].every(x => typeof x === "string") &&
    ["영상", "이미지", "텍스트", "기타"].includes(String(v.type)) && ["ready", "analyzing", "failed", "unavailable"].includes(String(v.status)) &&
    strings(v.tags) && date(v.savedAt) && (v.deletedAt === undefined || date(v.deletedAt)) && (v.viewedAt === undefined || date(v.viewedAt)) &&
    (v.collection === undefined || ["장소", "여행", "음식", "의류", "제품", "회사"].includes(String(v.collection)));
function checked<T>(value: T, valid: boolean): T {
    if (!valid) throw new ApiError(0, "INVALID_RESPONSE", "서버 응답 형식이 올바르지 않습니다.");
    return value;
}
const sessionShape = (s: Session) => record(s) && typeof s.token === "string" && /^[a-f0-9]{64}$/.test(s.token) && date(s.expiresAt) && userShape(s.user);

export class ApiError extends Error {
    status: number;
    code: string;
    constructor(status: number, code: string, message: string) { super(message); this.status = status; this.code = code; }
}

export const api = {
    async request<T>(path: string, method = "GET", body?: unknown, token?: string, signal?: AbortSignal): Promise<T> {
        const base = process.env.EXPO_PUBLIC_API_URL?.replace(/\/$/, "");
        if (!base) throw new ApiError(0, "CONFIGURATION", "API 주소가 설정되지 않았습니다. EXPO_PUBLIC_API_URL을 확인해주세요.");
        const controller = new AbortController();
        const abort = () => controller.abort();
        if (signal?.aborted) controller.abort();
        signal?.addEventListener("abort", abort);
        const timeout = setTimeout(abort, 12000);
        try {
            const response = await fetch(`${base}${path}`, {
                method, headers: { Accept: "application/json", ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
                body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal
            });
            if (response.status === 204) return undefined as T;
            const payload = await response.json().catch(() => null);
            if (!response.ok) throw new ApiError(response.status, payload?.error?.code || "HTTP_ERROR", payload?.error?.message || (response.status === 403 ? "접근 권한이 없습니다." : "요청을 처리하지 못했습니다."));
            if (payload === null) throw new ApiError(0, "INVALID_RESPONSE", "서버 응답 형식이 올바르지 않습니다.");
            return payload as T;
        } catch (error) {
            if (error instanceof ApiError) throw error;
            throw new ApiError(0, controller.signal.aborted ? "TIMEOUT" : "NETWORK", controller.signal.aborted ? "요청 시간이 초과되었습니다. 다시 시도해주세요." : "서버에 연결할 수 없습니다. 인터넷 연결과 API 주소를 확인해주세요.");
        } finally { clearTimeout(timeout); signal?.removeEventListener("abort", abort); }
    },
    login: async (email: string, password: string) => { const s = await api.request<Session>("/auth/login", "POST", { email, password }); return checked(s, sessionShape(s)); },
    register: async (body: Registration) => { const s = await api.request<Session>("/auth/register", "POST", body); return checked(s, sessionShape(s)); },
    state: async (token: string) => {
        const s = await api.request<Snapshot>("/state", "GET", undefined, token);
        return checked(s, record(s) && userShape(s.user) && Array.isArray(s.contents) && s.contents.every(contentShape) &&
            Array.isArray(s.notices) && s.notices.every(n => record(n) && [n.id, n.title, n.description].every(v => typeof v === "string") && date(n.date) && typeof n.read === "boolean") &&
            strings(s.searchHistory) && Number.isInteger(s.savedCount) && s.savedCount >= 0);
    },
    createContent: async (token: string, url: string, memo: string) => { const c = await api.request<SavedContent>("/contents", "POST", { url, memo }, token); return checked(c, contentShape(c)); },
    profile: async (token: string, nickname: string) => { const u = await api.request<User>("/me", "PATCH", { nickname }, token); return checked(u, userShape(u)); }
};
