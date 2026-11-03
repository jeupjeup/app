import { requireOptionalNativeModule } from "expo";
import type { SharePayload } from "expo-sharing";
import { useEffect, useRef, useState } from "react";
import { AppState, Linking } from "react-native";
import AddContentDialog from "@/components/AddContentDialog";

type IncomingSharingModule = {
    getSharedPayloads: () => SharePayload[];
    clearSharedPayloads: () => void;
};

function sharedUrl(payloads: SharePayload[]) {
    // Prefer a dedicated URL over the caption that may accompany it.
    const values = [
        ...payloads.filter(payload => payload.shareType === "url"),
        ...payloads.filter(payload => !payload.shareType || payload.shareType === "text")
    ];
    for (const payload of values) {
        const matches = payload.value?.match(/https?:\/\/[^\s<>"']+/gi) ?? [];
        for (const candidate of matches) {
            try {
                const url = new URL(candidate);
                if (["http:", "https:"].includes(url.protocol) && url.hostname) return candidate;
            } catch {
                // A caption may contain malformed URLs; continue to the next one.
            }
        }
    }
    return null;
}

export default function IncomingShareDialog() {
    const [incoming, setIncoming] = useState<{ url: string; id: number; } | null>(null);
    const sequence = useRef(0);

    useEffect(() => {
        // Keep existing development builds usable until the new native build is installed.
        const sharing = requireOptionalNativeModule<IncomingSharingModule>("ExpoSharing");
        if (!sharing?.getSharedPayloads || !sharing.clearSharedPayloads) return;

        const receive = () => {
            try {
                const payloads = sharing.getSharedPayloads();
                if (!payloads.length) return;
                const url = sharedUrl(payloads);
                if (url) setIncoming({ url, id: ++sequence.current });
                // Retain the copied URL in React state, and allow identical future shares.
                sharing.clearSharedPayloads();
            } catch {
                console.warn("공유받은 링크를 읽지 못했습니다.");
            }
        };
        receive();
        const appState = AppState.addEventListener("change", state => {
            if (state === "active") receive();
        });
        const links = Linking.addEventListener("url", ({ url }) => {
            try {
                if (new URL(url).hostname === "expo-sharing") receive();
            } catch {
                // Unrelated native intents do not contain share payloads.
            }
        });
        return () => { appState.remove(); links.remove(); };
    }, []);

    if (!incoming) return null;
    return <AddContentDialog
        key={incoming.id}
        visible
        initialUrl={incoming.url}
        onClose={() => setIncoming(null)}
    />;
}
