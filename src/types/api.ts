import type { Notice, SavedContent } from "./content";

export type User = { id: string; email: string; nickname: string; notificationsEnabled: boolean; };
export type Session = { token: string; expiresAt: string; user: User; };
export type Snapshot = { user: User; contents: SavedContent[]; notices: Notice[]; searchHistory: string[]; savedCount: number; };
export type Registration = { email: string; password: string; nickname: string; requiredConsent: boolean; notificationsEnabled: boolean; };
