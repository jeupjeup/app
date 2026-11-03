import { Image } from "expo-image";
import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Button, Icon, Screen, Text } from "@/components/ui";
import { assets } from "@/modules/assets";
import { fonts } from "@/modules/theme";
import { useUserData } from "@/modules/userData";

// 184:3208, 184:3301, 184:3337 — 0-01 / 온보딩
export default function Page() {
    const [step, setStep] = useState(0);
    const { guide } = useLocalSearchParams<{ guide?: string; }>();
    const { update } = useUserData();
    const illustrations = [assets.onboarding1, assets.onboarding2, assets.onboarding3];
    const dimensions = [
        { "width": 340, "height": 269 },
        { "width": 317, "height": 292 },
        { "width": 302, "height": 311 }
    ];
    const next = () => {
        if (step < 2) setStep(step + 1);
        else if (guide) router.back();
        else {
            update({ "onboarded": true });
            router.replace("/login/choose");
        }
    };

    return <Screen line={false} style={styles.page}>
        <View style={styles.dots}>
            <Icon name={(["dots1", "dots2", "dots3"] as const)[step]} width={57} height={12} />
        </View>
        <Image
            source={illustrations[step]}
            contentFit="contain"
            style={[dimensions[step], { "maxWidth": "100%", "alignSelf": "center" }]}
        />
        <View style={styles.bottom}>
            <Text style={styles.copy}>
                {step === 0 ? (
                    <>
                        원하는 모든것을{"\n"}
                        <Text style={styles.bold}>‘줍줍’</Text> 하세요.
                    </>
                ) : step === 1 ? (
                    <>
                        <Text style={styles.bold}>컬렉션</Text>을 선택해{"\n"}
                        정보를 정리해요!
                    </>
                ) : (
                    <>
                        필요할 때마다{"\n"}
                        <Text style={styles.bold}>꺼내보면</Text> 끝!
                    </>
                )}
            </Text>
            <SafeAreaView edges={["bottom"]}>
                <Button onPress={next} style={{ "height": 52 }} textStyle={{ "fontSize": 18 }}>
                    {step === 2 ? "시작하기" : "다음"}
                </Button>
            </SafeAreaView>
        </View>
    </Screen>;
}

const styles = StyleSheet.create({
    "page": {
        "paddingHorizontal": 16,
        "paddingBottom": 16,
        "justifyContent": "space-between",
        "minHeight": 730,
        "gap": 20
    },
    "dots": {
        "alignItems": "center",
        "paddingTop": 77
    },
    "bottom": {
        "gap": 44,
        "paddingBottom": 24
    },
    "copy": {
        "fontFamily": fonts.display,
        "fontSize": 32,
        "lineHeight": 46.4,
        "letterSpacing": -0.24,
        "textAlign": "center",
        "minHeight": 141,
        "paddingTop": 23,
        "color": "#000000"
    },
    "bold": {
        "fontFamily": fonts.displayBold,
        "fontSize": 32,
        "lineHeight": 46.4,
        "color": "#000000"
    }
});
