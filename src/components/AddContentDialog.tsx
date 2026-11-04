import { router } from "expo-router";
import { useState } from "react";
import { StyleSheet, TextInput } from "react-native";
import { Button, Dialog, Text } from "@/components/ui";
import { colors, fonts } from "@/modules/theme";
import { useUserData } from "@/modules/userData";

// A save succeeds only after the server has persisted the URL.
type Props = {
    visible: boolean;
    onClose: () => void;
    initialUrl?: string;
};

export default function AddContentDialog(props: Props) {
    const { visible, onClose, initialUrl = "" } = props;
    const { createContent, busy: apiBusy } = useUserData();
    const [url, setUrl] = useState(initialUrl);
    const [memo, setMemo] = useState("");
    const [result, setResult] = useState<"saved" | null>(null);
    const [busy, setBusy] = useState(false);
    const [savedId, setSavedId] = useState("");
    let valid = false;
    try {
        const parsed = new URL(url.trim());
        valid = ["http:", "https:"].includes(parsed.protocol) && !!parsed.hostname;
    } catch {
        /* The design keeps the add button disabled for invalid URLs. */
    }
    const close = () => {
        setResult(null);
        setUrl("");
        setMemo("");
        onClose();
    };
    const save = async () => {
        if (!valid || busy) return;
        setBusy(true);
        try {
            const item = await createContent(url.trim(), memo);
            if (item) { setSavedId(item.id); setResult("saved"); }
        } finally { setBusy(false); }
    };

    return <Dialog
        visible={visible}
        onClose={close}
        width={250}
        close={!result || result === "saved"}
        style={{ "padding": 16, "gap": 0 }}
    >
        {result ? (
            <>
                <Text style={styles.heading}>
                    정보를 주웠어요.
                </Text>
                <Button onPress={() => { close(); router.push({ pathname: "/library/[id]", params: { id: savedId } }); }} style={styles.details} textStyle={{ color: colors.placeholder, fontSize: 12 }}>상세보기</Button>
            </>
        ) : (
            <>
                <Text style={[styles.heading, { "marginBottom": 20 }]}>정보의 링크를 입력해주세요</Text>
                <TextInput
                    accessibilityLabel="URL 입력"
                    value={url}
                    onChangeText={setUrl}
                    placeholder="URL 입력"
                    placeholderTextColor={colors.placeholder}
                    autoCapitalize="none"
                    autoCorrect={false}
                    keyboardType="url"
                    style={styles.url}
                    multiline
                />
                <TextInput
                    accessibilityLabel="정보 메모"
                    value={memo}
                    onChangeText={setMemo}
                    maxLength={70}
                    placeholder="(선택) 정보의 쓰임새나 간단한 메모를 입력해주세요."
                    placeholderTextColor={colors.placeholder}
                    style={styles.memo}
                    multiline
                />
                <Text style={styles.count}>
                    <Text style={{ "color": colors.primary, "fontSize": 12 }}>{memo.length}</Text>/70
                </Text>
                <Button
                    onPress={() => {
                        void save();
                    }}
                    disabled={!valid || busy || apiBusy}
                    style={{ "marginTop": 2 }}
                >
                    추가
                </Button>
            </>
        )}
    </Dialog>;
}

const styles = StyleSheet.create({
    "heading": {
        "fontFamily": fonts.semibold,
        "fontSize": 14,
        "lineHeight": 20,
        "textAlign": "center",
        "marginTop": 8
    },
    "url": {
        "borderWidth": 1,
        "borderColor": colors.border,
        "borderRadius": 6,
        "padding": 10,
        "minHeight": 50,
        "maxHeight": 70,
        "fontSize": 12,
        "fontFamily": fonts.regular,
        "textAlign": "center",
        "color": colors.text,
        "backgroundColor": colors.surface
    },
    "memo": {
        "borderWidth": 1,
        "borderColor": colors.border,
        "borderRadius": 6,
        "padding": 10,
        "height": 92,
        "fontSize": 12,
        "fontFamily": fonts.regular,
        "textAlignVertical": "top",
        "marginTop": 20,
        "color": colors.text,
        "backgroundColor": colors.surface
    },
    "count": {
        "textAlign": "right",
        "color": "#9CA3AF",
        "fontSize": 12,
        "marginTop": 5
    },
    "details": {
        "backgroundColor": "transparent",
        "borderWidth": 1,
        "borderColor": colors.border,
        "minHeight": 24,
        "paddingVertical": 2,
        "marginTop": 14,
        "marginBottom": 12,
        "alignSelf": "center",
        "width": 118
    },
    "message": {
        "fontSize": 10,
        "color": colors.muted,
        "textAlign": "center",
        "marginTop": 6,
        "marginBottom": 16
    }
});
