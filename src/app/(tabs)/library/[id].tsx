import { Image } from "expo-image";
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { Linking, Pressable, Share, StyleSheet, TextInput, View } from "react-native";
import { Button, Dialog, Header, Icon, Screen, Text } from "@/components/ui";
import { collections } from "@/components/CollectionGrid";
import { openContent } from "@/components/ContentCard";
import { assets } from "@/modules/assets";
import { colors, fonts } from "@/modules/theme";
import { formatDate, useUserData } from "@/modules/userData";
import type { ContentStatus } from "@/types/content";

// D-01: ready, analyzing, failed and unavailable states; deletion dialogs 293:2373 / 293:2381.
export default function Page() {
    const { id, status } = useLocalSearchParams<{ id: string; status?: ContentStatus; }>();
    const { data, command, remove, busy, error } = useUserData();
    const [editing, setEditing] = useState(false);
    const [editTitle, setEditTitle] = useState("");
    const [editMemo, setEditMemo] = useState("");
    const [editCollection, setEditCollection] = useState<string | null>(null);
    const [editType, setEditType] = useState("기타");
    const [confirm, setConfirm] = useState(false);
    const [deleted, setDeleted] = useState(false);
    const [linkFailed, setLinkFailed] = useState(false);
    const item = data.contents.find((content) => content.id === id);

    useEffect(() => {
        if (id && !item?.deletedAt) void command(`/contents/${encodeURIComponent(id)}/view`, "POST", {});
    }, [id, item?.deletedAt, command]);

    if (!item)
        return <Screen>
            <Header />
            <Text style={{ padding: 16 }}>콘텐츠를 찾을 수 없습니다. 목록을 새로고침해주세요.</Text>
        </Screen>;
    const state = linkFailed ? "unavailable" : ((__DEV__ && process.env.EXPO_PUBLIC_ENABLE_PREVIEW === "1" ? status : undefined) ?? item.status);
    const finishDeletion = () => {
        setDeleted(false);
        if (router.canGoBack()) router.back();
        else router.replace("/library");
    };
    const field = (title: string, children: React.ReactNode) => (
        <View style={styles.field}>
            <Text style={styles.label}>{title}</Text>
            {typeof children === "string" ? <Text style={styles.value}>{children}</Text> : children}
        </View>
    );
    const openOriginal = async () => {
        try {
            await Linking.openURL(item.url);
        } catch {
            setLinkFailed(true);
        }
    };

    return <>
        <Screen style={{ "paddingBottom": 20 }}>
            <Header />
            <View style={{ "paddingHorizontal": 16, "gap": 20 }}>
                <View style={styles.card}>
                    {state === "unavailable" ? (
                        <View style={styles.unavailable}>
                            <Icon name="unavailable" width={42} />
                            <Text style={{ "color": colors.white, "fontSize": 12 }}>
                                원본 콘텐츠를 확인할 수 없어요.
                            </Text>
                        </View>
                    ) : item.image ? (
                        <Image
                            source={assets[item.image === "cafeArchive" ? "cafeDetail" : item.image]}
                            contentFit="cover"
                            style={styles.image}
                        />
                    ) : (
                        <View style={styles.image} />
                    )}
                    <Text style={styles.title}>{item.title}</Text>
                    <View style={styles.metadata}>
                        <Text style={{ "fontSize": 10, "color": colors.muted }}>{formatDate(item.savedAt)} 저장됨</Text>
                        <Pressable
                            accessibilityRole="button"
                            onPress={() => {
                                void Share.share({ "message": item.url, "url": item.url, "title": item.title });
                            }}
                            style={{ "flexDirection": "row", "gap": 4, "alignItems": "center" }}
                        >
                            <Icon name="share" width={23} height={13} />
                            <Text style={{ "color": colors.muted, "fontSize": 12 }}>공유하기</Text>
                        </Pressable>
                    </View>
                    {state === "analyzing" || state === "failed" ? (
                        <View style={styles.status}>
                            <Icon name={state === "analyzing" ? "analyzing" : "analysisFailed"} width={42} />
                            <Text style={{ "fontSize": 13, "textAlign": "center", "lineHeight": 19 }}>
                                {state === "analyzing"
                                    ? "콘텐츠를 저장했어요.\n내용을 분석하고 있으니 잠시만 기다려주세요."
                                    : "콘텐츠는 저장되었지만 내용분석에 실패했어요.\n다시 한번 저장을 시도해주세요."}
                            </Text>
                        </View>
                    ) : (
                        <>
                            {field("설명", item.description || "자동 분석은 아직 제공되지 않습니다.")}
                            {field("태그", item.tags.map((tag) => `#${tag}`).join(" "))}
                            {field("유형", item.type)}
                            {field("출처", item.source)}
                            {field("포함된 컬렉션", item.collection ?? "")}
                            {field(
                                "저장된 링크",
                                state === "unavailable" ? (
                                    <Text style={{ "color": colors.placeholder, "fontSize": 12 }}>접근 불가능</Text>
                                ) : (
                                    <Pressable
                                        accessibilityRole="link"
                                        onPress={() => {
                                            void openOriginal();
                                        }}
                                    >
                                        <Text
                                            style={{
                                                "color": colors.primary,
                                                "textDecorationLine": "underline",
                                                "fontSize": 12
                                            }}
                                        >
                                            바로가기
                                        </Text>
                                    </Pressable>
                                )
                            )}
                            {__DEV__ && process.env.EXPO_PUBLIC_ENABLE_PREVIEW === "1" && item.id.startsWith("cafe-") && (
                                <View style={styles.field}>
                                    <Text style={styles.label}>관련된 콘텐츠</Text>
                                    {[
                                        {
                                            "name": "브루다 커피 종로3가점",
                                            "image": "relatedCafe" as const,
                                            "id": "cafe-2"
                                        },
                                        {
                                            "name": "브루다 커피 종각역점 내부 이미지",
                                            "image": "relatedInterior" as const,
                                            "id": "cafe-3"
                                        }
                                    ].map((related) => (
                                        <Pressable
                                            key={related.id}
                                            accessibilityRole="button"
                                            style={styles.related}
                                            onPress={() => openContent(related.id)}
                                        >
                                            <Image
                                                source={assets[related.image]}
                                                contentFit="cover"
                                                style={{ "width": 43, "height": 43 }}
                                            />
                                            <Text style={{ "flex": 1, "fontSize": 12 }}>{related.name}</Text>
                                            <Icon name="detailChevron" width={8} height={14} />
                                        </Pressable>
                                    ))}
                                </View>
                            )}
                        </>
                    )}
                </View>
                <Button disabled={busy || !!item.deletedAt} onPress={() => {
                    setEditTitle(item.title); setEditMemo(item.memo); setEditCollection(item.collection ?? null); setEditType(item.type); setEditing(true);
                }}>정보 수정</Button>
                <Button disabled={busy || !!item.deletedAt} danger onPress={() => setConfirm(true)}>
                    정보 삭제
                </Button>
            </View>
        </Screen>
        <Dialog visible={editing} onClose={() => setEditing(false)} close>
            <Text style={{ fontSize: 16 }}>정보 수정</Text>
            {error && <Text accessibilityRole="alert" style={{ color: colors.error, fontSize: 12 }}>{error}</Text>}
            <TextInput accessibilityLabel="콘텐츠 제목" value={editTitle} onChangeText={setEditTitle} maxLength={200} style={{ borderWidth: 1, borderColor: colors.border, padding: 8 }} />
            <TextInput accessibilityLabel="콘텐츠 메모" value={editMemo} onChangeText={setEditMemo} maxLength={70} multiline placeholder="메모" style={{ borderWidth: 1, borderColor: colors.border, padding: 8 }} />
            <Text>유형</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                {["영상", "이미지", "텍스트", "기타"].map(value => <Pressable key={value} onPress={() => setEditType(value)} accessibilityRole="radio" accessibilityState={{ checked: editType === value }} style={{ padding: 8, backgroundColor: editType === value ? colors.primary : colors.soft }}><Text>{value}</Text></Pressable>)}
            </View>
            <Text>컬렉션</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                {[null, ...collections.map(c => c.name)].map(value => <Pressable key={value ?? "none"} onPress={() => setEditCollection(value)} accessibilityRole="radio" accessibilityState={{ checked: editCollection === value }} style={{ padding: 8, backgroundColor: editCollection === value ? colors.primary : colors.soft }}><Text>{value ?? "없음"}</Text></Pressable>)}
            </View>
            <Button disabled={busy || !editTitle.trim()} onPress={async () => {
                if (await command(`/contents/${encodeURIComponent(item.id)}`, "PATCH", { title: editTitle.trim(), memo: editMemo, type: editType, collection: editCollection })) setEditing(false);
            }}>저장</Button>
        </Dialog>
        <Dialog visible={confirm} onClose={() => setConfirm(false)} close>
            {error && <Text accessibilityRole="alert" style={{ color: colors.error, fontSize: 12 }}>{error}</Text>}
            <Text style={{ "textAlign": "center", "fontSize": 16 }}>이 정보를 삭제하시겠습니까?</Text>
            <Button
                danger
                disabled={busy}
                onPress={async () => {
                    if (await remove(item.id)) { setConfirm(false); setDeleted(true); }
                }}
            >
                삭제
            </Button>
        </Dialog>
        <Dialog visible={deleted} width={250} onClose={finishDeletion}>
            <Text style={{ "textAlign": "center", "fontFamily": fonts.semibold }}>삭제되었습니다.</Text>
            <Text style={{ "fontSize": 10, "color": colors.placeholder, "textAlign": "center" }}>
                삭제된 정보는 30일 간 휴지통에 보관됩니다.
            </Text>
        </Dialog>
    </>;
}

