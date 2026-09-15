/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        command: {
          bg: "#080c14",
          card: "#0d1424",
          cardBorder: "#1e293b",
          sidebar: "#0a0f1d",
          accent: "#06b6d4",
          accentGlow: "rgba(6, 182, 212, 0.15)",
          radar: "#10b981",
          warning: "#f59e0b",
          danger: "#ef4444",
          textMuted: "#94a3b8",
          textBright: "#f8fafc"
        }
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif']
      }
    },
  },
  plugins: [],
}
