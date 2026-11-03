import "expo-dev-client";
import { Stack } from "expo-router";
import { useFonts } from "expo-font";
import * as SplashScreen from "expo-splash-screen";
import { View } from "react-native";
import ApiFeedback from "@/components/ApiFeedback";
import IncomingShareDialog from "@/components/IncomingShareDialog";
import { useEffect } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { UserDataProvider, useUserData } from "@/modules/userData";
import { colors } from "@/modules/theme";
import { useDevelopmentMenu } from "@/modules/useDevelopmentMenu";

void SplashScreen.preventAutoHideAsync();

function Navigator() {
    useDevelopmentMenu();
    const { ready } = useUserData();
    const [loaded, error] = useFonts({
        "Pretendard-Regular": require("@/assets/fonts/pretendard/Pretendard-Regular.otf"),
        "Pretendard-Medium": require("@/assets/fonts/pretendard/Pretendard-Medium.otf"),
        "Pretendard-SemiBold": require("@/assets/fonts/pretendard/Pretendard-SemiBold.otf"),
        "Pretendard-Bold": require("@/assets/fonts/pretendard/Pretendard-Bold.otf"),
        "Paperlogy-Medium": require("@/assets/fonts/paperlogy/Paperlogy-5Medium.ttf"),
        "Paperlogy-Bold": require("@/assets/fonts/paperlogy/Paperlogy-7Bold.ttf")
    });

    useEffect(() => {
        if (ready && (loaded || error)) void SplashScreen.hideAsync();
    }, [ready, loaded, error]);

    if (!ready || (!loaded && !error)) return null;

    return <View style={{ flex: 1, paddingTop: 0 }}><ApiFeedback /><Stack screenOptions={{ "headerShown": false, "contentStyle": { "backgroundColor": colors.background } }} /><IncomingShareDialog /></View>;
}

export default function RootLayout() {
    return <SafeAreaProvider>
        <UserDataProvider>
            <Navigator />
        </UserDataProvider>
    </SafeAreaProvider>;
}
