import { registerDevMenuItems } from "expo-dev-client";
import { router } from "expo-router";
import { useEffect } from "react";
import { initialContents, initialNotices, initialTrash } from "./fixtures";
import { useUserData } from "./userData";
import type { ContentStatus } from "@/types/content";

// Preview controls stay in the development client's menu, outside the product UI.
export function useDevelopmentMenu() {
    const { update } = useUserData();
    useEffect(() => {
        if (!__DEV__) return;
        const detail = (status: ContentStatus) => {
            update((d) => ({
                ...d,
                contents: d.contents.some((item) => item.id === "cafe-1")
                    ? d.contents
                    : [...initialContents, ...d.contents]
            }));
            router.push({ pathname: "/library/[id]", params: { id: "cafe-1", status } });
        };
        void registerDevMenuItems([
            {
                name: "Figma · 예시 데이터 복원",
                shouldCollapse: true,
                callback: () => {
                    update({
                        contents: [...initialContents, ...initialTrash],
                        notices: initialNotices,
                        savedCount: 143
                    });
                    router.replace("/home");
                }
            },
            {
                name: "Figma · 빈 화면 상태",
                shouldCollapse: true,
                callback: () => {
                    update({ contents: [], notices: [], savedCount: 0 });
                    router.replace("/home");
                }
            },
            { name: "Figma · 상세 / 분석 중", shouldCollapse: true, callback: () => detail("analyzing") },
            { name: "Figma · 상세 / 분석 실패", shouldCollapse: true, callback: () => detail("failed") },
            { name: "Figma · 상세 / 원본 접근 불가", shouldCollapse: true, callback: () => detail("unavailable") },
            { name: "Figma · 온보딩", shouldCollapse: true, callback: () => router.push("/onboarding") }
        ]).catch((error: unknown) => console.warn("Could not register development menu", error));
    }, [update]);
}
