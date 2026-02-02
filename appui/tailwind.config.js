/**
 * Tailwind CSS configuration for AI Resume Builder UI
 * Includes custom color palette, typography, and spacing system per design spec
 */
module.exports = {
  content: [
    './src/**/*.{js,ts,jsx,tsx}',
    './src/app/**/*.{js,ts,jsx,tsx}',
    './src/components/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#4F46E5',
          dark: '#4338CA',
        },
        success: { DEFAULT: '#16A34A' },
        warning: { DEFAULT: '#F59E0B' },
        error: { DEFAULT: '#DC2626' },
        gray: {
          900: '#111827',
          700: '#374151',
          500: '#6B7280',
          300: '#D1D5DB',
          100: '#F3F4F6',
          50: '#F9FAFB',
        },
        background: '#FFFFFF',
        surface: '#FAFAFA',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui'],
        mono: ['Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      fontSize: {
        'display-h1': ['2.25rem', { lineHeight: '2.75rem', fontWeight: '600' }], // 36/44
        h2: ['1.75rem', { lineHeight: '2.25rem', fontWeight: '600' }], // 28/36
        h3: ['1.375rem', { lineHeight: '1.875rem', fontWeight: '500' }], // 22/30
        'body-lg': ['1rem', { lineHeight: '1.5rem', fontWeight: '400' }], // 16/24
        'body-sm': ['0.875rem', { lineHeight: '1.25rem', fontWeight: '400' }], // 14/20
        caption: ['0.75rem', { lineHeight: '1rem', fontWeight: '400' }], // 12/16
        mono: ['0.8125rem', { lineHeight: '1.125rem', fontWeight: '400' }], // 13/18
      },
      spacing: {
        1: '4px',
        2: '8px',
        3: '12px',
        4: '16px',
        6: '24px',
        8: '32px',
        12: '48px',
      },
    },
  },
  plugins: [],
};
