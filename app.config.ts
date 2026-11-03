import type { ExpoConfig } from "expo/config";

const config: ExpoConfig = {
    "name": "줍줍저장소",
    "slug": "jeupjeupsave",
    "version": "1.0.0",
    "platforms": ["ios", "android"],
    "orientation": "portrait",
    "icon": "./assets/images/icon.png",
    "scheme": "jeupjeupsave",
    "userInterfaceStyle": "light",
    "ios": {
        "appleTeamId": "R394X6W495",
        "icon": "./assets/expo.icon",
        "bundleIdentifier": "kr.pro203s.jeupjeup"
    },
    "android": {
        "package": "kr.pro203s.jeupjeup",
        "adaptiveIcon": {
            "backgroundColor": "#E6F4FE",
            "foregroundImage": "./assets/images/android-icon-foreground.png",
            "backgroundImage": "./assets/images/android-icon-background.png",
            "monochromeImage": "./assets/images/android-icon-monochrome.png"
        },
        "predictiveBackGestureEnabled": false
    },
    "plugins": [
        "expo-router",
        "expo-dev-client",
        "expo-secure-store",
        "expo-web-browser",
        "./plugins/with-native-social-login",
        [
            "expo-splash-screen",
            {
                "backgroundColor": "#FF9F43",
                "image": "./assets/figma/images/logoHome.png",
                "imageWidth": 138
            }
        ]
    ],
    "experiments": {
        "typedRoutes": true,
        "reactCompiler": true
    }
};

export default config;
