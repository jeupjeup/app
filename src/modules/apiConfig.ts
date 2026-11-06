import { Platform } from "react-native";

// A physical device uses EXPO_PUBLIC_API_URL pointing to the server's LAN address.
export function apiBaseUrl() {
    const configured = process.env.EXPO_PUBLIC_API_URL?.trim();
    const base = configured || (__DEV__ ? `http://${Platform.OS === "android" ? "10.0.2.2" : "127.0.0.1"}:8000/api` : "");
    let url: URL;
    try { url = new URL(base); } catch { throw new Error("EXPO_PUBLIC_API_URL에 API 주소를 설정해주세요."); }
    if ((!__DEV__ && url.protocol !== "https:") || !["http:", "https:"].includes(url.protocol) ||
        url.username || url.password || url.search || url.hash || url.pathname.replace(/\/+$/, "") !== "/api") {
        throw new Error("API 주소는 /api로 끝나야 하며 운영 환경에서는 HTTPS가 필요합니다.");
    }
    return base.replace(/\/+$/, "");
}
