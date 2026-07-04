import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { ChatResponse } from "@/lib/chat-api";
import { useAuthStore } from "@/store/auth";

export type ChatTurn = {
  id: string;
  question: string;
  response: ChatResponse;
};

type ChatSessionState = {
  chatId: string | null;
  turns: ChatTurn[];
  setChatId: (id: string) => void;
  addTurn: (question: string, response: ChatResponse) => void;
  reset: () => void;
};

let turnCounter = 0;

// Persisted to sessionStorage so the thread survives dashboard nav (and hard
// refreshes within the same tab). Closing the tab or opening a new one starts
// a fresh chat — the persisted chat still lives server-side on the Chats page.
// Reset fires explicitly (New Chat button, sign-out, first-turn error).
export const useChatSessionStore = create<ChatSessionState>()(
  persist(
    (set) => ({
      chatId: null,
      turns: [],
      setChatId: (id) => set({ chatId: id }),
      addTurn: (question, response) =>
        set((state) => ({
          turns: [
            ...state.turns,
            { id: `turn-${++turnCounter}`, question, response },
          ],
        })),
      reset: () => set({ chatId: null, turns: [] }),
    }),
    {
      name: "mmap-chat-session",
      storage: createJSONStorage(() =>
        typeof window === "undefined" ? undefined! : window.sessionStorage,
      ),
      partialize: (state) => ({ chatId: state.chatId, turns: state.turns }),
    },
  ),
);

// Wipe on sign-out so the next user doesn't see the previous one's chat.
if (typeof window !== "undefined") {
  let wasAuthed = useAuthStore.getState().isAuthenticated;
  useAuthStore.subscribe((state) => {
    if (wasAuthed && !state.isAuthenticated) {
      useChatSessionStore.getState().reset();
    }
    wasAuthed = state.isAuthenticated;
  });
}
