import { Image, type ImageStyle } from "expo-image";
import { router } from "expo-router";
import type { ReactNode } from "react";
import {
    KeyboardAvoidingView,
    Modal,
    Platform,
    Pressable,
    ScrollView,
    StyleSheet,
    Text as NativeText,
    TextInput,
    View,
    type StyleProp,
    type TextProps,
    type TextStyle,
    type ViewStyle
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import { assets, type AssetName } from "@/modules/assets";
import { colors, fonts } from "@/modules/theme";

export function Text({ style, ...props }: TextProps) {
    return <NativeText {...props} style={[styles.text, style]} />;
}

type IconProps = {
    name: AssetName;
    width?: number;
    height?: number;
    style?: StyleProp<ImageStyle>;
};

export function Icon(props: IconProps) {
    const { name, width = 24, height = width, style } = props;

    return <Image source={assets[name]} style={[{ width, height }, style]} contentFit="contain" />;
}

type ButtonProps = {
    children: ReactNode;
    onPress: () => void;
    disabled?: boolean;
    danger?: boolean;
    style?: StyleProp<ViewStyle>;
    textStyle?: StyleProp<TextStyle>;
};

export function Button(props: ButtonProps) {
    const { children, onPress, disabled, danger, style, textStyle } = props;

    return <Pressable
        accessibilityRole="button"
        disabled={disabled}
        onPress={onPress}
        style={({ pressed }) => [
            styles.button,
            danger && { "backgroundColor": colors.danger },
            disabled && { "backgroundColor": colors.soft },
            pressed && { "opacity": 0.8 },
            style
        ]}
    >
        <Text style={[styles.buttonText, textStyle]}>{children}</Text>
    </Pressable>;
}

type HeaderProps = {
    title?: string;
    back?: boolean;
};

export function Header(props: HeaderProps) {
    const { title, back = true } = props;

    return <View style={styles.header}>
        {back && (
            <Pressable
                accessibilityRole="button"
                accessibilityLabel="뒤로 가기"
                hitSlop={12}
                onPress={() => (router.canGoBack() ? router.back() : router.replace("/home"))}
            >
                <Icon name="back" width={12} height={20} style={{ "transform": [{ "rotate": "180deg" }] }} />
            </Pressable>
        )}
        {title && (
            <Text accessibilityRole="header" style={styles.title}>
                {title}
            </Text>
        )}
    </View>;
}

type ScreenProps = {
    children: ReactNode;
    scroll?: boolean;
    style?: StyleProp<ViewStyle>;
    orange?: boolean;
    line?: boolean;
};

export function Screen(props: ScreenProps) {
    const { children, scroll = true, style, orange = false, line = true } = props;

    return <SafeAreaView edges={["top"]} style={[styles.screen, orange && { "backgroundColor": colors.primary }]}>
        <StatusBar style="dark" />
        {line && <View style={{ "height": 2, "backgroundColor": colors.primary }} />}
        <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "ios" ? "padding" : undefined}>
            {scroll ? (
                <ScrollView
                    keyboardShouldPersistTaps="handled"
                    contentContainerStyle={[{ "flexGrow": 1, "backgroundColor": colors.background }, style]}
                >
                    {children}
                </ScrollView>
            ) : (
                <View style={[styles.flex, { "backgroundColor": colors.background }, style]}>{children}</View>
            )}
        </KeyboardAvoidingView>
    </SafeAreaView>;
}

type SearchFieldProps = {
    value?: string;
    onChangeText?: (value: string) => void;
    onSubmit?: () => void;
    onFocus?: () => void;
    onPress?: () => void;
    archive?: boolean;
    autoFocus?: boolean;
};

export function SearchField(props: SearchFieldProps) {
    const { value, onChangeText, onSubmit, onFocus, onPress, archive = false, autoFocus = false } = props;
    if (onPress)
        return <Pressable
            accessibilityRole="button"
            accessibilityLabel="AI 검색하기"
            style={styles.search}
            onPress={onPress}
        >
            <Text style={{ "flex": 1, "color": colors.placeholder, "fontFamily": fonts.medium }}>AI 검색하기</Text>
            <Icon name={archive ? "searchArchive" : "search"} width={20} />
        </Pressable>;

    return <View style={styles.search}>
        <TextInput
            accessibilityLabel="AI 검색하기"
            placeholder="AI 검색하기"
            placeholderTextColor={colors.placeholder}
            value={value}
            onChangeText={onChangeText}
            onFocus={onFocus}
            autoFocus={autoFocus}
            onSubmitEditing={onSubmit}
            returnKeyType="search"
            style={styles.searchInput}
        />
        <Pressable accessibilityRole="button" accessibilityLabel="검색" hitSlop={10} onPress={onSubmit}>
            <Icon name={archive ? "searchArchive" : "search"} width={20} />
        </Pressable>
    </View>;
}

