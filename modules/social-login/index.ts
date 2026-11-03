import { requireOptionalNativeModule } from "expo";

export type NativeOAuthProvider = "naver" | "kakao";
export type NativeOAuthResult =
    | { status: "cancelled" }
    | { status: "success"; accessToken: string; expiresAt: number };

type SocialLoginModule = {
    login(provider: NativeOAuthProvider): Promise<NativeOAuthResult>;
};

// Resolve lazily so an older development build can still open the app.
export function loginWithNativeProvider(provider: NativeOAuthProvider): Promise<NativeOAuthResult> {
    const module = requireOptionalNativeModule<SocialLoginModule>("JeupjeupSocialLogin");
    if (!module) {
        throw new Error("소셜 로그인 네이티브 모듈이 없습니다. 앱을 새로 빌드해주세요.");
    }
    return module.login(provider);
}
