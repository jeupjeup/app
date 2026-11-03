export function redirectSystemPath({ path, initial }: { path: string; initial: boolean; }) {
    try {
        const url = new URL(path, "jeupjeupsave://app");
        const kakaoCallback = /^kakao[0-9a-f]+:$/i.test(url.protocol) && url.hostname === "oauth";
        const naverCallback = url.protocol === "kr.pro203s.jeupjeup.naver:";

        if (kakaoCallback || naverCallback) {
            // The native SDK consumes the original URL and completes login.
            // Ignore its navigation event so it cannot replace the login/home screen.
            return initial ? "/login" : "";
        }
    } catch {
        // Preserve unrelated intents; never crash while inspecting an incoming link.
    }
    return path;
}
