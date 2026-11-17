import { useEffect, useState } from "react";
import { safeAbsoluteUrl } from "../data/api";
import type { Card, CardImage } from "../data/types";
import { ChevronRight } from "./icons";

export type ActionCard = Extract<Card, { type: "action" }>;

interface Handlers {
  onPick: (card: ActionCard) => void;
  onZoom: (images: CardImage[]) => void;
}

type RecommendationCard = Extract<Card, { type: "recommendation" }>;
type CardItem = Exclude<Card, RecommendationCard> | RecommendationCard[];

function groupRecommendations(cards: Card[]): CardItem[] {
  return cards.reduce<CardItem[]>((items, card) => {
    const last = items[items.length - 1];
    if (card.type !== "recommendation") return [...items, card];
    if (Array.isArray(last)) return [...items.slice(0, -1), [...last, card]];
    return [...items, [card]];
  }, []);
}

function Stars({ rating }: { rating: number }) {
  const filled = Math.min(5, Math.max(0, rating)) * 20;
  return (
    <span className="mew-stars" role="img" aria-label={`${Math.round(rating * 10) / 10} out of 5`}>
      <span className="mew-stars-fill" style={{ width: `${filled}%` }}>
        ★★★★★
      </span>
      ★★★★★
    </span>
  );
}

function RecommendationView({ card }: { card: RecommendationCard }) {
  const imageUrl = safeAbsoluteUrl(card.image?.url, "https");
  const linkUrl = safeAbsoluteUrl(card.url, "http-https");
  const body = (
    <>
      {imageUrl && <img src={imageUrl} alt={card.image?.alt ?? ""} loading="lazy" />}
      {card.offer_label && <span className="mew-card-badge">{card.offer_label}</span>}
      <strong>{card.title}</strong>
      {card.rating != null && <Stars rating={card.rating} />}
      {(card.price || card.compare_price) && (
        <span className="mew-price-row">
          {card.compare_price && <s className="mew-compare">{card.compare_price}</s>}
          {card.price && <span className="mew-price">{card.price}</span>}
        </span>
      )}
      {card.description && <small>{card.description}</small>}
    </>
  );
  return (
    <div className="mew-card mew-recommendation">
      {linkUrl ? (
        <a href={linkUrl} target="_blank" rel="noopener noreferrer">
          {body}
        </a>
      ) : (
        body
      )}
      {card.why && <span className="mew-why">{card.why}</span>}
    </div>
  );
}

export function Cards({ cards, active, onPick, onZoom }: { cards: Card[]; active: boolean } & Handlers) {
  return (
    <div className="mew-cards">
      {groupRecommendations(cards).map((card) =>
        Array.isArray(card) ? (
          <div key={card[0].id} className="mew-carousel">
            {card.map((item) => (
              <RecommendationView key={item.id} card={item} />
            ))}
          </div>
        ) : card.type === "action" ? (
          <button
            key={card.id}
            type="button"
            className="mew-card mew-action"
            disabled={!active}
            onClick={() => onPick(card)}
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
            {card.label && <b className={card.variant === "heading" ? "mew-divider-title" : undefined}>{card.label}</b>}
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

export function Lightbox({ images, onClose }: { images: CardImage[]; onClose: () => void }) {
  const [shown, setShown] = useState(0);
  const image = images[shown] ?? images[0];
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
