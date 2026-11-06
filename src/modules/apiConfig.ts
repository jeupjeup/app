// EXPO_PUBLIC_API_URL can override the deployed API for local development.
export function apiBaseUrl() {
    const configured = process.env.EXPO_PUBLIC_API_URL?.trim();
    const base = configured || "https://jeupjeup-api.pro203s.kr/api";
    let url: URL;
    try { url = new URL(base); } catch { throw new Error("EXPO_PUBLIC_API_URL에 API 주소를 설정해주세요."); }
    if ((!__DEV__ && url.protocol !== "https:") || !["http:", "https:"].includes(url.protocol) ||
        url.username || url.password || url.search || url.hash || url.pathname.replace(/\/+$/, "") !== "/api") {
        throw new Error("API 주소는 /api로 끝나야 하며 운영 환경에서는 HTTPS가 필요합니다.");
    }
    return base.replace(/\/+$/, "");
}
