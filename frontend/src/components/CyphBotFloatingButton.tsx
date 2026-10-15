import { memo } from 'react';
import { Sparkles } from 'lucide-react';

interface Props {
  open: boolean;
  onClick: () => void;
}

/**
 * Phone-width CyphBot trigger, shown on every app page. A compact round
 * button that sits just above the dock (same safe-area offset), so it stays
 * visible without covering page actions. From 640px up the topbar button
 * takes over.
 */
export const CyphBotFloatingButton = memo(function CyphBotFloatingButton({
  open,
  onClick,
}: Props) {
  if (open) return null;

  return (
    <button
      type="button"
      onClick={onClick}
      className="cyphbot-fab sm:hidden"
      title="Ask CyphBot"
      aria-label="Open CyphBot"
    >
      <Sparkles size={19} strokeWidth={2} aria-hidden="true" />
      <span className="cyphbot-fab-dot" aria-hidden="true" />
    </button>
  );
});

export default CyphBotFloatingButton;
