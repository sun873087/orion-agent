/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  // 'class' strategy:由 lib/theme.ts 動態加 'dark' class 到 <html>。
  // 讓 prefers-color-scheme + user override 走同一條路。
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // 顏色全綁 CSS var → 暗色由 index.css 的 .dark 覆寫。
        // <alpha-value> 讓 bg-claude-cream/50 之類 alpha 修飾仍 work。
        claude: {
          cream: 'rgb(var(--c-cream) / <alpha-value>)',
          panel: 'rgb(var(--c-panel) / <alpha-value>)',
          border: 'rgb(var(--c-border) / <alpha-value>)',
          borderSoft: 'rgb(var(--c-border-soft) / <alpha-value>)',
          text: 'rgb(var(--c-text) / <alpha-value>)',
          textDim: 'rgb(var(--c-text-dim) / <alpha-value>)',
          textFaint: 'rgb(var(--c-text-faint) / <alpha-value>)',
          orange: 'rgb(var(--c-orange) / <alpha-value>)',
          orangeHover: 'rgb(var(--c-orange-hover) / <alpha-value>)',
          orangeSoft: 'rgb(var(--c-orange-soft) / <alpha-value>)',
          code: 'rgb(var(--c-code) / <alpha-value>)',
          codeText: 'rgb(var(--c-code-text) / <alpha-value>)',
        },
      },
      fontFamily: {
        sans: [
          'ui-sans-serif',
          '-apple-system',
          'BlinkMacSystemFont',
          'Inter',
          'Helvetica Neue',
          'sans-serif',
        ],
        serif: ['ui-serif', 'Georgia', 'Cambria', 'Times New Roman', 'serif'],
        mono: [
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Monaco',
          'Consolas',
          'monospace',
        ],
      },
      boxShadow: {
        soft: '0 1px 2px 0 rgba(0, 0, 0, 0.04), 0 0 0 1px rgba(0, 0, 0, 0.04)',
        input: '0 0 0 1px rgba(0, 0, 0, 0.06), 0 1px 3px 0 rgba(0, 0, 0, 0.04)',
        modal:
          '0 25px 50px -12px rgba(0, 0, 0, 0.15), 0 0 0 1px rgba(0, 0, 0, 0.05)',
      },
      animation: {
        'fade-in': 'fadeIn 150ms ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
