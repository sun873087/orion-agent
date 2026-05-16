/** @type {import('tailwindcss').Config} */
export default {
  content: ['./renderer/index.html', './renderer/src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Cowork 預設 dark theme(桌機 app 慣例),lighter palette 可選
        bg: {
          base: '#0d1117',      // 主背景(GitHub dark)
          panel: '#161b22',     // panel / card 背景
          input: '#1c2128',     // input 背景
          hover: '#21262d',
        },
        fg: {
          base: '#e6edf3',      // 主文字
          muted: '#7d8590',     // 次要文字
          subtle: '#484f58',    // 提示
        },
        accent: {
          DEFAULT: '#2f81f7',   // 強調色(send button、active state)
          hover: '#388bfd',
        },
        success: '#3fb950',
        error: '#f85149',
        warning: '#d29922',
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
