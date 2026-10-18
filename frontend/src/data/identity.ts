import type { Api } from "./api";
import type { Auth } from "./auth";
import type { Chat } from "./chat";

/**
 * Identifying: an email plus a proof, either a one-time code or an order number. Both go to the
 * identity endpoints, never through the chat, so they do not reach the model or its traces. Once
 * proven, the message that was waiting is answered. Failures throw: the form decides what to tell
 * the visitor.
 */
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
