import { useState } from "react";
import { Pressable, View } from "react-native";
import ContentCard from "@/components/ContentCard";
import { Button, Dialog, EmptyState, Header, Screen, Text } from "@/components/ui";
import { colors } from "@/modules/theme";
import { useUserData } from "@/modules/userData";

// 218:1126, 218:1030, restore overlay 310:1605.
export default function Page() {
    const { data, command, restore, busy } = useUserData();
    const [restoreId, setRestoreId] = useState<string | null>(null);
    const items = data.contents.filter((item) => item.deletedAt);

    return <>
        <Screen>
            <Header title="휴지통" />
            <View style={{ "paddingHorizontal": 16, "gap": 20, "paddingBottom": 24, "flex": 1 }}>
                {!!items.length && (
                    <Pressable
                        accessibilityRole="button"
                        disabled={busy}
                        onPress={() => { void command("/trash", "DELETE"); }}
                        style={{ "alignSelf": "flex-end", "paddingVertical": 4 }}
                    >
                        <Text style={{ "color": colors.muted, "fontSize": 14 }}>휴지통 비우기</Text>
                    </Pressable>
                )}
                {items.length ? (
                    items.map((item) => (
                        <ContentCard key={item.id} item={item} restore={() => setRestoreId(item.id)} />
                    ))
                ) : (
                    <View style={{ "flex": 1, "justifyContent": "center", "paddingBottom": 30 }}>
                        <EmptyState icon="emptyTrash" width={61} height={61} small>
                            휴지통이 비었습니다
                        </EmptyState>
                    </View>
                )}
            </View>
        </Screen>
        <Dialog visible={!!restoreId} onClose={() => setRestoreId(null)}>
            <Text style={{ "textAlign": "center", "fontSize": 16 }}>이 정보를 복구하시겠습니까?</Text>
            <Button
                disabled={busy}
                onPress={async () => {
                    if (restoreId && await restore(restoreId)) setRestoreId(null);
                }}
                style={{ "alignSelf": "center", "width": 182, "minHeight": 32, "paddingVertical": 4 }}
            >
                복구하기
            </Button>
        </Dialog>
    </>;
}
