import type { Api } from "./api";
import type { Auth } from "./auth";
import type { Chat } from "./chat";

export function createIdentity(api: Api, auth: Auth, chat: Chat) {
  return {
    requestCode: (email: string) => api.requestOtp(email, auth.currentToken()),
    async verify(email: string, code: string) {
      auth.adopt(await api.verifyOtp(email, code, auth.currentToken()));
      await chat.resume();
    },
    async verifyOrder(email: string, orderId: string) {
      auth.adopt(await api.orderLookup(email, orderId, auth.currentToken()));
      await chat.resume();
    },
  };
}

export type Identity = ReturnType<typeof createIdentity>;
