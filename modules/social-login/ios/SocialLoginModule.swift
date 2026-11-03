import ExpoModulesCore
import KakaoSDKCommon
import KakaoSDKAuth
import KakaoSDKUser
import NidThirdPartyLogin

public class SocialLoginModule: Module {
  private var pending: (id: UUID, promise: Promise)?

  public func definition() -> ModuleDefinition {
    Name("JeupjeupSocialLogin")

    AsyncFunction("login") { (provider: String, promise: Promise) in
      guard self.pending == nil else {
        promise.reject("ERR_LOGIN_IN_PROGRESS", "이미 로그인이 진행 중입니다.")
        return
      }
      SocialLoginConfiguration.prepare()
      let id = UUID()
      self.pending = (id, promise)
      switch provider {
      case "kakao": self.loginKakao(id)
      case "naver": self.loginNaver(id)
      default: self.fail(id, "ERR_PROVIDER", "지원하지 않는 로그인입니다.")
      }
    }.runOnQueue(.main)

    OnDestroy {
      DispatchQueue.main.async {
        if let id = self.pending?.id {
          self.fail(id, "ERR_LOGIN_INTERRUPTED", "로그인이 중단되었습니다. 다시 시도해주세요.")
        }
      }
    }
  }

  private func loginKakao(_ id: UUID) {
    guard !SocialLoginConfiguration.value("JeupjeupKakaoClientId").isEmpty else {
      fail(id, "ERR_KAKAO_CONFIG", "KAKAO_CID에 네이티브 앱 키를 설정하고 앱을 다시 빌드해주세요.")
      return
    }
    let completion: (OAuthToken?, Error?) -> Void = { token, error in
      DispatchQueue.main.async {
        if let error {
          if self.isKakaoCancellation(error) { self.cancel(id) }
          else { self.fail(id, "ERR_KAKAO_LOGIN", "카카오 로그인에 실패했습니다. 앱 설정과 네트워크를 확인해주세요.") }
        } else if let token {
          self.succeed(id, token.accessToken, token.expiredAt)
        } else {
          self.fail(id, "ERR_KAKAO_TOKEN", "카카오 인증 토큰을 받지 못했습니다.")
        }
      }
    }

    if UserApi.isKakaoTalkLoginAvailable() {
      UserApi.shared.loginWithKakaoTalk(launchMethod: .CustomScheme) { token, error in
        DispatchQueue.main.async {
          guard self.pending?.id == id else { return }
          if let error, !self.isKakaoCancellation(error) {
            UserApi.shared.loginWithKakaoAccount(completion: completion)
          } else {
            completion(token, error)
          }
        }
      }
    } else {
      UserApi.shared.loginWithKakaoAccount(completion: completion)
    }
  }

  private func loginNaver(_ id: UUID) {
    guard !SocialLoginConfiguration.value("JeupjeupNaverClientId").isEmpty,
      !SocialLoginConfiguration.value("JeupjeupNaverClientSecret").isEmpty else {
      fail(id, "ERR_NAVER_CONFIG", "NAVER_CID와 NAVER_CLIENT_SECRET을 설정하고 앱을 다시 빌드해주세요.")
      return
    }
    NidOAuth.shared.requestLogin { result in
      DispatchQueue.main.async {
        switch result {
        case .success(let result):
          self.succeed(id, result.accessToken.tokenString, result.accessToken.expiresAt)
        case .failure(let error):
          if case .clientError(.canceledByUser) = error { self.cancel(id) }
          else { self.fail(id, "ERR_NAVER_LOGIN", "네이버 로그인에 실패했습니다. 앱 설정과 네트워크를 확인해주세요.") }
        }
      }
    }
  }

  private func isKakaoCancellation(_ error: Error) -> Bool {
    guard let error = error as? SdkError else { return false }
    if case .ClientFailed(reason: .Cancelled, errorMessage: _) = error { return true }
    if case .AuthFailed(reason: .AccessDenied, errorInfo: _) = error { return true }
    return false
  }

  private func succeed(_ id: UUID, _ token: String, _ expiry: Date) {
    guard let request = pending, request.id == id else { return }
    guard !token.isEmpty, expiry > Date() else {
      fail(id, "ERR_PROVIDER_TOKEN", "유효한 인증 토큰을 받지 못했습니다.")
      return
    }
    pending = nil
    request.promise.resolve(["status": "success", "accessToken": token,
      "expiresAt": expiry.timeIntervalSince1970 * 1000] as [String: Any])
  }

  private func cancel(_ id: UUID) {
    guard let request = pending, request.id == id else { return }
    pending = nil
    request.promise.resolve(["status": "cancelled"])
  }

  private func fail(_ id: UUID, _ code: String, _ message: String) {
    guard let request = pending, request.id == id else { return }
    pending = nil
    request.promise.reject(code, message)
  }
}
