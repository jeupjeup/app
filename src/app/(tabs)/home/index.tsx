import { Image } from "expo-image";
import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { EmptyState, Icon, Screen, SearchField, Text, ui } from "@/components/ui";
import ContentCard from "@/components/ContentCard";
import CollectionGrid, { openCollection } from "@/components/CollectionGrid";
import AddContentDialog from "@/components/AddContentDialog";
import SearchDialog from "@/components/SearchDialog";
import { assets } from "@/modules/assets";
import { colors } from "@/modules/theme";
import { useUserData } from "@/modules/userData";

export default function Page() {
    const { url } = useLocalSearchParams<{ url?: string; }>();
    const { data } = useUserData();
    const [add, setAdd] = useState(false);
    const [search, setSearch] = useState(false);
    const items = data.contents.filter((item) => !item.deletedAt);
    const heading = (title: string) => (
        <Pressable accessibilityRole="button" onPress={() => openCollection()} style={styles.heading}>
            <Text style={ui.title}>{title}</Text>
            <Icon name="chevron" width={12} height={20} />
        </Pressable>
    );

    return <>
        <Screen orange line={false} style={{ "paddingBottom": 30 }}>
            <View style={styles.brand}>
                <Image source={assets.logoHome} style={{ "width": 39, "height": 25 }} contentFit="contain" />
                <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="알림"
                    onPress={() => router.push("/home/notifications")}
                    hitSlop={12}
                >
                    <Icon name="bell" width={19} height={24} />
                </Pressable>
            </View>
            <View style={styles.body}>
                <View>
                    <SearchField onPress={() => setSearch(true)} />
                    <Text style={styles.hint}>기억나는 모든 것으로 AI에게 질문해보세요!</Text>
                    {items.length === 0 && (
                        <Text style={styles.hint}>ex) 오사카 여행갈 때 필요했던 캐리어 뭐였더라?</Text>
                    )}
                </View>
                <View>
                    {items.length === 0 && (
                        <Text style={{ "color": colors.primary, "fontSize": 12, "marginBottom": 12 }}>
                            최초로 정보를 추가해보세요!
                        </Text>
                    )}
                    <Pressable
                        accessibilityRole="button"
                        accessibilityLabel="URL · 텍스트 추가"
                        style={styles.add}
                        onPress={() => setAdd(true)}
                    >
                        <Text style={{ "fontSize": 28, "lineHeight": 28 }}>＋</Text>
                        <Text style={{ "fontSize": 12 }}>URL · 텍스트 추가</Text>
                    </Pressable>
                </View>
                <View style={styles.banner}>
                    <Text style={{ "fontSize": 12, "color": "#000000" }}>배너</Text>
                </View>
                {heading("최근 저장 목록")}
                {items.length ? (
                    <View style={{ "flexDirection": "row", "gap": 20 }}>
                        {items.slice(0, 2).map((item, index) => (
                            <ContentCard key={item.id} item={item} compact index={index} />
                        ))}
                    </View>
                ) : (
                    <EmptyState boxed icon="emptyHome">
                        아직 저장된 정보가 없어요
                    </EmptyState>
                )}
                {heading("컬렉션")}
                {items.length ? (
                    <CollectionGrid />
                ) : (
                    <EmptyState boxed icon="emptyHome">
                        아직 생성된 컬렉션이 없어요
                    </EmptyState>
                )}
                {!!items.length && (
                    <>
                        {heading("가장 많이 본 컬렉션")}
                        <CollectionGrid popular />
                    </>
                )}
            </View>
        </Screen>
        <AddContentDialog
            key={url ?? "add"}
            visible={add || !!url}
            initialUrl={url}
            onClose={() => {
                setAdd(false);
                if (url) router.setParams({ "url": "" });
            }}
        />
        <SearchDialog visible={search} onClose={() => setSearch(false)} />
    </>;
}

const styles = StyleSheet.create({
    "brand": {
        "backgroundColor": colors.primary,
        "height": 70,
        "paddingHorizontal": 16,
        "paddingVertical": 20,
        "flexDirection": "row",
        "justifyContent": "space-between",
        "alignItems": "center"
    },
    "body": {
        "paddingHorizontal": 16,
        "paddingTop": 30,
        "gap": 30
    },
    "hint": {
        "fontSize": 12,
        "color": colors.placeholder,
        "marginTop": 4,
        "lineHeight": 20
    },
    "add": {
        "minHeight": 30,
        "paddingHorizontal": 8,
        "borderWidth": 1,
        "borderColor": colors.border,
        "borderRadius": 6,
        "flexDirection": "row",
        "alignItems": "center",
        "justifyContent": "space-between",
        "backgroundColor": colors.surface
    },
    "banner": {
        "height": 160,
        "borderRadius": 8,
        "backgroundColor": colors.soft,
        "justifyContent": "center",
        "alignItems": "center"
    },
    "heading": {
        "minHeight": 44,
        "flexDirection": "row",
        "justifyContent": "space-between",
        "alignItems": "center"
    }
});
