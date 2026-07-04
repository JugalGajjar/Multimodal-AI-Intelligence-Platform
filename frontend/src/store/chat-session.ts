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
  /** Per-question toggles. Persisted so navigating between dashboard pages
   *  doesn't quietly re-enable RAG or drop Web mode mid-conversation. Reset
   *  to defaults on New Chat and on sign-out — a fresh conversation starts
   *  with the "safe" grounded-in-your-docs setup, not whatever the last
   *  thread happened to be using. */
  useRag: boolean;
  useWeb: boolean;
  setChatId: (id: string) => void;
  addTurn: (question: string, response: ChatResponse) => void;
  setUseRag: (v: boolean) => void;
  setUseWeb: (v: boolean) => void;
  /** Atomically replace the session with a chat loaded from the Chats page.
   *  Used to resume an old thread from /dashboard. Turns arrive already
   *  paired (question + response). */
  hydrateFromChat: (
    chatId: string,
    turns: Array<{ question: string; response: ChatResponse }>,
  ) => void;
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
      useRag: true,
      useWeb: false,
      setChatId: (id) => set({ chatId: id }),
      addTurn: (question, response) =>
        set((state) => ({
          turns: [
            ...state.turns,
            { id: `turn-${++turnCounter}`, question, response },
          ],
        })),
      setUseRag: (v) => set({ useRag: v }),
      setUseWeb: (v) => set({ useWeb: v }),
      hydrateFromChat: (chatId, incoming) =>
        set({
          chatId,
          turns: incoming.map(({ question, response }) => ({
            id: `turn-${++turnCounter}`,
            question,
            response,
          })),
        }),
      reset: () =>
        set({ chatId: null, turns: [], useRag: true, useWeb: false }),
    }),
    {
      name: "mmap-chat-session",
      storage: createJSONStorage(() =>
        typeof window === "undefined" ? undefined! : window.sessionStorage,
      ),
      partialize: (state) => ({
        chatId: state.chatId,
        turns: state.turns,
        useRag: state.useRag,
        useWeb: state.useWeb,
      }),
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
