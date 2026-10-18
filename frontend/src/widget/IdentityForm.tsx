import { useState, type FormEvent } from "react";
import type { Identity } from "../data/identity";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const CODE = /^[0-9]{6}$/;
// Exactly what the server accepts: 20 ASCII letters or digits.
const ORDER_ID = /^[A-Za-z0-9]{20}$/;

type Step = "email" | "choose" | "code" | "order";

/**
 * One card, outside the chat bubbles. The email always comes first; then the visitor proves it
 * with a code we email them, or with the number of one of their orders (when the shop allows
 * both they choose; with only one it goes straight to it). Whether the address or the order
 * exists is never revealed: the server always answers the same, so each step is shown either way
 * and a failure gets one generic message.
 */
export function IdentityForm({ identity, methods }: { identity: Identity; methods: string[] }) {
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [orderId, setOrderId] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const hasCode = methods.includes("otp");
  const hasOrder = methods.includes("order_id");

  async function run(work: () => Promise<void>, failure: string) {
    setBusy(true);
    setProblem(null);
    try {
      await work();
    } catch {
      setProblem(failure);
    } finally {
      setBusy(false);
    }
  }

  const sendCode = () =>
    run(async () => {
      await identity.requestCode(email.trim());
      setStep("code");
    }, "Could not send the code. Try again in a moment.");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || step === "choose") return;
    if (step === "email") {
      if (!EMAIL.test(email.trim())) return setProblem("Enter a valid email.");
      setProblem(null);
      if (hasCode && hasOrder) return setStep("choose");
      return hasCode ? void sendCode() : setStep("order");
    }
    if (step === "code") {
      if (!CODE.test(code)) return setProblem("Enter the 6 digit code.");
      return void run(() => identity.verify(email.trim(), code), "That code did not work.");
    }
    if (!ORDER_ID.test(orderId.trim())) return setProblem("The order number has 20 letters and digits.");
    void run(
      () => identity.verifyOrder(email.trim(), orderId.trim()),
      "We couldn't match that email and order number.",
    );
  }

  return (
    <form className="mew-identity" onSubmit={submit}>
      {step === "email" && (
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </label>
      )}
      {step === "choose" && (
        <>
          <span>How do you want to prove it is you?</span>
          <button type="button" disabled={busy} onClick={() => void sendCode()}>
            Email me a code
          </button>
          <button type="button" disabled={busy} onClick={() => setStep("order")}>
            I have my order number
          </button>
        </>
      )}
      {step === "code" && (
        <label>
          Code we emailed to {email}
          <input
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            inputMode="numeric"
            autoComplete="one-time-code"
          />
        </label>
      )}
      {step === "order" && (
        <label>
          Order number
          <input
            value={orderId}
            onChange={(e) => setOrderId(e.target.value.replace(/[^A-Za-z0-9]/g, "").slice(0, 20))}
            autoComplete="off"
            spellCheck={false}
          />
        </label>
      )}
      {problem && <div role="alert">{problem}</div>}
      {step !== "choose" && (
        <button type="submit" disabled={busy}>
          {step === "email" ? (hasCode && !hasOrder ? "Send code" : "Continue") : step === "code" ? "Verify" : "Check order"}
        </button>
      )}
    </form>
  );
}