type EmptyStateProps = {
    icon: AssetName;
    children: string;
    boxed?: boolean;
    width?: number;
    height?: number;
    small?: boolean;
};

export function EmptyState(props: EmptyStateProps) {
    const { icon, children, boxed = false, width = 50, height = 41, small = false } = props;

    return <View style={[styles.empty, boxed && styles.emptyBox]}>
        <Icon name={icon} width={width} height={height} />
        <Text style={[styles.emptyText, small && { "fontSize": 13, "lineHeight": 15 }]}>{children}</Text>
    </View>;
}

type DialogProps = {
    visible: boolean;
    onClose: () => void;
    children: ReactNode;
    width?: number;
    style?: StyleProp<ViewStyle>;
    close?: boolean;
};

export function Dialog(props: DialogProps) {
    const { visible, onClose, children, width = 270, style, close = false } = props;

    return <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
        <KeyboardAvoidingView style={styles.overlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
            <Pressable
                style={StyleSheet.absoluteFill}
                accessibilityRole="button"
                accessibilityLabel="팝업 닫기"
                onPress={onClose}
            />
            <View accessibilityViewIsModal style={[styles.dialog, { width, "maxWidth": "90%" }, style]}>
                {close && (
                    <Pressable
                        accessibilityRole="button"
                        accessibilityLabel="닫기"
                        onPress={onClose}
                        hitSlop={12}
                        style={styles.close}
                    >
                        <Icon name="close" width={14} />
                    </Pressable>
                )}
                {children}
            </View>
        </KeyboardAvoidingView>
    </Modal>;
}

export const ui = StyleSheet.create({
    "title": {
        "fontFamily": fonts.bold,
        "fontSize": 24,
        "lineHeight": 35,
        "letterSpacing": -0.24
    },
    "subtitle": {
        "fontFamily": fonts.bold,
        "fontSize": 20,
        "lineHeight": 29,
        "letterSpacing": -0.24
    },
    "row": {
        "flexDirection": "row",
        "alignItems": "center"
    },
    "input": {
        "borderWidth": 1,
        "borderColor": colors.border,
        "borderRadius": 4,
        "backgroundColor": colors.surface,
        "paddingHorizontal": 16,
        "height": 54,
        "color": colors.text,
        "fontFamily": fonts.regular,
        "fontSize": 16
    },
    "divider": {
        "height": 1,
        "backgroundColor": colors.divider
    },
    "page": {
        "paddingHorizontal": 16
    }
});

const styles = StyleSheet.create({
    "text": {
        "color": colors.text,
        "fontFamily": fonts.regular,
        "fontSize": 15,
        "includeFontPadding": false
    },
    "flex": {
        "flex": 1
    },
    "screen": {
        "flex": 1,
        "backgroundColor": colors.background
    },
    "header": {
        "flexDirection": "row",
        "alignItems": "center",
        "gap": 20,
        "minHeight": 70,
        "paddingHorizontal": 16,
        "paddingVertical": 17
    },
    "title": ui.title,
    "button": {
        "minHeight": 46,
        "borderRadius": 6,
        "backgroundColor": colors.primary,
        "justifyContent": "center",
        "alignItems": "center",
        "paddingHorizontal": 16,
        "paddingVertical": 10
    },
    "buttonText": {
        "fontFamily": fonts.semibold,
        "fontSize": 16,
        "lineHeight": 24,
        "color": colors.white,
        "textAlign": "center"
    },
    "search": {
        "height": 50,
        "paddingHorizontal": 16,
        "borderWidth": 1,
        "borderColor": colors.border,
        "borderRadius": 6,
        "backgroundColor": colors.surface,
        "flexDirection": "row",
        "alignItems": "center",
        "gap": 12
    },
    "searchInput": {
        "flex": 1,
        "minWidth": 0,
        "height": "100%",
        "padding": 0,
        "fontSize": 15,
        "color": colors.text,
        "fontFamily": fonts.medium
    },
    "empty": {
        "alignItems": "center",
        "justifyContent": "center",
        "gap": 10,
        "minHeight": 210
    },
    "emptyBox": {
        "borderWidth": 1,
        "borderColor": colors.border,
        "borderRadius": 8,
        "minHeight": 194
    },
    "emptyText": {
        "color": colors.primary,
        "fontSize": 15,
        "lineHeight": 30,
        "textAlign": "center"
    },
    "overlay": {
        "flex": 1,
        "backgroundColor": "rgba(0,0,0,0.25)",
        "justifyContent": "center",
        "alignItems": "center"
    },
    "dialog": {
        "backgroundColor": colors.surface,
        "borderRadius": 10,
        "padding": 16,
        "gap": 16,
        "alignItems": "stretch"
    },
    "close": {
        "alignSelf": "flex-end",
        "zIndex": 1
    }
});
