import * as Crypto from "expo-crypto";
import * as WebBrowser from "expo-web-browser";
import { loginWithNativeProvider } from "../../modules/social-login";
import { api, ApiError } from "@/modules/api";
import { OAUTH_REDIRECT_URI, type OAuthProvider } from "@/modules/oauthConfig";

export type { OAuthProvider } from "@/modules/oauthConfig";

async function randomToken() {
    const bytes = await Crypto.getRandomBytesAsync(32);
    return Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
}

async function signInWithGoogle(base: string) {
    const [state, verifier] = await Promise.all([randomToken(), randomToken()]);
    const digest = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, verifier, {
        encoding: Crypto.CryptoEncoding.BASE64
    });
    const authorizeUrl = new URL(`${base.replace(/\/+$/, "")}/auth/oauth/google/authorize`);
    authorizeUrl.searchParams.set("redirect_uri", OAUTH_REDIRECT_URI);
    authorizeUrl.searchParams.set("state", state);
    authorizeUrl.searchParams.set("code_challenge", digest.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""));
    authorizeUrl.searchParams.set("code_challenge_method", "S256");
    authorizeUrl.searchParams.set("keep_me_logged_in", "true");

    const result = await WebBrowser.openAuthSessionAsync(authorizeUrl.toString(), OAUTH_REDIRECT_URI);
    if (result.type === "cancel" || result.type === "dismiss") return null;
    if (result.type !== "success") throw new Error("로그인 창을 열지 못했습니다. 다시 시도해주세요.");

    const callback = new URL(result.url);
    const expected = new URL(OAUTH_REDIRECT_URI);
    if (
        callback.protocol !== expected.protocol || callback.host !== expected.host ||
        callback.pathname !== expected.pathname || callback.username || callback.password || callback.hash ||
        callback.searchParams.getAll("state").length !== 1 || callback.searchParams.get("state") !== state ||
        callback.searchParams.getAll("error").length > 1 ||
        (callback.searchParams.has("error") && callback.searchParams.has("code"))
    ) {
        throw new Error("로그인 요청을 확인할 수 없습니다. 다시 시도해주세요.");
    }
    if (callback.searchParams.get("error") === "access_denied") return null;
    if (callback.searchParams.has("error")) throw new Error("구글 인증에 실패했습니다. 다시 시도해주세요.");
    const code = callback.searchParams.get("code");
    if (!code?.trim() || callback.searchParams.getAll("code").length !== 1) {
        throw new Error("로그인 인증 코드가 없습니다.");
    }
    return api.googleLogin({ code, state, code_verifier: verifier, redirect_uri: OAUTH_REDIRECT_URI });
}

export async function signInWithOAuth(provider: OAuthProvider) {
    // Check the server before starting provider authentication.
    const base = process.env.EXPO_PUBLIC_API_URL?.trim();
    if (!base) throw new ApiError(0, "CONFIGURATION", "로그인 서버가 아직 설정되지 않았습니다. EXPO_PUBLIC_API_URL을 확인해주세요.");
    let url: URL;
    try { url = new URL(base); }
    catch { throw new ApiError(0, "CONFIGURATION", "로그인 서버 주소 설정을 확인해주세요."); }
    if ((url.protocol !== "https:" && !(__DEV__ && url.protocol === "http:")) || url.username || url.password || url.search || url.hash) {
        throw new ApiError(0, "CONFIGURATION", "로그인 서버 주소 설정을 확인해주세요.");
    }

    if (provider === "google") return signInWithGoogle(base);

    const result = await loginWithNativeProvider(provider);
    if (result.status === "cancelled") return null;
    if (result.status !== "success" || typeof result.accessToken !== "string" || !result.accessToken.trim() || !Number.isFinite(result.expiresAt) || result.expiresAt <= Date.now()) {
        throw new Error("유효한 소셜 로그인 토큰을 받지 못했습니다.");
    }
    // Only the server-issued app session is persisted, never the provider token.
    return api.socialLogin(provider, result.accessToken);
}