const styles = StyleSheet.create({
    "card": {
        "borderWidth": 1,
        "borderColor": colors.border,
        "borderRadius": 8,
        "padding": 16,
        "backgroundColor": colors.surface
    },
    "image": {
        "height": 264,
        "width": "100%",
        "borderRadius": 3,
        "backgroundColor": "#EAEAEA"
    },
    "title": {
        "marginTop": 16,
        "fontSize": 24,
        "lineHeight": 35,
        "fontFamily": fonts.semibold
    },
    "metadata": {
        "flexDirection": "row",
        "justifyContent": "space-between",
        "marginTop": 16,
        "paddingBottom": 16,
        "alignItems": "center"
    },
    "field": {
        "borderTopWidth": 1,
        "borderTopColor": colors.divider,
        "paddingTop": 16,
        "marginTop": 0,
        "paddingBottom": 16,
        "gap": 8
    },
    "label": {
        "fontFamily": fonts.semibold,
        "fontSize": 14,
        "lineHeight": 20
    },
    "value": {
        "fontSize": 12,
        "lineHeight": 18
    },
    "related": {
        "flexDirection": "row",
        "alignItems": "center",
        "gap": 10,
        "marginTop": 8
    },
    "status": {
        "borderTopWidth": 1,
        "borderTopColor": colors.divider,
        "minHeight": 176,
        "justifyContent": "center",
        "alignItems": "center",
        "gap": 20
    },
    "unavailable": {
        "height": 248,
        "borderRadius": 3,
        "backgroundColor": colors.border,
        "justifyContent": "center",
        "alignItems": "center",
        "gap": 20
    }
});
