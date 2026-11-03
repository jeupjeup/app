import { Redirect, Tabs } from "expo-router";
import { useUserData } from "@/modules/userData";
import TabBar from "@/components/TabBar";
import { colors } from "@/modules/theme";

export default function TabLayout() {
    const { data, ready } = useUserData();
    if (!ready) return null;
    if (!data.authenticated) return <Redirect href="/login" />;
    return <Tabs
        backBehavior="history"
        tabBar={({ state, emitter, navigateToTab }) => (
            <TabBar
                active={state.routes[state.index].name}
                onNavigate={(name) => {
                    const route = state.routes.find((r) => r.name === name);
                    if (!route) return;
                    const event = emitter.emit({ "type": "tabPress", "target": route.key, "canPreventDefault": true });
                    if (!event.defaultPrevented) navigateToTab(route.key);
                }}
            />
        )}
        screenOptions={{
            "headerShown": false,
            "sceneStyle": { "backgroundColor": colors.background },
            "tabBarHideOnKeyboard": true
        }}
    >
        <Tabs.Screen name="home" options={{ "title": "홈" }} />
        <Tabs.Screen name="library" options={{ "title": "보관함" }} />
        <Tabs.Screen name="mypage" options={{ "title": "마이" }} />
    </Tabs>;
}
