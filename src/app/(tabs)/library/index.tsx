import { useLocalSearchParams } from "expo-router";
import { useMemo, useState } from "react";
import { FlatList, Pressable, RefreshControl, StyleSheet, View } from "react-native";
import ContentCard from "@/components/ContentCard";
import FilterSheet from "@/components/FilterSheet";
import { collections } from "@/components/CollectionGrid";
import { EmptyState, Icon, Screen, SearchField, Text, ui } from "@/components/ui";
import { colors, fonts } from "@/modules/theme";
import { useUserData } from "@/modules/userData";

// L-01: 162:1541, 259:6831, 259:6907, 241:5497.
export default function Page() {
    const params = useLocalSearchParams<{ q?: string; collection?: string; }>();

    return <LibraryContent
        key={`${params.q ?? ""}:${params.collection ?? ""}`}
        initialQuery={params.q ?? ""}
        initialCollection={params.collection || "전체"}
    />;
}

type LibraryContentProps = {
    initialQuery: string;
    initialCollection: string;
};

function LibraryContent(props: LibraryContentProps) {
    const { initialQuery, initialCollection } = props;
    const { data, refresh } = useUserData();
    const [query, setQuery] = useState(initialQuery);
    const [search, setSearch] = useState(initialQuery);
    const [type, setType] = useState("전체");
    const [collection, setCollection] = useState(initialCollection);
    const [sort, setSort] = useState("기본");
    const [sheet, setSheet] = useState<"유형" | "컬렉션" | "정렬" | null>(null);
    const active = data.contents.filter((item) => !item.deletedAt);
    const items = useMemo(
        () =>
            data.contents
                .filter(
                    (item) =>
                        !item.deletedAt &&
                        (type === "전체" || item.type === type) &&
                        (collection === "전체" || item.collection === collection) &&
                        (!search.trim() ||
                            `${item.title} ${item.description} ${item.tags.join(" ")} ${item.memo}`
                                .toLowerCase()
                                .includes(search.trim().toLowerCase()))
                )
                .sort((a, b) =>
                    sort === "최신순"
                        ? Date.parse(b.savedAt) - Date.parse(a.savedAt)
                        : sort === "오래된 순"
                            ? Date.parse(a.savedAt) - Date.parse(b.savedAt)
                            : 0
                ),
        [data.contents, type, collection, sort, search]
    );
    const options =
        sheet === "유형"
            ? ["전체", "영상", "이미지", "텍스트", "기타"]
            : sheet === "컬렉션"
                ? ["전체", ...collections.map((c) => c.name)]
                : ["기본", "최신순", "오래된 순"];
    const value = sheet === "유형" ? type : sheet === "컬렉션" ? collection : sort;
    const reset = () => {
        setType("전체");
        setCollection("전체");
        setSort("기본");
        setQuery("");
        setSearch("");
    };

    return <>
        <Screen orange line={false} scroll={false}>
            <FlatList
                data={items}
                refreshControl={<RefreshControl
                    refreshing={false}
                    onRefresh={() => { void refresh(); }}
                    tintColor="transparent"
                    colors={["transparent"]}
                    progressBackgroundColor="transparent"
                />}
                keyExtractor={(item) => item.id}
                keyboardShouldPersistTaps="handled"
                keyboardDismissMode="on-drag"
                contentContainerStyle={{ "padding": 16, "gap": 20, "flexGrow": 1 }}
                ListHeaderComponent={
                    <View style={{ "gap": 20 }}>
                        <Text style={[ui.title, { "lineHeight": 33 }]}>지금까지 저장한 목록</Text>
                        <SearchField
                            archive
                            value={query}
                            onChangeText={(v) => {
                                setQuery(v);
                                if (!v) setSearch("");
                            }}
                            onSubmit={() => setSearch(query)}
                        />
                        <View>
                            <Pressable
                                accessibilityRole="button"
                                onPress={reset}
                                style={{ "alignSelf": "flex-end", "marginBottom": 8 }}
                            >
                                <Text style={{ "fontSize": 12, "color": colors.primary, "lineHeight": 20 }}>
                                    필터 초기화
                                </Text>
                            </Pressable>
                            <View style={styles.filters}>
                                {(["유형", "컬렉션", "정렬"] as const).map((name) => (
                                    <Pressable
                                        key={name}
                                        accessibilityRole="button"
                                        onPress={() => setSheet(name)}
                                        style={styles.filter}
                                    >
                                        <Text style={styles.filterText}>
                                            {name === "유형"
                                                ? type === "전체"
                                                    ? "유형"
                                                    : type
                                                : name === "컬렉션"
                                                    ? collection === "전체"
                                                        ? "컬렉션"
                                                        : collection
                                                    : sort}
                                        </Text>
                                        <View style={{ "transform": [{ "rotate": "-90deg" }] }}>
                                            <Icon name="filterArrow" width={7} height={11.89} />
                                        </View>
                                    </Pressable>
                                ))}
                            </View>
                        </View>
                    </View>
                }
                renderItem={({ item }) => <ContentCard item={item} />}
                ListEmptyComponent={
                    <View style={{ "paddingTop": 90 }}>
                        <EmptyState icon="emptyArchive">
                            {active.length ? "다른 필터로 다시 검색해보세요" : "아직 저장된 정보가 없어요"}
                        </EmptyState>
                    </View>
                }
            />
        </Screen>
        <FilterSheet
            title={sheet}
            options={options}
            value={value}
            onClose={() => setSheet(null)}
            onSelect={sheet === "유형" ? setType : sheet === "컬렉션" ? setCollection : setSort}
        />
    </>;
}

const styles = StyleSheet.create({
    "filters": {
        "flexDirection": "row",
        "gap": 20
    },
    "filter": {
        "flex": 1,
        "minHeight": 33,
        "flexDirection": "row",
        "alignItems": "center",
        "justifyContent": "space-between",
        "paddingHorizontal": 20,
        "borderRadius": 20,
        "backgroundColor": "#EAE9E7",
        "borderWidth": 1,
        "borderColor": "#D7D6D4"
    },
    "filterText": {
        "fontFamily": fonts.semibold,
        "fontSize": 14,
        "letterSpacing": -0.5
    }
});
