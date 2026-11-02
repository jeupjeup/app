import type { Notice, SavedContent } from "@/types/content";

// Only sample content visible inside the seven uiux Sections is used here.
export const cafeDescription =
    "브루다 커피 종각역점을 소개하는 블로그글입니다.\n\n브루다 커피는 도심 속에서 향긋한 커피와 편안한 휴식을 즐길 수 있는 모던한 분위기의 카페입니다. 접근성이 좋아 약속 전후로 가볍게 방문하기 좋으며, 아늑한 분위기 속에서 여유를 즐길 수 있습니다.\n\n위치 : 서울특별시 종로구 종로 65 1층";
export const initialContents: SavedContent[] = [1, 2, 3].map((n) => ({
    id: `cafe-${n}`,
    title: "브루다 커피 종각역점",
    url: `https://search.naver.com/search.naver?query=${encodeURIComponent(n === 1 ? "브루다 커피 종각역점" : `브루다 커피 종각역점 ${n}`)}`,
    memo: "",
    image: "cafeArchive",
    type: "텍스트",
    collection: "장소",
    source: "블로그",
    description: cafeDescription,
    tags: ["카페", "브루다커피", "종각역"],
    savedAt: "2026-10-12T10:00:00+09:00",
    status: "ready"
}));

export const initialTrash: SavedContent[] = [1, 2, 3].map((n) => ({
    id: `pillow-${n}`,
    title: "헬로키티 목베개",
    url: "https://search.naver.com/search.naver?query=" + encodeURIComponent("헬로키티 목베개"),
    memo: "",
    image: "pillow",
    type: "이미지",
    collection: "제품",
    source: "",
    description: "",
    tags: [],
    savedAt: "2026-10-12T10:00:00+09:00",
    deletedAt: "2026-10-12T10:00:00+09:00",
    status: "ready"
}));

export const initialNotices: Notice[] = [
    {
        id: "1",
        title: "새로운 컬렉션이 생겼어요!",
        description: "새로운 ‘장소’ 컬렉션에 저장을 추가해보세요.",
        date: "2026.10.12. 19:43",
        read: false,
        collection: "장소"
    },
    {
        id: "2",
        title: "10번째 추가가 완료됐어요!",
        description: "‘회사’ 컬렉션에 10번째로 저장했어요!",
        date: "2026.10.12. 17:43",
        read: false,
        collection: "회사"
    },
    {
        id: "3",
        title: "오류가 생겼어요!",
        description: "링크를 다시 한번 첨부해주세요.",
        date: "2026.10.12. 15:43",
        read: false,
        error: true
    },
    {
        id: "4",
        title: "새로운 컬렉션이 생겼어요!",
        description: "새로운 ‘의류’ 컬렉션에 저장을 추가해보세요.",
        date: "2026.10.12. 12:43",
        read: true,
        collection: "의류"
    }
];
