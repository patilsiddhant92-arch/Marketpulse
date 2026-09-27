/** @type {import('tailwindcss').Config} */

// Every colour resolves to a CSS variable in src/styles/tokens.css.
const token = (name) => `rgb(var(--c-${name}) / <alpha-value>)`;

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: token('bg'),
        surface: token('surface'),
        'surface-2': token('surface-2'),
        'surface-3': token('surface-3'),
        line: token('line'),
        'line-strong': token('line-strong'),
        fg: token('fg'),
        'fg-2': token('fg-2'),
        'fg-3': token('fg-3'),
        accent: token('accent'),
        up: token('up'),
        down: token('down'),
        warn: token('warn'),
        info: token('info'),
        violet: token('violet'),
        focus: token('focus'),
        'v-favourable': token('v-favourable'),
        'v-constructive': token('v-constructive'),
        'v-mixed': token('v-mixed'),
        'v-weak': token('v-weak'),
        'v-danger': token('v-danger'),
      },
      fontFamily: {
        mono: ['var(--font-mono)'],
        sans: ['var(--font-sans)'],
      },
      fontSize: {
        // 11px is the floor (spec 9); tables sit at 12.5px.
        '2xs': ['11px', '14px'],
        table: ['var(--fs-table)', '16px'],
      },
      height: {
        row: 'var(--row-h)',
        topbar: 'var(--topbar-h)',
        envstrip: 'var(--envstrip-h)',
      },
      width: {
        sidecar: 'var(--sidecar-w)',
      },
      borderRadius: {
        DEFAULT: 'var(--radius)',
      },
    },
  },
  plugins: [],
};
