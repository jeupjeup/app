import { Image } from "expo-image";
import { router } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, TextInput, View } from "react-native";
import { Button, Icon, Screen, Text, ui } from "@/components/ui";
import { assets } from "@/modules/assets";
import { colors, fonts } from "@/modules/theme";
import { useUserData } from "@/modules/userData";

// 135:188 — local UI preview; no authentication endpoint was supplied.
export default function Page() {
    const { update, previewPasswordRef } = useUserData();
    const [id, setId] = useState("");
    const [password, setPassword] = useState("");
    const login = () => {
        if (!id.trim() || !password) return;
        previewPasswordRef.current = password;
        update({ "email": id.trim() });
        router.replace({ "pathname": "/login/signup", "params": { "returning": "1" } });
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
            <Button onPress={login} style={{ "height": 58, "borderRadius": 4 }}>
                로그인
            </Button>
        </View>
        <View style={styles.line} />
        <Text style={[styles.caption, { "textAlign": "center", "marginTop": 56 }]}>SNS로 10초만에 회원가입</Text>
        <View style={styles.social}>
            {(["kakao", "naver", "google"] as const).map((name) => (
                <Pressable
                    key={name}
                    accessibilityRole="button"
                    accessibilityLabel={`${name} 회원가입 화면`}
                    onPress={() => router.push("/login/signup")}
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
