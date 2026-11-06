import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";
import { AppState } from "react-native";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { samplePreviewData } from "@/modules/fixtures";
import { api, ApiError } from "@/modules/api";
import { signInWithOAuth, type OAuthProvider } from "@/modules/oauth";
import type { Registration, Session, Snapshot } from "@/types/api";
import type { Notice, SavedContent } from "@/types/content";

type UserData = {
    onboarded: boolean; authenticated: boolean; nickname: string; email: string;
    contents: SavedContent[]; notices: Notice[]; searchHistory: string[]; savedCount: number;
};
const empty: UserData = { onboarded: false, authenticated: false, nickname: "", email: "", contents: [], notices: [], searchHistory: [], savedCount: 0 };
type Update = Partial<UserData> | ((data: UserData) => UserData);
const TOKEN_KEY = "jeupjeup-session-v1";
const ONBOARDING_KEY = "@jeupjeup/onboarded/v1";
const SAVED_PREVIEW_KEY = "@jeupjeup/dev/sample-preset/v1";

function useDataStore() {
    const [data, setData] = useState(empty);
    const [ready, setReady] = useState(false);
    const [loading, setLoading] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const token = useRef<string | null>(null);
    const generation = useRef(0);
    const mutating = useRef(false);
    const readVersion = useRef(0);
    const preview = useRef(false);
    const apply = useCallback((state: Snapshot) => {
        setData(d => ({ ...d, authenticated: true, nickname: state.user.nickname, email: state.user.email, contents: state.contents, notices: state.notices, searchHistory: state.searchHistory, savedCount: state.savedCount }));
    }, []);
    const clearSession = useCallback(async () => {
        generation.current++;
        token.current = null;
        preview.current = false;
        setData(d => ({ ...empty, onboarded: d.onboarded }));
        await SecureStore.deleteItemAsync(TOKEN_KEY);
    }, []);
    const report = useCallback(async (cause: unknown) => {
        if (cause instanceof ApiError && cause.status === 401 && cause.code !== "INVALID_CREDENTIALS") await clearSession();
        const messages: Record<string, string> = {
            DUPLICATE_CONTENT: "이미 저장한 콘텐츠입니다. 보관함을 확인해주세요.",
            CONTENT_DELETED: "휴지통에 있는 콘텐츠입니다. 먼저 복원해주세요.",
            UNAUTHORIZED: "로그인이 만료되었습니다. 다시 로그인해주세요.",
            INVALID_CREDENTIALS: "이메일 또는 비밀번호를 확인해주세요.",
            OAUTH_NOT_CONFIGURED: "소셜 로그인 서버 설정이 필요합니다. 이메일 로그인을 이용해주세요.",
            OAUTH_EMAIL_COLLISION: "이 이메일은 이미 가입되어 있습니다. 기존 로그인 방법을 이용해주세요.",
            OAUTH_EMAIL_REQUIRED: "소셜 계정의 이메일 제공 동의가 필요합니다.",
            OAUTH_EMAIL_UNVERIFIED: "소셜 계정에서 이메일 인증을 완료해주세요.",
            NOT_FOUND: "콘텐츠를 찾을 수 없습니다. 새로고침해주세요."
        };
        setError(cause instanceof ApiError ? messages[cause.code] ?? cause.message : cause instanceof Error ? cause.message : "요청을 처리하지 못했습니다.");
    }, [clearSession]);
    const refresh = useCallback(async () => {
        if (!token.current || preview.current) return;
        const version = ++readVersion.current, activeToken = token.current;
        setLoading(true);
        try {
            const state = await api.state(activeToken);
            if (activeToken === token.current && version === readVersion.current) { apply(state); setError(null); }
        } catch (cause) { if (activeToken === token.current && version === readVersion.current) await report(cause); }
        finally { if (version === readVersion.current) setLoading(false); }
    }, [apply, report]);
    const previewData = useCallback((change: Update) => {
        if (!__DEV__) return;
        preview.current = true;
        ++generation.current;
        ++readVersion.current;
        setLoading(false);
        setError(null);
        setData(d => {
            const next = typeof change === "function" ? change(d) : { ...d, ...change };
            return { ...next, onboarded: true, authenticated: true };
        });
    }, []);
    useEffect(() => {
        let active = true;
        void (async () => {
            try {
                const [onboarded, savedToken, savedPreview] = await Promise.all([
                    AsyncStorage.getItem(ONBOARDING_KEY),
                    SecureStore.getItemAsync(TOKEN_KEY),
                    __DEV__ ? AsyncStorage.getItem(SAVED_PREVIEW_KEY) : Promise.resolve(null)
                ]);
                if (!active) return;
                setData(d => ({ ...d, onboarded: onboarded === "1" }));
                token.current = savedToken;
                if (__DEV__ && savedPreview === "figma-v1") {
                    previewData(samplePreviewData);
                    return;
                }
                if (savedToken) {
                    setData(d => ({ ...d, authenticated: true }));
                    await refresh();
                }
            } catch (cause) { if (active) await report(cause); }
            finally { if (active) setReady(true); }
        })();
        return () => { active = false; };
    }, [refresh, report, previewData]);
    useEffect(() => {
        const subscription = AppState.addEventListener("change", state => { if (state === "active") void refresh(); });
        return () => subscription.remove();
    }, [refresh]);
    const hasAnalysis = data.contents.some(item => !item.deletedAt && item.status === "analyzing");
    useEffect(() => {
        if (!data.authenticated || preview.current) return;
        // Recursive timeout avoids overlapping requests; sync also sees saves made on the web.
        let active = true;
        let timer: ReturnType<typeof setTimeout>;
        const poll = async () => {
            if (AppState.currentState === "active" && !mutating.current) await refresh();
            if (active) timer = setTimeout(() => { void poll(); }, hasAnalysis ? 2500 : 15000);
        };
        timer = setTimeout(() => { void poll(); }, hasAnalysis ? 2500 : 15000);
        return () => { active = false; clearTimeout(timer); };
    }, [data.authenticated, hasAnalysis, refresh]);
    const update = useCallback((change: Update) => {
        setData(d => {
            const next = typeof change === "function" ? change(d) : { ...d, ...change };
            if (next.onboarded !== d.onboarded) void AsyncStorage.setItem(ONBOARDING_KEY, next.onboarded ? "1" : "0").catch(() => setError("기기 설정을 저장하지 못했습니다."));
            return { ...d, onboarded: next.onboarded };
        });
    }, []);
    const saveSampleData = useCallback(async () => {
        if (!__DEV__ || mutating.current) return false;
        try {
            await AsyncStorage.setItem(SAVED_PREVIEW_KEY, "figma-v1");
            previewData(samplePreviewData);
            return true;
        } catch (cause) {
            await report(cause);
            return false;
        }
    }, [previewData, report]);
    const clearSavedSampleData = useCallback(async () => {
        if (!__DEV__ || mutating.current) return false;
        try {
            await AsyncStorage.removeItem(SAVED_PREVIEW_KEY);
            preview.current = false;
            ++generation.current;
            ++readVersion.current;
            setLoading(false);
            setError(null);
            setData({ ...empty, onboarded: true, authenticated: !!token.current });
            await refresh();
            return true;
        } catch (cause) {
            await report(cause);
            return false;
        }
    }, [refresh, report]);
    const execute = useCallback(async <T,>(action: (activeToken: string) => Promise<T>, reload = true): Promise<{ value: T; } | null> => {
        if (mutating.current) return null;
        if (!token.current || preview.current) { setError("로그인 후 이용해주세요. 미리보기 데이터는 서버에 저장하지 않습니다."); return null; }
        const activeToken = token.current, epoch = generation.current;
        mutating.current = true; setBusy(true); setError(null);
        ++readVersion.current;
        try {
            const value = await action(activeToken);
            if (generation.current !== epoch) return null;
            if (reload) await refresh();
            return generation.current === epoch ? { value } : null;
        } catch (cause) { if (generation.current === epoch) await report(cause); return null; }
        finally { mutating.current = false; setBusy(false); setLoading(false); }
    }, [refresh, report]);
    const authenticate = useCallback(async (action: () => Promise<Session | null>) => {
        if (mutating.current) return false;
        mutating.current = true; setBusy(true); setError(null);
        try {
            const session = await action();
            if (!session) return false;
            if (__DEV__) await AsyncStorage.removeItem(SAVED_PREVIEW_KEY);
            await SecureStore.setItemAsync(TOKEN_KEY, session.token);
            generation.current++; token.current = session.token; preview.current = false;
            setData({ ...empty, onboarded: true, authenticated: true, nickname: session.user.nickname, email: session.user.email });
            void AsyncStorage.setItem(ONBOARDING_KEY, "1").catch(() => {});
            await refresh();
            return !!token.current;
        } catch (cause) { await report(cause); return false; }
        finally { mutating.current = false; setBusy(false); }
    }, [refresh, report]);
    const login = (email: string, password: string) => authenticate(() => api.login(email, password));
    const loginSocial = (provider: OAuthProvider) => authenticate(() => signInWithOAuth(provider));
    const register = (body: Registration) => authenticate(() => api.register(body));
    const command = useCallback(async (path: string, method = "POST", body?: unknown) => !!await execute(t => api.request<void>(path, method, body, t)), [execute]);
    const logout = async (withdraw = false) => {
        if (!await execute(t => api.request<void>(withdraw ? "/me" : "/auth/logout", withdraw ? "DELETE" : "POST", withdraw ? undefined : {}, t), false)) return false;
        await clearSession(); return true;
    };
    return {
        data, ready, loading, busy, error, update, previewData, saveSampleData, clearSavedSampleData, refresh, login, loginSocial, register, logout,
        dismissError: () => setError(null), command,
        remove: (id: string) => command(`/contents/${encodeURIComponent(id)}`, "DELETE"),
        restore: (id: string) => command(`/contents/${encodeURIComponent(id)}/restore`, "POST", {}),
        createContent: async (url: string, memo: string) => (await execute(async t => {
            const item = await api.createContent(t, url, memo);
            if (token.current === t) setData(d => ({ ...d, contents: [item, ...d.contents.filter(c => c.id !== item.id)], savedCount: d.savedCount + 1 }));
            return item;
        }))?.value ?? null,
        changeNickname: async (nickname: string) => !!await execute(t => api.profile(t, nickname)),
        verifyPassword: async (currentPassword: string) => !!await execute(t => api.request<void>("/me/password/verify", "POST", { currentPassword }, t), false),
        changePassword: (currentPassword: string, newPassword: string) => command("/me/password", "PATCH", { currentPassword, newPassword })
    };
}
const Context = createContext<ReturnType<typeof useDataStore> | null>(null);
export function UserDataProvider({ children }: { children: ReactNode; }) {
    const store = useDataStore();
    return <Context.Provider value={store}>{children}</Context.Provider>;
}
export function useUserData() {
    const context = useContext(Context);
    if (!context) throw new Error("UserDataProvider is required");
    return context;
}
export function formatDate(value: string) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(date).replaceAll("-", ".");
}
