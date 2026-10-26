// Знак Компаса: плитка цвета действий, кольцо и стрелка (север белый, юг мятный), как на обложке материалов
export function Logo() {
  return (
    <span className="logo">
      <svg width="28" height="28" viewBox="0 0 120 120" aria-hidden>
        <rect width="120" height="120" rx="30" className="logo-tile" />
        <circle cx="60" cy="60" r="38" fill="none" stroke="#fff" strokeWidth="8" />
        <g transform="rotate(28 60 60)">
          <path d="M60 22 L72 60 L48 60 Z" fill="#fff" />
          <path d="M48 60 L72 60 L60 98 Z" className="logo-south" />
        </g>
        <circle cx="60" cy="60" r="8" className="logo-hub" />
      </svg>
      <span className="logo-text">Компас</span>
    </span>
  )
}
