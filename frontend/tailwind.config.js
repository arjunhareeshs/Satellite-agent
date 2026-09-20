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
      },
      // `animate-spin-slow` is used by Header/Map compass icons but is not
      // one of Tailwind's built-in spin speeds and was previously undefined
      // -- referencing it silently did nothing.
      animation: {
        'spin-slow': 'spin 3s linear infinite',
      },
    },
  },
  // tailwindcss-animate supplies `animate-in`, `slide-in-from-right`,
  // `zoom-in-95` and friends, used by EvidencePanel's drawer,
  // CoChangeGraph/SimilarSites modals, and the map basemap-status pill. None
  // of these classes existed anywhere in this project before, so every
  // "animated" entrance was in fact instant with no transition at all.
  plugins: [require('tailwindcss-animate')],
}
