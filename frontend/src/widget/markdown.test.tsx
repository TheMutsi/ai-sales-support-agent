import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { Markdown } from "./markdown";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
const container = document.createElement("div");
document.body.appendChild(container);
const render = (text: string) => {
  root = createRoot(container);
  act(() => root!.render(<Markdown text={text} />));
  return container;
};
afterEach(() => act(() => root?.unmount()));

describe("Markdown", () => {
  it("renders the answer the model actually wrote: bold and a bulleted list", () => {
    const el = render("We offer three plans:\n\n- **Starter**: $29.00 per month\n- **Pro**: $99.00 per month\n\nWould you like more?");
    expect([...el.querySelectorAll("li")].map((li) => li.textContent)).toEqual(["Starter: $29.00 per month", "Pro: $99.00 per month"]);
    expect([...el.querySelectorAll("strong")].map((s) => s.textContent)).toEqual(["Starter", "Pro"]);
    expect([...el.querySelectorAll("p")].map((p) => p.textContent)).toEqual(["We offer three plans:", "Would you like more?"]);
    expect(el.textContent).not.toContain("**");
  });

  it("renders numbered lists, inline code and headings as bold", () => {
    const el = render("### Steps\n1. Open `Settings`\n2. Click Save");
    expect(el.querySelector("ol")!.children).toHaveLength(2);
    expect(el.querySelector("code")!.textContent).toBe("Settings");
    expect(el.querySelector("strong")!.textContent).toBe("Steps");
  });

  it("makes links only from http(s) urls, with safe attributes", () => {
    const el = render("[docs](https://a.example/x), [bad](javascript:alert(1)) and https://b.example/y.");
    const links = [...el.querySelectorAll("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://a.example/x", "https://b.example/y"]);
    expect(links.every((a) => a.rel === "noopener noreferrer" && a.target === "_blank")).toBe(true);
    expect(el.textContent).toContain("[bad](javascript:alert(1))");
    expect(el.textContent).toContain("https://b.example/y.");
  });

  it("never inserts markup from the text", () => {
    const el = render('<img src=x onerror="alert(1)"> **<script>alert(1)</script>**');
    expect(el.querySelector("img")).toBeNull();
    expect(el.querySelector("script")).toBeNull();
    expect(el.textContent).toContain('<img src=x onerror="alert(1)">');
  });

  it("leaves an unfinished marker as text while the answer is still streaming", () => {
    expect(render("The **Star").textContent).toBe("The **Star");
  });
});
