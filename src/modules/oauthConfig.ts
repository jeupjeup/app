import type { NativeOAuthProvider } from "../../modules/social-login";

export type OAuthProvider = NativeOAuthProvider | "google";

// The server redirects with a short-lived app code, never a provider token or app session.
export const OAUTH_REDIRECT_URI = "jeupjeupsave://login";

export type GoogleOAuthExchangeRequest = {
    code: string;
    state: string;
    code_verifier: string;
    redirect_uri: string;
};
