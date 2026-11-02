import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { initialContents, initialNotices, initialTrash } from "@/modules/fixtures";
import type { Notice, SavedContent } from "@/types/content";

type UserData = {
    onboarded: boolean;
    previewSession: boolean;
    nickname: string;
    email: string;
    contents: SavedContent[];
    notices: Notice[];
    searchHistory: string[];
    passwordAttempts: number;
    passwordLockedUntil: number;
    savedCount: number;
};

const initialData: UserData = {
    "onboarded": false,
    "previewSession": false,
    "nickname": "달리는 자동차",
    "email": "ajhfaofew@gmail.com",
    "contents": [...initialContents, ...initialTrash],
    "notices": initialNotices,
    "searchHistory": ["오사카", "케이크", "유자차", "커피"],
    "passwordAttempts": 0,
    "passwordLockedUntil": 0,
    "savedCount": 143
};

const STORAGE_KEY = "@jeupjeup/ui-preview/v1";

type Update = Partial<UserData> | ((data: UserData) => UserData);

const Context = createContext<{
    data: UserData;
    ready: boolean;
    update: (change: Update) => void;
    remove: (id: string) => void;
    restore: (id: string) => void;
    reset: () => void;
    previewPasswordRef: React.MutableRefObject<string>;
} | null>(null);

type UserDataProviderProps = {
    children: ReactNode;
};

export function UserDataProvider(props: UserDataProviderProps) {
    const { children } = props;
    const [data, setData] = useState<UserData>(initialData);
    const [ready, setReady] = useState(false);
    // Credentials are never persisted. Authentication is an explicit local UI preview.
    const previewPasswordRef = useRef("");
    const writes = useRef(Promise.resolve());

    useEffect(() => {
        let active = true;
        AsyncStorage.getItem(STORAGE_KEY)
            .then((raw) => {
                if (active && raw) {
                    const stored = JSON.parse(raw) as Partial<UserData>;
                    const cutoff = Date.now() - 30 * 24 * 60 * 60 * 1000;
                    setData({
                        ...initialData,
                        ...stored,
                        "contents": (stored.contents ?? initialData.contents).filter(
                            (item) => !item.deletedAt || Date.parse(item.deletedAt) > cutoff
                        )
                    });
                }
            })
            .catch((error: unknown) => console.warn("Could not read local preview data", error))
            .finally(() => {
                if (active) setReady(true);
            });

        return () => {
            active = false;
        };
    }, []);

    useEffect(() => {
        if (!ready) return;
        writes.current = writes.current
            .then(() => AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(data)))
            .catch((error: unknown) => console.warn("Could not persist local preview data", error));
    }, [data, ready]);

    const update = useCallback((change: Update) => {
        setData((previous) => (typeof change === "function" ? change(previous) : { ...previous, ...change }));
    }, []);
    const remove = useCallback(
        (id: string) =>
            update((d) => {
                if (!d.contents.some((item) => item.id === id && !item.deletedAt)) return d;

                return {
                    ...d,
                    "contents": d.contents.map((item) =>
                        item.id === id ? { ...item, "deletedAt": new Date().toISOString() } : item
                    ),
                    "savedCount": Math.max(0, d.savedCount - 1)
                };
            }),
        [update]
    );
    const restore = useCallback(
        (id: string) =>
            update((d) => {
                if (!d.contents.some((item) => item.id === id && item.deletedAt)) return d;

                return {
                    ...d,
                    "contents": d.contents.map((item) => (item.id === id ? { ...item, "deletedAt": undefined } : item)),
                    "savedCount": d.savedCount + 1
                };
            }),
        [update]
    );
    const reset = useCallback(() => {
        previewPasswordRef.current = "";
        setData({ ...initialData, "onboarded": true, "contents": [], "notices": [], "savedCount": 0, "searchHistory": [] });
    }, []);

    return <Context.Provider value={{ data, ready, update, remove, restore, reset, previewPasswordRef }}>
        {children}
    </Context.Provider>;
}

export function useUserData() {
    const context = useContext(Context);
    if (!context) throw new Error("UserDataProvider is required");

    return context;
}

export function formatDate(value: string) {
    const date = new Date(value);

    return new Intl.DateTimeFormat("sv-SE", { "timeZone": "Asia/Seoul" }).format(date).replaceAll("-", ".");
}
