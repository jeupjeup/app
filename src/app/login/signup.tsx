import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Button, Icon, Screen, Text, ui } from "@/components/ui";
import { colors } from "@/modules/theme";
import { useUserData } from "@/modules/userData";

// 135:262 → 241:5974 → 241:6015 → 241:6209; returning: 241:6354 / 241:6483.
export default function Page() {
    const { returning } = useLocalSearchParams<{ returning?: string; }>();
    const { data, register, busy } = useUserData();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [nickname, setNickname] = useState(returning ? data.nickname : "");
    const [required, setRequired] = useState(false);
    const [optional, setOptional] = useState(false);
    const [showTerms, setShowTerms] = useState(!!returning);
    const all = required && optional;
    const finish = async () => {
        if (!showTerms) {
            if (nickname.trim()) setShowTerms(true);

            return;
        }
        if (!required || !nickname.trim()) return;
        if (await register({ email: email.trim(), password, nickname: nickname.trim(), requiredConsent: required, notificationsEnabled: optional })) router.replace("/home");
    };
    const agreement = (title: string, checked: boolean, onPress: () => void, top = false) => (
        <Pressable
            accessibilityRole="checkbox"
            accessibilityState={{ checked }}
            onPress={onPress}
            style={[styles.agreement, top && styles.agreementTop]}
        >
            <Text>{title}</Text>
            <View style={[styles.check, checked && { "backgroundColor": colors.primary }]}>
                <Icon name="check" width={14} height={10.3282} />
            </View>
        </Pressable>
    );

    return <Screen line={false} style={styles.page}>
        <Text style={[ui.title, { "marginTop": 44 }]}>
            {returning ? (
                <>
                    <Text style={styles.highlight}>{data.nickname}</Text>님{"\n"}다시 돌아오신 것을 환영합니다!
                </>
            ) : (
                <>
                    나만의{"\n"}
                    <Text style={styles.highlight}>닉네임</Text>을 설정해볼까요?
                </>
            )}
        </Text>
        {!returning && (
            <View style={styles.nickname}>
                <TextInput accessibilityLabel="가입 이메일" keyboardType="email-address" autoCapitalize="none" autoCorrect={false} placeholder="이메일" value={email} onChangeText={setEmail} style={[ui.input, { marginBottom: 12 }]} />
                <TextInput accessibilityLabel="가입 비밀번호" secureTextEntry autoCapitalize="none" autoCorrect={false} placeholder="비밀번호 (영문·숫자·특수문자 8~20자)" value={password} onChangeText={setPassword} style={[ui.input, { marginBottom: 12 }]} />
                <Text style={{ "marginBottom": 14 }}>닉네임</Text>
                <TextInput
                    accessibilityLabel="닉네임"
                    placeholder="이름을 입력해주세요"
                    placeholderTextColor={colors.placeholder}
                    maxLength={25}
                    value={nickname}
                    onChangeText={(value) => {
                        setNickname(value);
                        if (!value.trim()) setShowTerms(false);
                    }}
                    onBlur={() => {
                        if (nickname.trim()) setShowTerms(true);
                    }}
                    onSubmitEditing={() => {
                        if (nickname.trim()) setShowTerms(true);
                    }}
                    style={ui.input}
                />
                <Text style={styles.count}>
                    <Text style={{ "color": colors.primary, "fontSize": 12 }}>{nickname.length}</Text>/25
                </Text>
            </View>
        )}
        {showTerms && (
            <View style={{ "marginTop": returning ? 48 : 30 }}>
                <Text style={[ui.subtitle, { "marginBottom": 22, "paddingLeft": 10 }]}>이용 약관에 동의해주세요</Text>
                {agreement(
                    "전체 동의하기",
                    all,
                    () => {
                        setRequired(!all);
                        setOptional(!all);
                    },
                    true
                )}
                <View
                    style={{ "paddingTop": 10, "borderBottomWidth": 1, "borderColor": colors.divider, "paddingBottom": 8 }}
                >
                    {agreement("(필수) 개인정보 이용 동의", required, () => setRequired(!required))}
                    {agreement("(선택) 알림 수신 동의", optional, () => setOptional(!optional))}
                </View>
            </View>
        )}
        <View style={{ "flex": 1, "minHeight": 60 }} />
        <SafeAreaView edges={["bottom"]} style={{ "paddingBottom": showTerms ? 40 : 28 }}>
            <Button
                onPress={finish}
                disabled={busy || !email.trim() || !password || !nickname.trim() || (showTerms && !required)}
                style={{ "height": showTerms ? 46 : 58 }}
            >
                시작하기
            </Button>
        </SafeAreaView>
    </Screen>;
}

const styles = StyleSheet.create({
    "page": {
        "paddingHorizontal": 16
    },
    "highlight": {
        ...ui.title,
        "color": colors.primary
    },
    "nickname": {
        "marginTop": 44
    },
    "count": {
        "textAlign": "right",
        "fontSize": 12,
        "color": "#9CA3AF",
        "marginTop": 10
    },
    "agreement": {
        "flexDirection": "row",
        "alignItems": "center",
        "justifyContent": "space-between",
        "paddingHorizontal": 10,
        "minHeight": 44
    },
    "agreementTop": {
        "height": 65,
        "borderTopWidth": 1,
        "borderBottomWidth": 1,
        "borderColor": colors.divider
    },
    "check": {
        "width": 20,
        "height": 20,
        "backgroundColor": "#D1D1D1",
        "justifyContent": "center",
        "alignItems": "center"
    }
});
