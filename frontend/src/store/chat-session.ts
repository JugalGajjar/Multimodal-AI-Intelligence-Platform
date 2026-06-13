import { create } from "zustand";

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

// Not persisted — a hard refresh starts a new chat. Past chats are in /chats.
export const useChatSessionStore = create<ChatSessionState>()((set) => ({
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
}));

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
