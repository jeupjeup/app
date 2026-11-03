import { SafeAreaView } from "react-native-safe-area-context";
import { ActivityIndicator, Pressable, View } from "react-native";
import { Text } from "@/components/ui";
import { useUserData } from "@/modules/userData";
import { colors } from "@/modules/theme";

export default function ApiFeedback() {
    const { loading, busy, error, refresh, dismissError, data } = useUserData();
    if (!loading && !busy && !error) return null;
    return <SafeAreaView edges={["top"]} style={{ padding: 12, gap: 8, backgroundColor: colors.soft }}>
        {(loading || busy) && <ActivityIndicator accessibilityLabel="서버 요청 처리 중" color={colors.primary} />}
        {error && <>
            <Text accessibilityRole="alert" style={{ color: colors.error, fontSize: 13 }}>{error}</Text>
            <View style={{ flexDirection: "row", gap: 24 }}>
                {data.authenticated && <Pressable disabled={loading || busy} onPress={() => { void refresh(); }} accessibilityRole="button"><Text>새로고침</Text></Pressable>}
                <Pressable onPress={dismissError} accessibilityRole="button"><Text>닫기</Text></Pressable>
            </View>
        </>}
    </SafeAreaView>;
}
