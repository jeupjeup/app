import { registerDevMenuItems } from "expo-dev-client";
import { router } from "expo-router";
import { useEffect } from "react";
import { initialContents, samplePreviewData } from "@/modules/fixtures";
import { useUserData } from "@/modules/userData";
import type { ContentStatus } from "@/types/content";

// Preview controls stay in the development client's menu, outside the product UI.
export function useDevelopmentMenu() {
    const { previewData: update, saveSampleData, clearSavedSampleData, ready } = useUserData();

    useEffect(() => {
        if (!__DEV__ || !ready) return;
        const detail = (status: ContentStatus) => {
            update((d) => ({
                ...d,
                "contents": d.contents.some((item) => item.id === "cafe-1")
                    ? d.contents
                    : [...initialContents, ...d.contents]
            }));
            router.push({ "pathname": "/library/[id]", "params": { "id": "cafe-1", status } });
        };
        void registerDevMenuItems([
            {
                name: "Figma · 예시 데이터 저장",
                shouldCollapse: true,
                callback: () => {
                    void saveSampleData().then(saved => {
                        if (saved) router.replace("/home");
                        else console.warn("예시 데이터를 기기에 저장하지 못했습니다.");
                    });
                }
            },
            {
                name: "Figma · 예시 데이터 저장 해제",
                shouldCollapse: true,
                callback: () => {
                    void clearSavedSampleData().then(cleared => {
                        if (cleared) router.replace("/");
                        else console.warn("예시 데이터 저장을 해제하지 못했습니다.");
                    });
                }
            },
            {
                "name": "Figma · 예시 데이터 복원",
                "shouldCollapse": true,
                "callback": () => {
                    update(samplePreviewData);
                    router.replace("/home");
                }
            },
            {
                "name": "Figma · 빈 화면 상태",
                "shouldCollapse": true,
                "callback": () => {
                    update({ "contents": [], "notices": [], "savedCount": 0 });
                    router.replace("/home");
                }
            },
            { "name": "Figma · 상세 / 분석 중", "shouldCollapse": true, "callback": () => detail("analyzing") },
            { "name": "Figma · 상세 / 분석 실패", "shouldCollapse": true, "callback": () => detail("failed") },
            { "name": "Figma · 상세 / 원본 접근 불가", "shouldCollapse": true, "callback": () => detail("unavailable") },
            { "name": "Figma · 온보딩", "shouldCollapse": true, "callback": () => router.push("/onboarding") }
        ]).catch((error: unknown) => console.warn("Could not register development menu", error));
    }, [update, saveSampleData, clearSavedSampleData, ready]);
}
