import { useEffect, useState } from "react";
import type { Card, CardImage } from "../data/types";
import { ChevronRight } from "./icons";

interface Handlers {
  /** An action card was chosen: send its message as the visitor. */
  onPick: (message: string) => void;
  /** A product's pictures were chosen: show them large (the first one first). */
  onZoom: (images: CardImage[]) => void;
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
        ) : card.type === "divider" ? (
          <div key={card.id} className="mew-divider" role="separator">
            <span />
            {card.label && <b>{card.label}</b>}
            <span />
          </div>
        ) : (
          <div key={card.id} className="mew-card mew-product">
            <button
              type="button"
              className="mew-product-image"
              aria-label={`Enlarge ${card.image.alt}`}
              onClick={() => onZoom([card.image, ...(card.more_images ?? [])].filter((i) => i.url))}
            >
              {card.more_images?.[0]?.url && (
                <img className="mew-stack-back" src={card.more_images[0].url} alt="" loading="lazy" />
              )}
              {card.image.url && <img className="mew-stack-front" src={card.image.url} alt={card.image.alt} loading="lazy" />}
            </button>
            <span className="mew-card-text">
              {card.badge && <span className="mew-card-badge">{card.badge}</span>}
              <strong>{card.name}</strong>
              {(card.price || card.compare_price) && (
                <span className="mew-price-row">
                  {card.compare_price && <s className="mew-compare">{card.compare_price}</s>}
                  {card.price && <span className="mew-price">{card.price}</span>}
                </span>
              )}
              {card.subtitle && <small>{card.subtitle}</small>}
            </span>
          </div>
        ),
      )}
    </div>
  );
}

/** A picture shown large over the panel; Escape, the backdrop or the button close it. */
export function Lightbox({ images, onClose }: { images: CardImage[]; onClose: () => void }) {
  const [shown, setShown] = useState(0);
  const image = images[shown] ?? images[0];
  // Closing puts the focus back where it was (the picture that was chosen). Read while rendering,
  // before the close button takes the focus.
  const [opener] = useState(() => document.activeElement as HTMLElement | null);
  useEffect(() => () => opener?.focus?.(), [opener]);
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
      {images.length > 1 && (
        <div className="mew-lightbox-thumbs" onClick={(event) => event.stopPropagation()}>
          {images.map((other, index) => (
            <button
              key={other.url}
              type="button"
              aria-label={`Show picture ${index + 1}`}
              aria-current={index === shown ? "true" : undefined}
              onClick={() => setShown(index)}
            >
              <img src={other.url} alt="" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
