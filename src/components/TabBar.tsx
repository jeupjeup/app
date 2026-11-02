import { Pressable, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Icon, Text } from "./ui";
import { colors, fonts } from "@/modules/theme";

const tabs = [
    { route: "home", title: "홈", icon: "home", width: 16, height: 18 },
    { route: "library", title: "보관함", icon: "archive", width: 18, height: 18 },
    { route: "mypage", title: "마이", icon: "my", width: 20, height: 20 }
] as const;
export default function TabBar({ active, onNavigate }: { active: string; onNavigate: (route: string) => void }) {
    const insets = useSafeAreaInsets();
    return (
        <View style={[styles.bar, { paddingBottom: Math.max(10, insets.bottom) }]}>
            {tabs.map((tab) => (
                <Pressable
                    accessibilityRole="tab"
                    accessibilityState={{ selected: active === tab.route }}
                    key={tab.route}
                    onPress={() => onNavigate(tab.route)}
                    style={[styles.item, active === tab.route && styles.selected]}
                >
                    <Icon name={tab.icon} width={tab.width} height={tab.height} />
                    <Text style={styles.label}>{tab.title}</Text>
                </Pressable>
            ))}
        </View>
    );
}
const styles = StyleSheet.create({
    bar: {
        flexDirection: "row",
        gap: 10,
        paddingHorizontal: 8,
        paddingTop: 10,
        backgroundColor: colors.white,
        borderTopWidth: 1,
        borderTopColor: colors.border
    },
    item: { flex: 1, height: 60, justifyContent: "center", alignItems: "center", gap: 4, borderRadius: 30 },
    selected: { backgroundColor: colors.selected },
    label: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 17.4, letterSpacing: -0.24 }
});
