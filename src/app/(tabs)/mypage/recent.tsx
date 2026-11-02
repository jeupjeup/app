import { View } from "react-native";
import ContentCard from "@/components/ContentCard";
import { EmptyState, Header, Screen } from "@/components/ui";
import { useUserData } from "@/modules/userData";

export default function Page() {
    const { data } = useUserData();
    const items = data.contents
        .filter((item) => item.viewedAt && !item.deletedAt)
        .sort((a, b) => Date.parse(b.viewedAt!) - Date.parse(a.viewedAt!));

    return <Screen>
        <Header title="최근 본 상품" />
        <View style={{ "padding": 16, "paddingTop": 10, "gap": 20, "flex": 1 }}>
            {items.length ? (
                items.map((item) => (
                    <ContentCard key={item.id} item={{ ...item, "savedAt": item.viewedAt! }} recent />
                ))
            ) : (
                <View style={{ "flex": 1, "justifyContent": "center", "paddingBottom": 30 }}>
                    <EmptyState icon="emptyRecent" width={43} height={43} small>
                        최근 본 상품이 없습니다
                    </EmptyState>
                </View>
            )}
        </View>
    </Screen>;
}
