import { Image } from "expo-image";
import { router } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { Text } from "./ui";
import { assets } from "@/modules/assets";
import { colors, fonts } from "@/modules/theme";
import { formatDate } from "@/modules/userData";
import type { SavedContent } from "@/types/content";

export function openContent(id: string) {
    router.push({ pathname: "/library/[id]", params: { id } });
}
export default function ContentCard({
    item,
    compact = false,
    index = 0,
    restore,
    recent = false
}: {
    item: SavedContent;
    compact?: boolean;
    index?: number;
    restore?: () => void;
    recent?: boolean;
}) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        if (!compact) return;
        const timer = setInterval(() => setNow(Date.now()), 60_000);
        return () => clearInterval(timer);
    }, [compact]);
    const minutes = Math.max(0, Math.floor((now - Date.parse(item.savedAt)) / 60_000));
    const elapsed =
        minutes < 1
            ? "방금 저장"
            : minutes < 60
              ? `${minutes}분 전 저장`
              : minutes < 1440
                ? `${Math.floor(minutes / 60)}시간 전 저장`
                : `${Math.floor(minutes / 1440)}일 전 저장`;
    const relativeDate = item.id === "cafe-1" ? "15분 전 저장" : item.id === "cafe-2" ? "12시간 전 저장" : elapsed;
    const Card = restore ? View : Pressable;
    return (
        <Card
            accessibilityRole={restore ? undefined : "button"}
            onPress={restore ? undefined : () => openContent(item.id)}
            style={[styles.card, compact && styles.compact]}
        >
            {item.image && (
                <Image
                    source={assets[compact && item.image === "cafeArchive" ? "cafeHome" : item.image]}
                    contentFit="cover"
                    contentPosition={item.image === "pillow" ? { top: "78.607%" } : "center"}
                    style={[styles.image, compact && styles.compactImage]}
                />
            )}
            <Text numberOfLines={1} style={[styles.title, compact && { marginTop: 8 }]}>
                {compact && item.id.startsWith("cafe-") ? (index === 0 ? "브루다 커피" : "무슨 커피") : item.title}
            </Text>
            <View style={styles.metadata}>
                <Text style={styles.date}>
                    {compact ? relativeDate : `${formatDate(item.savedAt)} ${recent ? "조회함" : "저장됨"}`}
                </Text>
                {restore && (
                    <Pressable onPress={restore} accessibilityRole="button" hitSlop={8}>
                        <Text style={{ color: colors.placeholder, fontSize: 12 }}>복구하기</Text>
                    </Pressable>
                )}
            </View>
        </Card>
    );
}
const styles = StyleSheet.create({
    card: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 16, backgroundColor: colors.surface },
    image: { width: "100%", height: 111, borderRadius: 3 },
    title: { fontFamily: fonts.semibold, fontSize: 15, lineHeight: 28, color: "#4C423C", marginTop: 4 },
    metadata: { marginTop: 4, flexDirection: "row", justifyContent: "space-between", gap: 8 },
    date: { fontSize: 11, lineHeight: 13, color: colors.date },
    compact: { flex: 1, minWidth: 0, height: 204, padding: 16 },
    compactImage: { height: 111 }
});
