/** @type {import('tailwindcss').Config} */
export default {
  content: ['./renderer/index.html', './renderer/src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // 全部讀 CSS variable(in index.css)— light / dark 由 html.dark 切
        bg: {
          base: 'var(--bg-base)',
          panel: 'var(--bg-panel)',
          input: 'var(--bg-input)',
          hover: 'var(--bg-hover)',
        },
        fg: {
          base: 'var(--fg-base)',
          muted: 'var(--fg-muted)',
          subtle: 'var(--fg-subtle)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          hover: 'var(--accent-hover)',
        },
        success: 'var(--success)',
        error: 'var(--error)',
        warning: 'var(--warning)',
      },
      fontFamily: {
        sans: [
          'system-ui', '-apple-system', 'BlinkMacSystemFont',
          '"Segoe UI"', 'Roboto', 'sans-serif',
        ],
        mono: ['ui-monospace', 'SFMono-Regular', '"SF Mono"', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
}
