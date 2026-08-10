/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // —— 珍珠贝母设计语言（产品详情页）——
        pearl: '#f3ede6',
        'pearl-ink': '#3d2f2a',
        'pearl-ink-2': '#7a6a60',
        'pearl-ink-3': '#a89a8e',
        rosewood: '#b06a8a',
        'rosewood-soft': '#f5e3ec',
        iris: '#8a7ab8',
        'iris-soft': '#e9e4f6',
        mint: '#6fae9e',
        'mint-soft': '#dff0eb',
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
        // 珍珠贝母：标题站酷快乐体 / 正文 Quicksand+Noto Sans SC / 数字 Baloo 2
        display: ['ZCOOL KuaiLe', 'PingFang SC', 'sans-serif'],
        pearl: ['Quicksand', 'Noto Sans SC', 'PingFang SC', 'sans-serif'],
        num: ['Baloo 2', 'Quicksand', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
