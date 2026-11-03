import ExpoModulesCore
import KakaoSDKCommon
import KakaoSDKAuth
import NidThirdPartyLogin

enum SocialLoginConfiguration {
  private static var kakaoInitialized = false
  private static var naverInitialized = false

  static func value(_ key: String) -> String {
    (Bundle.main.object(forInfoDictionaryKey: key) as? String ?? "")
      .trimmingCharacters(in: .whitespacesAndNewlines)
  }

  static func prepare() {
    let kakaoKey = value("JeupjeupKakaoClientId")
    if !kakaoInitialized && !kakaoKey.isEmpty {
      KakaoSDK.initSDK(appKey: kakaoKey)
      kakaoInitialized = true
    }

    let clientId = value("JeupjeupNaverClientId")
    let secret = value("JeupjeupNaverClientSecret")
    let scheme = value("JeupjeupNaverUrlScheme")
    if !naverInitialized && !clientId.isEmpty && !secret.isEmpty && !scheme.isEmpty {
      NidOAuth.shared.initialize(appName: "줍줍저장소", clientId: clientId,
        clientSecret: secret, urlScheme: scheme)
      NidOAuth.shared.setLoginBehavior(.appPreferredWithInAppBrowserFallback)
      naverInitialized = true
    }
  }
}

public class SocialLoginAppDelegateSubscriber: ExpoAppDelegateSubscriber {
  public func application(_ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
    SocialLoginConfiguration.prepare()
    return true
  }

  public func application(_ app: UIApplication, open url: URL,
    options: [UIApplication.OpenURLOptionsKey: Any] = [:]) -> Bool {
    SocialLoginConfiguration.prepare()
    if AuthApi.isKakaoTalkLoginUrl(url) {
      return AuthController.handleOpenUrl(url: url)
    }
    if url.scheme == SocialLoginConfiguration.value("JeupjeupNaverUrlScheme") {
      return NidOAuth.shared.handleURL(url)
    }
    return false
  }
}
