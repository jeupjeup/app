import { useEffect, useRef, useState } from "react";
import { Animated, Easing, Modal, Platform, Pressable, ScrollView, StyleSheet, View } from "react-native";
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
    const [progress] = useState(() => new Animated.Value(0));
    const fadeComplete = useRef(false);
    const sheetDismissed = useRef(true);
    const [content, setContent] = useState<{ title: string; options: string[]; value: string; } | null>(null);
    const [backdropReady, setBackdropReady] = useState(false);
    const open = !!title;

    // Keep the selected filter visible until its closing animation finishes.
    if (title && (content?.title !== title || content.options !== options || content.value !== value)) {
        setContent({ title, options, value });
    }

    useEffect(() => {
        if (!backdropReady) return;
        fadeComplete.current = false;
        if (open) sheetDismissed.current = false;
        const animation = Animated.timing(progress, {
            toValue: open ? 1 : 0,
            duration: open ? 260 : 200,
            easing: open ? Easing.out(Easing.cubic) : Easing.in(Easing.cubic),
            useNativeDriver: true
        });
        animation.start(({ finished }) => {
            if (finished && !open) {
                fadeComplete.current = true;
                if (Platform.OS !== "ios" || sheetDismissed.current) {
                    setContent(null);
                    setBackdropReady(false);
                }
            }
        });
        return () => animation.stop();
    }, [open, backdropReady, progress]);

    return <Modal
        visible={!!content}
        transparent
        animationType="none"
        onRequestClose={onClose}
        onShow={() => setBackdropReady(true)}
        statusBarTranslucent
    >
        <View style={styles.overlay} pointerEvents={open ? "auto" : "none"}>
            <Animated.View style={[StyleSheet.absoluteFill, styles.backdrop, { opacity: progress }]} />
            <Modal
                visible={open && backdropReady}
                transparent
                animationType="slide"
                onRequestClose={onClose}
                onDismiss={() => {
                    sheetDismissed.current = true;
                    if (!open && fadeComplete.current) {
                        setContent(null);
                        setBackdropReady(false);
                    }
                }}
                statusBarTranslucent
            >
                <View style={styles.overlay}>
                    <Pressable
                        accessibilityRole="button"
                        accessibilityLabel="필터 닫기"
                        onPress={onClose}
                        style={StyleSheet.absoluteFill}
                    />
                    <View
                        accessibilityViewIsModal
                        style={[styles.sheet, { paddingBottom: Math.max(8, insets.bottom), minHeight: 356 }]}
                    >
                        <Text style={[ui.subtitle, { "paddingHorizontal": 10, "paddingBottom": 20 }]}>{content?.title}</Text>
                        <ScrollView>
                            {content?.options.map((option) => (
                                <Pressable
                                    key={option}
                                    accessibilityRole="radio"
                                    accessibilityState={{ "checked": content.value === option }}
                                    style={styles.option}
                                    onPress={() => {
                                        onSelect(option);
                                        onClose();
                                    }}
                                >
                                    <Text>{option}</Text>
                                    <Icon name={content.value === option ? "radioSelected" : "radio"} width={20} height={20} />
                                </Pressable>
                            ))}
                        </ScrollView>
                    </View>
                </View>
            </Modal>
        </View>
    </Modal>;
}

const styles = StyleSheet.create({
    "overlay": {
        "flex": 1,
        "justifyContent": "flex-end"
    },
    "backdrop": {
        "backgroundColor": "rgba(0,0,0,0.30)"
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
