import { memo } from 'react';
import { Sparkles } from 'lucide-react';

interface Props {
  open: boolean;
  onClick: () => void;
}

export const CyphBotFloatingButton = memo(function CyphBotFloatingButton({
  open,
  onClick,
}: Props) {
  // Never show when chatbot is already open, and strictly mobile only (md:hidden)
  if (open) return null;

  return (
    <button
      onClick={onClick}
      className="fixed bottom-[74px] right-3.5 z-[80] md:hidden group flex items-center gap-1.5 px-3.5 py-2 rounded-full border border-accent/40 hover:border-accent bg-raised/95 hover:bg-inset text-ink shadow-xl hover:scale-105 active:scale-95 transition-all duration-200 select-none btn-tactile backdrop-blur-md"
      title="Open CyphBot Sovereign AI (⌘J)"
      aria-label="Open CyphBot Sovereign AI"
    >
      <div className="relative flex items-center justify-center">
        <Sparkles
          size={14}
          className="text-accent transition-transform group-hover:rotate-12 duration-200"
        />
        <span className="absolute -top-1 -right-1 w-1.5 h-1.5 rounded-full bg-ok animate-pulse" />
      </div>
      <span className="font-mono text-[11px] font-bold tracking-wider uppercase text-ink">
        CYPHBOT
      </span>
      <span className="text-[9px] mono px-1.5 py-0.5 rounded bg-inset text-soft border border-line">
        ⌘J
      </span>
    </button>
  );
});

export default CyphBotFloatingButton;
