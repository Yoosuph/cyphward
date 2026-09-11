/** Minimal JSON syntax highlighter for the STRATA codebox style. */
export function highlightJSON(obj: unknown): string {
  return JSON.stringify(obj, null, 2)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/"([^"]+)":/g, '<span class="pk">"$1"</span>:')
    .replace(/: "([^"]*)"/g, ': <span class="ps">"$1"</span>')
    .replace(/: (-?\d+(?:\.\d+)?)/g, ': <span class="pn">$1</span>');
}
