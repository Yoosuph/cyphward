/** @type {import('tailwindcss').Config} */
function withOpacity(varName, rgbVarName) {
  return ({ opacityValue }) => {
    if (opacityValue !== undefined) {
      return `rgba(var(${rgbVarName}), ${opacityValue})`;
    }
    return `var(${varName})`;
  };
}

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: withOpacity('--bg', '--bg-rgb'),
        raised: withOpacity('--raised', '--raised-rgb'),
        inset: withOpacity('--inset', '--inset-rgb'),
        ink: withOpacity('--ink', '--ink-rgb'),
        soft: withOpacity('--soft', '--soft-rgb'),
        line: withOpacity('--line', '--line-rgb'),
        'line-strong': withOpacity('--line-strong', '--line-strong-rgb'),
        linestrong: withOpacity('--line-strong', '--line-strong-rgb'),
        accent: withOpacity('--accent', '--accent-rgb'),
        ok: withOpacity('--ok', '--ok-rgb'),
        warn: withOpacity('--warn', '--warn-rgb'),
      },
      fontFamily: {
        display: ['Fraunces', 'Georgia', 'serif'],
        body: ['"Space Grotesk"', '"Helvetica Neue"', 'Arial', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
};
