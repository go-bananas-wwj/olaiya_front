/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#f6f5fa',
        card: '#ffffff',
        ink: '#1c1a2e',
        'ink-2': '#5a5670',
        'ink-3': '#9a96b0',
        brand: '#6d4bd8',
        'brand-dark': '#4b3587',
        'brand-deep': '#2a1f4d',
        'brand-soft': '#efeaff',
        ok: '#0e9f6e',
        'ok-soft': '#e3f6ee',
        warn: '#b7791f',
        'warn-soft': '#fdf3e0',
        line: '#e8e6f0',
      },
      borderRadius: {
        card: '14px',
      },
      boxShadow: {
        card: '0 1px 3px rgba(28,26,46,.06), 0 8px 24px rgba(28,26,46,.06)',
      },
      fontFamily: {
        sans: ['-apple-system', 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
