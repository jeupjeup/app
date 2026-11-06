import { useState } from "react";
import { Pressable, TextInput, View } from "react-native";
import { Button, Dialog, Text } from "@/components/ui";
import { useUserData } from "@/modules/userData";
import { colors, fonts } from "@/modules/theme";
import type { Collection, ContentType, SavedContent } from "@/types/content";

const types: ContentType[] = ["영상", "이미지", "텍스트", "기타"];
const collections: Collection[] = ["장소", "여행", "음식", "의류", "제품", "회사"];
export default function EditContentDialog({ item, onClose }: { item: SavedContent; onClose: () => void }) {
    const { command, busy, error } = useUserData();
    const [original] = useState(item);
    const [title, setTitle] = useState(item.title);
    const [memo, setMemo] = useState(item.memo);
    const [type, setType] = useState(item.type);
    const [collection, setCollection] = useState<Collection | null>(item.collection ?? null);
    const patch: { title?: string; memo?: string; type?: ContentType; collection?: Collection | null } = {};
    if (title.trim() !== original.title) patch.title = title.trim();
    if (memo !== original.memo) patch.memo = memo;
    if (type !== original.type) patch.type = type;
    if (collection !== (original.collection ?? null)) patch.collection = collection;
    const inputStyle = { borderWidth: 1, borderColor: colors.border, borderRadius: 6, padding: 10, color: colors.text, fontFamily: fonts.regular };
    const choice = (label: string, selected: boolean, onPress: () => void) => <Pressable key={label} accessibilityRole="radio" accessibilityState={{ checked: selected }} onPress={onPress}
        style={{ padding: 8, borderRadius: 6, backgroundColor: selected ? colors.soft : colors.background }}><Text>{label}</Text></Pressable>;
    return <Dialog visible onClose={onClose} close>
        <Text>정보 수정</Text>
        <TextInput accessibilityLabel="제목" value={title} onChangeText={setTitle} maxLength={200} style={inputStyle} />
        <TextInput accessibilityLabel="메모" value={memo} onChangeText={setMemo} maxLength={70} multiline style={inputStyle} />
        <Text>유형</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4 }}>{types.map(value => choice(value, type === value, () => setType(value)))}</View>
        <Text>컬렉션</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
            {choice("없음", collection === null, () => setCollection(null))}
            {collections.map(value => choice(value, collection === value, () => setCollection(value)))}
        </View>
        {error && <Text accessibilityRole="alert">{error}</Text>}
        <Button disabled={busy || !title.trim() || Object.keys(patch).length === 0} onPress={() => {
            void command(`/contents/${encodeURIComponent(item.id)}`, "PATCH", patch).then(saved => { if (saved) onClose(); });
        }}>저장</Button>
    </Dialog>;
}
