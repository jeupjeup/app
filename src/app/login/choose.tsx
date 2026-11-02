import { router } from "expo-router";
import { Pressable, StyleSheet, View } from "react-native";
import { Icon, Screen, Text, ui } from "@/components/ui";
import { colors, fonts } from "@/modules/theme";

// 383:1409; pressed states 424:1309 / 424:1268.
export default function ChooseAccount() {
    return (
        <Screen line={false} style={styles.page}>
            <Text style={[ui.title, { marginTop: 44 }]}>기존에 로그인이 되어있나요?</Text>
            <View style={styles.choices}>
                <Pressable
                    accessibilityRole="button"
                    onPress={() => router.push("/login")}
                    style={({ pressed }) => [
                        styles.choice,
                        { backgroundColor: pressed ? colors.soft : colors.primary }
                    ]}
                >
                    <Icon name="login" width={40} height={40} />
                    <Text style={styles.label}>이미 계정이 있어요</Text>
                </Pressable>
                <Pressable
                    accessibilityRole="button"
                    onPress={() => router.push("/login/signup")}
                    style={({ pressed }) => [
                        styles.choice,
                        { backgroundColor: pressed ? colors.primary : colors.soft }
                    ]}
                >
                    <Icon name="signup" width={46} height={40} />
                    <Text style={styles.label}>처음 시작해봐요!</Text>
                </Pressable>
            </View>
        </Screen>
    );
}
const styles = StyleSheet.create({
    page: { paddingHorizontal: 16, paddingBottom: 40 },
    choices: { gap: 30, marginTop: 78 },
    choice: { height: 250, borderRadius: 6, justifyContent: "center", alignItems: "center", gap: 5 },
    label: { fontFamily: fonts.semibold, fontSize: 24, color: colors.white }
});
