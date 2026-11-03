package expo.modules.sociallogin

import android.content.Context
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import com.kakao.sdk.common.KakaoSdk
import com.kakao.sdk.common.model.ClientError
import com.kakao.sdk.common.model.ClientErrorCause
import com.kakao.sdk.auth.model.OAuthToken
import com.kakao.sdk.user.UserApiClient
import com.navercorp.nid.NidOAuth
import com.navercorp.nid.core.data.datastore.NidOAuthInitializingCallback
import com.navercorp.nid.oauth.util.NidOAuthCallback
import expo.modules.kotlin.Promise
import expo.modules.kotlin.functions.Queues
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.util.UUID

class SocialLoginModule : Module() {
  private val main = Handler(Looper.getMainLooper())
  private var pending: Pair<String, Promise>? = null
  private var kakaoInitialized = false

  override fun definition() = ModuleDefinition {
    Name("JeupjeupSocialLogin")

    AsyncFunction("login") { provider: String, promise: Promise ->
      if (pending != null) {
        promise.reject("ERR_LOGIN_IN_PROGRESS", "이미 로그인이 진행 중입니다.", null)
      } else {
        val id = UUID.randomUUID().toString()
        pending = id to promise
        try {
          when (provider) {
            "kakao" -> loginKakao(id)
            "naver" -> loginNaver(id)
            else -> fail(id, "ERR_PROVIDER", "지원하지 않는 로그인입니다.")
          }
        } catch (_: Exception) {
          fail(id, "ERR_LOGIN_START", "로그인을 시작하지 못했습니다. 앱 설정을 확인해주세요.")
        }
      }
    }.runOnQueue(Queues.MAIN)

    OnDestroy {
      main.post {
        pending?.first?.let { fail(it, "ERR_LOGIN_INTERRUPTED", "로그인이 중단되었습니다. 다시 시도해주세요.") }
      }
    }
  }

  private fun setting(context: Context, name: String): String {
    val info = context.packageManager.getApplicationInfo(context.packageName, PackageManager.GET_META_DATA)
    val resourceId = info.metaData?.getInt(name, 0) ?: 0
    return if (resourceId != 0) context.getString(resourceId).trim() else ""
  }

  private fun loginKakao(id: String) {
    val activity = appContext.currentActivity
    if (activity == null) {
      fail(id, "ERR_ACTIVITY", "로그인 화면을 표시할 수 없습니다.")
      return
    }
    val key = setting(activity, "JeupjeupKakaoClientId")
    if (key.isBlank()) {
      fail(id, "ERR_KAKAO_CONFIG", "KAKAO_CID에 네이티브 앱 키를 설정하고 앱을 다시 빌드해주세요.")
      return
    }
    if (!kakaoInitialized) {
      KakaoSdk.init(activity.applicationContext, key)
      kakaoInitialized = true
    }

    val completion: (OAuthToken?, Throwable?) -> Unit = { token, error ->
      main.post {
        when {
          isKakaoCancellation(error) -> cancel(id)
          error != null -> fail(id, "ERR_KAKAO_LOGIN", "카카오 로그인에 실패했습니다. 앱 설정과 네트워크를 확인해주세요.")
          token != null -> succeed(id, token.accessToken, token.accessTokenExpiresAt.time)
          else -> fail(id, "ERR_KAKAO_TOKEN", "카카오 인증 토큰을 받지 못했습니다.")
        }
      }
    }
    if (UserApiClient.instance.isKakaoTalkLoginAvailable(activity)) {
      UserApiClient.instance.loginWithKakaoTalk(activity) { token, error ->
        main.post {
          if (pending?.first == id) {
            if (error != null && !isKakaoCancellation(error)) {
              try {
                UserApiClient.instance.loginWithKakaoAccount(activity, callback = completion)
              } catch (_: Exception) {
                fail(id, "ERR_KAKAO_LOGIN", "카카오 계정 로그인 화면을 열지 못했습니다.")
              }
            } else completion(token, error)
          }
        }
      }
    } else {
      UserApiClient.instance.loginWithKakaoAccount(activity, callback = completion)
    }
  }

  private fun loginNaver(id: String) {
    val activity = appContext.currentActivity
    if (activity == null) {
      fail(id, "ERR_ACTIVITY", "로그인 화면을 표시할 수 없습니다.")
      return
    }
    val clientId = setting(activity, "JeupjeupNaverClientId")
    val secret = setting(activity, "JeupjeupNaverClientSecret")
    if (clientId.isBlank() || secret.isBlank()) {
      fail(id, "ERR_NAVER_CONFIG", "NAVER_CID와 NAVER_CLIENT_SECRET을 설정하고 앱을 다시 빌드해주세요.")
      return
    }
    NidOAuth.initialize(activity.applicationContext, clientId, secret, "줍줍저장소",
      object : NidOAuthInitializingCallback {
        override fun onSuccess() {
          main.post {
            if (pending?.first == id) {
              try {
                NidOAuth.requestLogin(activity, object : NidOAuthCallback {
                  override fun onSuccess() {
                    main.post { succeed(id, NidOAuth.getAccessToken().orEmpty(), NidOAuth.getExpiresAt() * 1000L) }
                  }

                  override fun onFailure(errorCode: String, errorDesc: String) {
                    main.post {
                      if (errorCode == "user_cancel" || errorCode == "access_denied") cancel(id)
                      else fail(id, "ERR_NAVER_LOGIN", "네이버 로그인에 실패했습니다. 앱 설정과 네트워크를 확인해주세요.")
                    }
                  }
                })
              } catch (_: Exception) {
                fail(id, "ERR_NAVER_LOGIN", "네이버 로그인 화면을 열지 못했습니다.")
              }
            }
          }
        }

        override fun onFailure(e: Exception) {
          main.post { fail(id, "ERR_NAVER_INIT", "네이버 SDK 초기화에 실패했습니다.") }
        }
      })
  }

  private fun isKakaoCancellation(error: Throwable?): Boolean =
    error is ClientError && error.reason == ClientErrorCause.Cancelled

  private fun succeed(id: String, token: String, expiry: Long) {
    val request = pending?.takeIf { it.first == id } ?: return
    if (token.isBlank() || expiry <= System.currentTimeMillis()) {
      fail(id, "ERR_PROVIDER_TOKEN", "유효한 인증 토큰을 받지 못했습니다.")
      return
    }
    pending = null
    request.second.resolve(mapOf("status" to "success", "accessToken" to token, "expiresAt" to expiry.toDouble()))
  }

  private fun cancel(id: String) {
    val request = pending?.takeIf { it.first == id } ?: return
    pending = null
    request.second.resolve(mapOf("status" to "cancelled"))
  }

  private fun fail(id: String, code: String, message: String) {
    val request = pending?.takeIf { it.first == id } ?: return
    pending = null
    request.second.reject(code, message, null)
  }
}
