import type { AssetName } from "@/modules/assets";

export type Collection = "장소" | "여행" | "음식" | "의류" | "제품" | "회사";
export type ContentType = "영상" | "이미지" | "텍스트" | "기타";
export type ContentStatus = "ready" | "analyzing" | "failed" | "unavailable";
export interface SavedContent {
    id: string;
    title: string;
    url: string;
    memo: string;
    image?: AssetName;
    type: ContentType;
    collection?: Collection;
    source: string;
    description: string;
    tags: string[];
    savedAt: string;
    status: ContentStatus;
    deletedAt?: string;
    viewedAt?: string;
    pendingSync?: boolean;
}

export interface Notice {
    id: string;
    title: string;
    description: string;
    date: string;
    read: boolean;
    error?: boolean;
    collection?: Collection;
}
