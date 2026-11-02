import { router } from "expo-router";
import { Pressable, StyleSheet, View } from "react-native";
import { Icon, Text } from "@/components/ui";
import { colors, fonts } from "@/modules/theme";
import type { AssetName } from "@/modules/assets";
import type { Collection } from "@/types/content";

export const collections: { name: Collection; icon: AssetName; }[] = [
    { "name": "장소", "icon": "place" },
    { "name": "여행", "icon": "travel" },
    { "name": "음식", "icon": "food" },
    { "name": "의류", "icon": "clothing" },
    { "name": "제품", "icon": "product" },
    { "name": "회사", "icon": "work" }
];

export function openCollection(collection?: Collection) {
    router.navigate({ "pathname": "/library", "params": { "collection": collection ?? "", "q": "" } });
}

type Props = {
    popular?: boolean;
};

export default function CollectionGrid(props: Props) {
    const { popular = false } = props;

    return <View style={styles.grid}>
        {(popular ? [collections[0], collections[2]] : collections).map((item) => (
            <Pressable
                accessibilityRole="button"
                key={item.name}
                accessibilityLabel={`${item.name} 컬렉션 보러가기`}
                onPress={() => openCollection(item.name)}
                style={[styles.item, { "width": popular ? "48%" : "31%" }]}
            >
                <View style={styles.content}>
                    <Icon name={item.icon} width={item.icon === "work" ? 21.332 : 24} />
                    <Text style={styles.label}>{item.name}</Text>
                </View>
                {popular && (
                    <View style={styles.action}>
                        <Text style={{ "color": colors.white, "fontSize": 10, "fontFamily": fonts.semibold }}>
                            보러가기
                        </Text>
                    </View>
                )}
            </Pressable>
        ))}
    </View>;
}

const styles = StyleSheet.create({
    "grid": {
        "flexDirection": "row",
        "flexWrap": "wrap",
        "justifyContent": "space-between",
        "rowGap": 30
    },
    "item": {
        "backgroundColor": colors.soft,
        "borderRadius": 8,
        "overflow": "hidden"
    },
    "content": {
        "height": 60,
        "justifyContent": "center",
        "alignItems": "center",
        "gap": 4
    },
    "label": {
        "fontFamily": fonts.semibold,
        "fontSize": 12,
        "lineHeight": 17.4
    },
    "action": {
        "height": 36,
        "justifyContent": "center",
        "alignItems": "center",
        "backgroundColor": colors.primary
    }
});
