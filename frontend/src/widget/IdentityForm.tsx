import { useState, type FormEvent } from "react";
import type { Identity } from "../data/identity";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const CODE = /^[0-9]{6}$/;

/**
 * Two steps in one card, outside the chat bubbles: the email, then the six digit code. Whether
 * the address belongs to a customer is never revealed (the server always answers the same), so
 * the code step is shown either way and a wrong code gets one generic message.
 */
export function IdentityForm({ identity }: { identity: Identity }) {
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const valid = step === "email" ? EMAIL.test(email.trim()) : CODE.test(code);
    if (!valid) return setProblem(step === "email" ? "Enter a valid email." : "Enter the 6 digit code.");
    setBusy(true);
    setProblem(null);
    try {
      if (step === "email") {
        await identity.requestCode(email.trim());
        setStep("code");
      } else {
        await identity.verify(email.trim(), code);
      }
    } catch {
      setProblem(step === "email" ? "Could not send the code. Try again in a moment." : "That code did not work.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="mew-identity" onSubmit={submit}>
      {step === "email" ? (
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </label>
      ) : (
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
      {problem && <div role="alert">{problem}</div>}
      <button type="submit" disabled={busy}>{step === "email" ? "Send code" : "Verify"}</button>
    </form>
  );
}
