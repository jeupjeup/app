const {
  AndroidConfig,
  withAndroidManifest,
  withInfoPlist,
  withProjectBuildGradle,
  withStringsXml,
} = require('expo/config-plugins');

const NAVER_SCHEME = 'kr.pro203s.jeupjeup.naver';

module.exports = function withNativeSocialLogin(config) {
  // Values are read during prebuild, not exposed in expo.extra or public JS env vars.
  const kakaoKey = (
    process.env.KAKAO_CID ||
    process.env.NATIVE_APP_KEY ||
    process.env.EXPO_PUBLIC_KAKAO_NATIVE_APP_KEY ||
    ''
  ).trim();
  const naverId = (process.env.NAVER_CID || '').trim();
  const naverSecret = (process.env.NAVER_CLIENT_SECRET || '').trim();

  config = withInfoPlist(config, (config) => {
    const plist = config.modResults;
    plist.JeupjeupKakaoClientId = kakaoKey;
    plist.JeupjeupNaverClientId = naverId;
    plist.JeupjeupNaverClientSecret = naverSecret;
    plist.JeupjeupNaverUrlScheme = NAVER_SCHEME;
    plist.LSApplicationQueriesSchemes = [...new Set([
      ...(plist.LSApplicationQueriesSchemes || []),
      'kakaokompassauth', 'naversearchapp', 'naversearchthirdlogin',
    ])];
    const schemes = [NAVER_SCHEME, ...(kakaoKey ? [`kakao${kakaoKey}`] : [])];
    const types = plist.CFBundleURLTypes || [];
    for (const scheme of schemes) {
      if (!types.some((entry) => (entry.CFBundleURLSchemes || []).includes(scheme))) {
        types.push({ CFBundleURLSchemes: [scheme] });
      }
    }
    plist.CFBundleURLTypes = types;
    return config;
  });

  config = withStringsXml(config, (config) => {
    config.modResults = AndroidConfig.Strings.setStringItem([
      { $: { name: 'jeupjeup_kakao_client_id', translatable: 'false' }, _: kakaoKey },
      { $: { name: 'jeupjeup_naver_client_id', translatable: 'false' }, _: naverId },
      { $: { name: 'jeupjeup_naver_client_secret', translatable: 'false' }, _: naverSecret },
    ], config.modResults);
    return config;
  });

  config = withAndroidManifest(config, (config) => {
    const app = AndroidConfig.Manifest.getMainApplicationOrThrow(config.modResults);
    app['meta-data'] ||= [];
    for (const [name, resource] of [
      ['JeupjeupKakaoClientId', 'jeupjeup_kakao_client_id'],
      ['JeupjeupNaverClientId', 'jeupjeup_naver_client_id'],
      ['JeupjeupNaverClientSecret', 'jeupjeup_naver_client_secret'],
    ]) {
      app['meta-data'] = app['meta-data'].filter((entry) => entry.$['android:name'] !== name);
      app['meta-data'].push({ $: { 'android:name': name, 'android:resource': `@string/${resource}` } });
    }
    if (kakaoKey) {
      app.activity ||= [];
      const name = 'com.kakao.sdk.auth.AuthCodeHandlerActivity';
      let activity = app.activity.find((entry) => entry.$['android:name'] === name);
      if (!activity) {
        activity = { $: { 'android:name': name }, 'intent-filter': [] };
        app.activity.push(activity);
      }
      activity.$['android:exported'] = 'true';
      // Replace this SDK activity's callback filter when the app key changes.
      activity['intent-filter'] = [{
        action: [{ $: { 'android:name': 'android.intent.action.VIEW' } }],
        category: [
          { $: { 'android:name': 'android.intent.category.DEFAULT' } },
          { $: { 'android:name': 'android.intent.category.BROWSABLE' } },
        ],
        data: [{ $: { 'android:scheme': `kakao${kakaoKey}`, 'android:host': 'oauth' } }],
      }];
    }
    return config;
  });

  return withProjectBuildGradle(config, (config) => {
    const repository = 'https://devrepo.kakao.com/nexus/content/groups/public/';
    if (!config.modResults.contents.includes(repository)) {
      config.modResults.contents += `\n// Kakao Login SDK repository\nallprojects {\n  repositories {\n    maven { url '${repository}' }\n  }\n}\n`;
    }
    return config;
  });
};
