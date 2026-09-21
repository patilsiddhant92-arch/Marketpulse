/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#080c14',
        surface: '#101721',
        'surface-raised': '#151f2b',
        border: '#263447',
        primary: '#d8ac3d',
        bullish: '#10b981',
        bearish: '#f43f5e',
        muted: '#98a7ba',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'IBM Plex Mono', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
