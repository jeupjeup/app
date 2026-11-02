import { router } from "expo-router";
import { useState } from "react";
import { Image } from "expo-image";
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Icon, SearchField, Text } from "./ui";
import { assets } from "@/modules/assets";
import { colors } from "@/modules/theme";
import { useUserData } from "@/modules/userData";
import { openContent } from "./ContentCard";

// 293:2082 — native search input, local preview results and recent queries.
export default function SearchDialog({ visible, onClose }: { visible: boolean; onClose: () => void }) {
    const { data, update } = useUserData();
    const [query, setQuery] = useState("");
    const insets = useSafeAreaInsets();
    const matches = data.contents
        .filter(
            (item) =>
                !item.deletedAt &&
                `${item.title} ${item.description} ${item.memo} ${item.tags.join(" ")}`
                    .toLowerCase()
                    .includes(query.toLowerCase().trim())
        )
        .slice(0, 3);
    const submit = (value = query) => {
        if (!value.trim()) return;
        update((d) => ({
            ...d,
            searchHistory: [value.trim(), ...d.searchHistory.filter((q) => q !== value.trim())].slice(0, 10)
        }));
        onClose();
        router.navigate({ pathname: "/library", params: { q: value.trim(), collection: "" } });
    };
    return (
        <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
            <KeyboardAvoidingView
                style={[styles.overlay, { paddingTop: insets.top + 86 }]}
                behavior={Platform.OS === "ios" ? "padding" : undefined}
            >
                <Pressable
                    style={StyleSheet.absoluteFill}
                    accessibilityRole="button"
                    accessibilityLabel="검색 닫기"
                    onPress={onClose}
                />
                <View style={{ paddingHorizontal: 16 }}>
                    <SearchField autoFocus value={query} onChangeText={setQuery} onSubmit={() => submit()} />
                    <View style={styles.preview}>
                        <Text style={{ fontSize: 12, marginBottom: 12 }}>미리보기</Text>
                        {matches.map((item) => (
                            <Pressable
                                key={item.id}
                                style={styles.result}
                                accessibilityRole="button"
                                onPress={() => {
                                    onClose();
                                    openContent(item.id);
                                }}
                            >
                                {item.image && (
                                    <Image
                                        source={assets[item.image]}
                                        contentFit="cover"
                                        style={{ width: 28, height: 28 }}
                                    />
                                )}
                                <Text style={{ flex: 1, fontSize: 12 }} numberOfLines={1}>
                                    {item.title}
                                </Text>
                                <Icon name="profileChevron" width={8} height={14} />
                            </Pressable>
                        ))}
                        <Pressable
                            onPress={() => update({ searchHistory: [] })}
                            accessibilityRole="button"
                            style={{ alignSelf: "flex-end", paddingVertical: 12 }}
                        >
                            <Text style={{ fontSize: 10 }}>전체 삭제</Text>
                        </Pressable>
                        <ScrollView
                            horizontal
                            showsHorizontalScrollIndicator={false}
                            contentContainerStyle={{ gap: 10 }}
                        >
                            {data.searchHistory.map((value) => (
                                <Pressable
                                    key={value}
                                    accessibilityRole="button"
                                    style={styles.chip}
                                    onPress={() => {
                                        setQuery(value);
                                        submit(value);
                                    }}
                                >
                                    <Icon name="history" width={14} height={14} />
                                    <Text style={{ fontSize: 10 }}>{value}</Text>
                                </Pressable>
                            ))}
                        </ScrollView>
                    </View>
                </View>
            </KeyboardAvoidingView>
        </Modal>
    );
}
const styles = StyleSheet.create({
    overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.30)" },
    preview: {
        marginTop: 6,
        padding: 10,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: 6,
        backgroundColor: colors.surface
    },
    result: { flexDirection: "row", gap: 10, alignItems: "center", height: 52 },
    chip: {
        backgroundColor: "#EAEAEA",
        borderRadius: 20,
        paddingHorizontal: 10,
        paddingVertical: 8,
        flexDirection: "row",
        gap: 8,
        alignItems: "center"
    }
});
