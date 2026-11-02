import { Modal, Pressable, ScrollView, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Icon, Text, ui } from "@/components/ui";
import { colors } from "@/modules/theme";

// 241:4853 / 241:4923 / 241:5108.
type Props = {
    title: string | null;
    options: string[];
    value: string;
    onSelect: (value: string) => void;
    onClose: () => void;
};

export default function FilterSheet(props: Props) {
    const { title, options, value, onSelect, onClose } = props;
    const insets = useSafeAreaInsets();

    return <Modal visible={!!title} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
        <View style={styles.overlay}>
            <Pressable
                accessibilityRole="button"
                accessibilityLabel="필터 닫기"
                onPress={onClose}
                style={StyleSheet.absoluteFill}
            />
            <View
                accessibilityViewIsModal
                style={[styles.sheet, { "paddingBottom": Math.max(8, insets.bottom), "minHeight": 356 }]}
            >
                <Text style={[ui.subtitle, { "paddingHorizontal": 10, "paddingBottom": 20 }]}>{title}</Text>
                <ScrollView>
                    {options.map((option) => (
                        <Pressable
                            key={option}
                            accessibilityRole="radio"
                            accessibilityState={{ "checked": value === option }}
                            style={styles.option}
                            onPress={() => {
                                onSelect(option);
                                onClose();
                            }}
                        >
                            <Text>{option}</Text>
                            <Icon name={value === option ? "radioSelected" : "radio"} width={20} height={20} />
                        </Pressable>
                    ))}
                </ScrollView>
            </View>
        </View>
    </Modal>;
}

const styles = StyleSheet.create({
    "overlay": {
        "flex": 1,
        "backgroundColor": "rgba(0,0,0,0.30)",
        "justifyContent": "flex-end"
    },
    "sheet": {
        "maxHeight": "80%",
        "borderTopLeftRadius": 32,
        "borderTopRightRadius": 32,
        "backgroundColor": colors.surface,
        "paddingTop": 24,
        "paddingHorizontal": 16
    },
    "option": {
        "flexDirection": "row",
        "justifyContent": "space-between",
        "alignItems": "center",
        "minHeight": 56,
        "paddingHorizontal": 10,
        "borderTopWidth": 1,
        "borderTopColor": colors.divider
    }
});
