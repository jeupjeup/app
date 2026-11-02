import { Pressable, StyleSheet, View } from "react-native";
import { Icon, Text } from "@/components/ui";
import { colors, fonts } from "@/modules/theme";
import type { AssetName } from "@/modules/assets";
import { useUserData } from "@/modules/userData";

type ProfileRowProps = {
    detail?: boolean;
    onPress?: () => void;
};

export function ProfileRow(props: ProfileRowProps) {
    const { detail = false, onPress } = props;
    const { data } = useUserData();

    return <Pressable accessibilityRole={onPress ? "button" : undefined} onPress={onPress} style={styles.profile}>
        <Icon name="avatar" width={50} height={50} />
        <View style={{ "flex": 1, "gap": 4 }}>
            <Text style={{ "fontFamily": fonts.semibold, "fontSize": 16 }}>{data.nickname}</Text>
            {!detail && <Text style={{ "fontSize": 10, "color": colors.placeholder }}>상세 정보</Text>}
        </View>
        {!detail && <Icon name="profileChevron" width={8} height={14} />}
    </Pressable>;
}

type ServiceRowProps = {
    icon: AssetName;
    title: string;
    onPress?: () => void;
    trailing?: React.ReactNode;
};

export function ServiceRow(props: ServiceRowProps) {
    const { icon, title, onPress, trailing } = props;
    const dimensions: Partial<Record<AssetName, [number, number]>> = {
        "computer": [22, 18],
        "id": [19, 20],
        "nickname": [22, 20.4692],
        "password": [21, 18],
        "door": [18, 18]
    };
    const [width, height] = dimensions[icon] ?? [24, 24];

    return <Pressable accessibilityRole={onPress ? "button" : undefined} onPress={onPress} style={styles.service}>
        <View style={{ "width": 24, "alignItems": "center" }}>
            <Icon name={icon} width={width} height={height} />
        </View>
        <Text style={{ "fontSize": 15, "fontFamily": fonts.medium, "flex": 1 }}>{title}</Text>
        {trailing}
    </Pressable>;
}

const styles = StyleSheet.create({
    "profile": {
        "flexDirection": "row",
        "gap": 10,
        "alignItems": "center",
        "minHeight": 90,
        "backgroundColor": colors.white,
        "paddingHorizontal": 16,
        "paddingVertical": 20,
        "borderTopWidth": 1,
        "borderBottomWidth": 1,
        "borderColor": "#D4D3D1"
    },
    "service": {
        "minHeight": 54,
        "paddingHorizontal": 26,
        "paddingVertical": 14,
        "flexDirection": "row",
        "alignItems": "center",
        "gap": 10
    }
});
