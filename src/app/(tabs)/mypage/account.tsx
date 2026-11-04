import { router } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, TextInput, View } from "react-native";
import { Button, Dialog, Header, Icon, Screen, Text, ui } from "@/components/ui";
import { ProfileRow, ServiceRow } from "@/components/ProfileRow";
import { colors, fonts } from "@/modules/theme";
import { useUserData } from "@/modules/userData";

// 195:1059; nickname/logout/withdraw overlays: 261:2036, 261:2098, 257:1797.
export default function Page() {
    const { data, changeNickname, logout: endSession, busy } = useUserData();
    const [dialog, setDialog] = useState<"nickname" | "logout" | "withdraw" | null>(null);
    const [nickname, setNickname] = useState(data.nickname);
    const logout = async () => {
        if (await endSession()) { setDialog(null); router.replace("/login"); }
    };

    return <>
        <Screen>
            <Header title="상세정보" back={false} />
            <ProfileRow detail />
            <Text style={[ui.subtitle, { "paddingHorizontal": 16, "marginTop": 20, "marginBottom": 14 }]}>
                서비스 관리
            </Text>
            <ServiceRow
                icon="id"
                title="아이디"
                trailing={
                    <View style={{ "alignItems": "flex-end" }}>
                        <Text style={{ "fontSize": 14, "color": colors.muted }}>{data.email}</Text>
                        <Text style={{ "fontSize": 12, "color": colors.muted }}>이메일로 로그인중</Text>
                    </View>
                }
            />
            <ServiceRow
                icon="nickname"
                title="닉네임 변경"
                onPress={() => {
                    setNickname(data.nickname);
                    setDialog("nickname");
                }}
            />
            <ServiceRow icon="password" title="비밀번호 재설정" onPress={() => router.push("/mypage/password")} />
            <ServiceRow icon="door" title="계정 로그아웃" onPress={() => setDialog("logout")} />
            <View style={{ "flex": 1, "minHeight": 100 }} />
            <Pressable
                accessibilityRole="button"
                onPress={() => setDialog("withdraw")}
                style={{ "padding": 16, "alignItems": "center" }}
            >
                <Text style={{ "color": colors.muted, "fontSize": 12 }}>계정 탈퇴</Text>
            </Pressable>
        </Screen>
        <Dialog visible={!!dialog} onClose={() => setDialog(null)}>
            {dialog === "nickname" ? (
                <>
                    <Text style={styles.message}>새로운 닉네임을 입력해주세요</Text>
                    <TextInput
                        accessibilityLabel="새로운 닉네임"
                        value={nickname}
                        onChangeText={setNickname}
                        maxLength={25}
                        style={[
                            ui.input,
                            { "borderRadius": 99, "height": 40, "borderColor": "#D9D9D9", "backgroundColor": colors.white }
                        ]}
                    />
                    <Button
                        disabled={busy || !nickname.trim()}
                        onPress={async () => { if (await changeNickname(nickname.trim())) setDialog(null); }}
                        style={{ "minHeight": 36, "borderRadius": 10, "paddingVertical": 5 }}
                    >
                        완료
                    </Button>
                </>
            ) : (
                <>
                    <View style={{ "alignItems": "center", "paddingTop": 6 }}>
                        <Icon name={dialog === "withdraw" ? "siren" : "logout"} width={36} height={36} />
                    </View>
                    <Text style={styles.message}>
                        {dialog === "withdraw"
                            ? "탈퇴하실시, 계정은 삭제되며\n복구되지않습니다."
                            : "로그아웃 하시겠습니까?"}
                    </Text>
                    <Button
                        danger={dialog === "withdraw"}
                        disabled={busy}
                        onPress={async () => {
                            if (dialog === "withdraw") {
                                if (await endSession(true)) { setDialog(null); router.replace("/login/choose"); }
                            } else await logout();
                        }}
                        style={{
                            "minHeight": 36,
                            "borderRadius": 10,
                            "paddingVertical": 5,
                            "width": 182,
                            "alignSelf": "center"
                        }}
                    >
                        {dialog === "withdraw" ? "계정 탈퇴" : "계정 로그아웃"}
                    </Button>
                </>
            )}
        </Dialog>
    </>;
}

const styles = StyleSheet.create({
    "message": {
        "fontSize": 16,
        "lineHeight": 22,
        "textAlign": "center",
        "fontFamily": fonts.regular
    }
});
