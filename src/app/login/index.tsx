import { Image } from "expo-image";
import { router } from "expo-router";
import { useState } from "react";
import { Alert, Pressable, StyleSheet, TextInput, View } from "react-native";
import { Button, Icon, Screen, Text, ui } from "@/components/ui";
import { assets } from "@/modules/assets";
import { colors, fonts } from "@/modules/theme";
import { useUserData } from "@/modules/userData";

// Email authentication uses the API session.
export default function Page() {
    const { login: authenticate, busy } = useUserData();
    const [id, setId] = useState("");
    const [password, setPassword] = useState("");
    const login = async () => {
        if (!id.trim() || !password || busy) return;
        if (await authenticate(id.trim(), password)) router.replace("/home");
    };

    return <Screen line={false} style={styles.page}>
        <View style={styles.brand}>
            <Image source={assets.logoLogin} contentFit="contain" style={{ "width": 123, "height": 87 }} />
            <Text style={styles.caption}>원활한 서비스 이용을 위해 로그인해주세요</Text>
        </View>
        <View style={{ "gap": 12 }}>
            <TextInput
                accessibilityLabel="아이디"
                autoCapitalize="none"
                autoCorrect={false}
                value={id}
                onChangeText={setId}
                placeholder="아이디를 입력하세요."
                placeholderTextColor={colors.placeholder}
                style={styles.input}
            />
            <TextInput
                accessibilityLabel="비밀번호"
                value={password}
                onChangeText={setPassword}
                secureTextEntry
                autoCapitalize="none"
                placeholder="비밀번호를 입력하세요."
                placeholderTextColor={colors.placeholder}
                style={styles.input}
                onSubmitEditing={login}
            />
            <Button disabled={busy || !id.trim() || !password} onPress={login} style={{ "height": 58, "borderRadius": 4 }}>
                로그인
            </Button>
        </View>
        <Button onPress={() => router.push("/login/signup")} style={{ marginTop: 12 }}>이메일 회원가입</Button>
        <View style={styles.line} />
        <Text style={[styles.caption, { "textAlign": "center", "marginTop": 56 }]}>SNS로 10초만에 회원가입</Text>
        <View style={styles.social}>
            {(["kakao", "naver", "google"] as const).map((name) => (
                <Pressable
                    key={name}
                    accessibilityRole="button"
                    accessibilityLabel={`${name} 회원가입 화면`}
                    onPress={() => Alert.alert("소셜 로그인 준비 중", "소셜 인증 제공자 설정이 필요합니다. 이메일로 가입해주세요.")}
                >
                    <Icon name={name} width={58} height={58} />
                </Pressable>
            ))}
        </View>
    </Screen>;
}

const styles = StyleSheet.create({
    "page": {
        "paddingHorizontal": 16,
        "paddingTop": 74,
        "paddingBottom": 60
    },
    "brand": {
        "alignItems": "center",
        "marginBottom": 26
    },
    "caption": {
        "fontSize": 13,
        "color": "#8E6429",
        "lineHeight": 18
    },
    "input": {
        ...ui.input,
        "height": 58,
        "fontSize": 13,
        "fontFamily": fonts.regular,
        "paddingHorizontal": 20
    },
    "line": {
        "height": 1,
        "backgroundColor": "#8E6429",
        "marginTop": 48
    },
    "social": {
        "flexDirection": "row",
        "gap": 17,
        "justifyContent": "center",
        "marginTop": 20
    }
});
