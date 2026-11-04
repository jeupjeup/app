import { router } from "expo-router";
import { Linking, StyleSheet, View } from "react-native";
import { Header, Screen, Text, ui } from "@/components/ui";
import { ProfileRow, ServiceRow } from "@/components/ProfileRow";
import { colors, fonts } from "@/modules/theme";
import { useUserData } from "@/modules/userData";

// 191:3545 — no additional settings screens outside P-01.
export default function Page() {
    const { data } = useUserData();

    return <Screen>
        <Header title="마이페이지" back={false} />
        <ProfileRow onPress={() => router.push("/mypage/account")} />
        <View style={{ "paddingHorizontal": 16, "paddingTop": 20, "gap": 22 }}>
            <Text style={ui.subtitle}>내 정보</Text>
            <View style={{ "flexDirection": "row", "gap": 12 }}>
                {[
                    { "title": "지금까지 저장한 개수", "value": `${data.savedCount}개` },
                    { "title": "총 컬렉션 수", "value": `${new Set(data.contents.filter(c => !c.deletedAt && c.collection).map(c => c.collection)).size}개` }
                ].map((stat) => (
                    <View key={stat.title} style={styles.stat}>
                        <Text style={styles.statLabel}>{stat.title}</Text>
                        <Text style={styles.statValue}>{stat.value}</Text>
                    </View>
                ))}
            </View>
            <Text style={ui.subtitle}>서비스 관리</Text>
        </View>
        <View style={{ "marginTop": 20 }}>
            <ServiceRow icon="support" title="고객센터" onPress={() => { const url = process.env.EXPO_PUBLIC_SUPPORT_URL; if (url) void Linking.openURL(url).catch(() => {}); }} />
            <ServiceRow
                icon="computer"
                title="앱 이용 방법"
                onPress={() => router.push({ "pathname": "/onboarding", "params": { "guide": "1" } })}
            />
            <ServiceRow icon="history" title="최근 본 상품" onPress={() => router.push("/mypage/recent")} />
            <ServiceRow icon="trash" title="휴지통" onPress={() => router.push("/mypage/trash")} />
        </View>
    </Screen>;
}

const styles = StyleSheet.create({
    "stat": {
        "flex": 1,
        "minHeight": 70,
        "backgroundColor": colors.primary,
        "borderRadius": 6,
        "justifyContent": "center",
        "padding": 16,
        "gap": 4
    },
    "statLabel": {
        "color": colors.white,
        "fontSize": 10
    },
    "statValue": {
        "color": colors.white,
        "fontFamily": fonts.semibold,
        "fontSize": 18
    }
});
