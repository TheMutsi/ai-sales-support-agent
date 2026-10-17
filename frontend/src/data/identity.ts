import type { Api } from "./api";
import type { Auth } from "./auth";
import type { Chat } from "./chat";

/**
 * Identifying with a one-time code: ask for the email, check the code, then answer the message
 * that was waiting. The code goes to the identity endpoint, never through the chat, so it does
 * not reach the model or its traces. Failures throw: the form decides what to tell the visitor.
 */
export function createIdentity(api: Api, auth: Auth, chat: Chat) {
  return {
    requestCode: (email: string) => api.requestOtp(email),
    async verify(email: string, code: string) {
      auth.adopt(await api.verifyOtp(email, code, auth.currentToken()));
      await chat.resume();
    },
  };
}

export type Identity = ReturnType<typeof createIdentity>;
