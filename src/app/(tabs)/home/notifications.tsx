import { Pressable, StyleSheet, View } from "react-native";
import { useState } from "react";
import { openCollection } from "@/components/CollectionGrid";
import AddContentDialog from "@/components/AddContentDialog";
import { EmptyState, Header, Icon, Screen, Text } from "@/components/ui";
import { colors, fonts } from "@/modules/theme";
import { useUserData } from "@/modules/userData";

// H-02: 165:1997, 184:2696, 165:1945.
export default function Page() {
    const { data, command, busy } = useUserData();
    const [add, setAdd] = useState(false);

    return <>
        <Screen>
            <Header title="알림" />
            <View style={{ "paddingHorizontal": 16, "flex": 1 }}>
                {data.notices.length ? (
                    <>
                        <Pressable
                            accessibilityRole="button"
                            disabled={busy}
                            onPress={() => { void command("/notices/read", "POST", {}); }}
                            style={{ "alignSelf": "flex-end", "marginBottom": 20 }}
                        >
                            <Text style={{ "fontSize": 12, "color": colors.primary }}>모두 읽음</Text>
                        </Pressable>
                        <View style={{ "gap": 20 }}>
                            {data.notices.map((notice) => (
                                <Pressable
                                    key={notice.id}
                                    accessibilityRole="button"
                                    disabled={busy}
                                    onPress={async () => {
                                        if (!await command(`/notices/${encodeURIComponent(notice.id)}/read`, "POST", {})) return;
                                        if (notice.error) setAdd(true);
                                        else openCollection(notice.collection);
                                    }}
                                    style={[styles.notice, notice.read && { "opacity": 0.4 }]}
                                >
                                    <View style={{ "flexDirection": "row", "alignItems": "center", "gap": 12, "flex": 1 }}>
                                        <View
                                            style={{
                                                "width": 45,
                                                "height": 45,
                                                "alignItems": "center",
                                                "justifyContent": "center"
                                            }}
                                        >
                                            <Icon
                                                name={
                                                    notice.error
                                                        ? "noticeError"
                                                        : notice.id === "2"
                                                            ? "noticeMilestone"
                                                            : "noticeBell"
                                                }
                                                width={notice.error || notice.id === "2" ? 45 : 36}
                                                height={notice.error ? 44 : notice.id === "2" ? 45 : 36}
                                            />
                                        </View>
                                        <View style={{ "flex": 1, "gap": 4 }}>
                                            <Text style={styles.title}>{notice.title}</Text>
                                            <Text style={{ "fontSize": 12, "color": "#4C423C" }}>
                                                {notice.description}
                                            </Text>
                                        </View>
                                    </View>
                                    <Text style={styles.date}>{new Date(notice.date).toLocaleString("ko-KR")}</Text>
                                </Pressable>
                            ))}
                        </View>
                    </>
                ) : (
                    <View style={{ "flex": 1, "justifyContent": "center", "paddingBottom": 30 }}>
                        <EmptyState icon="emptyNotice" width={51} height={54} small>
                            아직 알림이 없어요
                        </EmptyState>
                    </View>
                )}
            </View>
        </Screen>
        <AddContentDialog visible={add} onClose={() => setAdd(false)} />
    </>;
}

const styles = StyleSheet.create({
    "notice": {
        "height": 90,
        "borderRadius": 8,
        "backgroundColor": colors.soft,
        "paddingHorizontal": 16,
        "paddingVertical": 16
    },
    "title": {
        "fontFamily": fonts.semibold,
        "fontSize": 14,
        "lineHeight": 20
    },
    "date": {
        "position": "absolute",
        "bottom": 12,
        "right": 16,
        "textAlign": "right",
        "fontSize": 8,
        "color": "rgba(31,25,22,0.3)"
    }
});
