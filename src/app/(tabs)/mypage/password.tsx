import { router } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, TextInput, View } from "react-native";
import { Button, Header, Icon, Screen, Text } from "@/components/ui";
import { colors, fonts } from "@/modules/theme";
import { useUserData } from "@/modules/userData";

// 294:2662, 345:1358, 345:1432, 268:2305, 292:1584.
// Verification and lockout are enforced by the server.
export default function Page() {
    const { verifyPassword, changePassword, busy } = useUserData();
    const [current, setCurrent] = useState("");
    const [next, setNext] = useState("");
    const [confirmation, setConfirmation] = useState("");
    const [verified, setVerified] = useState(false);
    const [attempted, setAttempted] = useState(false);
    const [visible, setVisible] = useState([false, false, false]);
    const valid = /^(?=.*[A-Za-z])(?=.*\d)(?=.*[!@#$%^&*<>])[A-Za-z\d!@#$%^&*<>]{8,20}$/.test(next);
    const canChange = verified && valid && next === confirmation && !busy;
    const verify = async () => {
        if (!current || busy) return;
        const matches = await verifyPassword(current);
        setVerified(matches);
        setAttempted(true);
    };
    const field = (
        index: number,
        title: string,
        value: string,
        onChange: (text: string) => void,
        placeholder: string,
        message?: string,
        success = false
    ) => (
        <View style={[styles.field, { "minHeight": index === 0 ? 185 : index === 1 ? 145 : 125 }]}>
            <Text style={styles.label}>{title}</Text>
            <View style={styles.inputRow}>
                <TextInput
                    accessibilityLabel={title}
                    value={value}
                    onChangeText={onChange}
                    placeholder={placeholder}
                    placeholderTextColor={colors.placeholder}
                    autoCapitalize="none"
                    autoCorrect={false}
                    secureTextEntry={!visible[index]}
                    editable={!busy}
                    onBlur={index === 0 ? verify : undefined}
                    style={styles.input}
                />
                <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${title} ${visible[index] ? "숨기기" : "표시"}`}
                    onPress={() => setVisible((previous) => previous.map((v, i) => (i === index ? !v : v)))}
                    hitSlop={10}
                >
                    <Icon name={visible[index] ? "eye" : "eyeOff"} width={16} height={16} />
                </Pressable>
            </View>
            {!!message && <Text style={[styles.message, success && { "color": colors.success }]}>{message}</Text>}
        </View>
    );

    return <Screen>
        <Header title="비밀번호 재설정" />
        {field(
            0,
            "기존 비밀번호",
            current,
            (v) => {
                setCurrent(v);
                setVerified(false);
                setAttempted(false);
            },
            "영문,숫자,특수문자 8~20자",
            verified
                    ? "비밀번호 인증이 완료되었습니다."
                    : attempted
                        ? "비밀번호가 틀렸습니다"
                        : "기존 비밀번호 입력 오류 횟수(5회)를 초과 시 24시간 동안 재설정이 제한됩니다.",
            verified
        )}
        {field(
            1,
            "신규 비밀번호",
            next,
            setNext,
            "영문,숫자,특수문자 8~20자",
            next && !valid ? "영문,숫자,특수문자(! @ # $ % ^ & * < >)포함 8~20자" : undefined
        )}
        {field(
            2,
            "신규 비밀번호 확인",
            confirmation,
            setConfirmation,
            "비밀번호를 한 번 더 입력하세요",
            confirmation && next !== confirmation ? "비밀번호가 틀렸습니다" : undefined
        )}
        <View style={{ "paddingHorizontal": 32, "paddingTop": 30 }}>
            <Button
                disabled={!canChange}
                onPress={async () => {
                    if (canChange && await changePassword(current, next)) router.back();
                }}
                style={[
                    { "height": 45, "minHeight": 45, "borderRadius": 10 },
                    !canChange && { "backgroundColor": "#D1D1D1" }
                ]}
            >
                비밀번호 변경하기
            </Button>
        </View>
    </Screen>;
}

const styles = StyleSheet.create({
    "field": {
        "minHeight": 165,
        "paddingHorizontal": 32,
        "paddingTop": 12,
        "gap": 14
    },
    "label": {
        "fontFamily": fonts.medium,
        "fontSize": 16,
        "lineHeight": 20
    },
    "inputRow": {
        "flexDirection": "row",
        "alignItems": "center",
        "height": 41,
        "gap": 8,
        "borderRadius": 99,
        "borderWidth": 1,
        "borderColor": "#D9D9D9",
        "backgroundColor": colors.white,
        "paddingHorizontal": 16
    },
    "input": {
        "flex": 1,
        "minWidth": 0,
        "height": "100%",
        "padding": 0,
        "fontFamily": fonts.regular,
        "fontSize": 14,
        "color": colors.text
    },
    "message": {
        "paddingHorizontal": 16,
        "fontSize": 10,
        "lineHeight": 13,
        "color": colors.error
    }
});
