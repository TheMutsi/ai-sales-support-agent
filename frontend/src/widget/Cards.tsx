import { useEffect } from "react";
import type { Card, CardImage } from "../data/types";
import { ChevronRight } from "./icons";

interface Handlers {
  /** An action card was chosen: send its message as the visitor. */
  onPick: (message: string) => void;
  /** A product picture was chosen: show it large. */
  onZoom: (image: CardImage) => void;
}

/**
 * The cards of one reply. Action cards only work on the latest reply (an old offer must not be
 * taken again), and not while an answer is being written.
 */
export function Cards({ cards, active, onPick, onZoom }: { cards: Card[]; active: boolean } & Handlers) {
  return (
    <div className="mew-cards">
      {cards.map((card) =>
        card.type === "action" ? (
          <button
            key={card.id}
            type="button"
            className="mew-card mew-action"
            disabled={!active}
            onClick={() => onPick(card.message)}
          >
            <span className="mew-card-text">
              {card.badge && <span className="mew-card-badge">{card.badge}</span>}
              <strong>{card.title}</strong>
              {card.subtitle && <small>{card.subtitle}</small>}
            </span>
            <ChevronRight />
          </button>
        ) : (
          <div key={card.id} className="mew-card mew-product">
            <button
              type="button"
              className="mew-product-image"
              aria-label={`Enlarge ${card.image.alt}`}
              onClick={() => onZoom(card.image)}
            >
              <img src={card.image.url} alt={card.image.alt} loading="lazy" />
            </button>
            <span className="mew-card-text">
              {card.badge && <span className="mew-card-badge">{card.badge}</span>}
              <strong>{card.name}</strong>
              {card.price && <span className="mew-price">{card.price}</span>}
              {card.subtitle && <small>{card.subtitle}</small>}
            </span>
          </div>
        ),
      )}
    </div>
  );
}

/** A picture shown large over the panel; Escape, the backdrop or the button close it. */
export function Lightbox({ image, onClose }: { image: CardImage; onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="mew-lightbox" role="dialog" aria-modal="true" aria-label={image.alt} onClick={onClose}>
      <button type="button" className="mew-lightbox-close" aria-label="Close picture" onClick={onClose} autoFocus>
        ×
      </button>
      <img src={image.url} alt={image.alt} onClick={(event) => event.stopPropagation()} />
    </div>
  );
}
