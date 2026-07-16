/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Deep indigo-violet brand scale — replaces the old flat 5-stop
        // palette with a full range so hover/active/border states don't
        // have to reuse the same one or two shades everywhere.
        brand: {
          50: "#f0f1ff",
          100: "#e2e4ff",
          200: "#c8cbff",
          300: "#a4a4ff",
          400: "#8377fb",
          500: "#6c56f0",
          600: "#5a3fdc",
          700: "#4a30b8",
          800: "#3d2a94",
          900: "#332677",
          950: "#1f1650",
        },
        // Warm neutral surface scale used for backgrounds/cards instead of
        // stock Tailwind slate, for a slightly less "default template" feel.
        surface: {
          0: "#ffffff",
          50: "#f8f8fb",
          100: "#f1f1f7",
          200: "#e5e5ee",
          300: "#d4d4e2",
          400: "#a8a8bf",
          500: "#7b7b95",
          600: "#5b5b72",
          700: "#43435a",
          800: "#2c2c40",
          900: "#1b1b2b",
          950: "#111119",
        },
        accent: {
          400: "#f5b95b",
          500: "#eda233",
          600: "#d3821c",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["\"Plus Jakarta Sans\"", "Inter", "ui-sans-serif", "sans-serif"],
        mono: ["\"JetBrains Mono\"", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      boxShadow: {
        soft: "0 1px 2px 0 rgba(27, 27, 43, 0.04), 0 2px 8px -2px rgba(27, 27, 43, 0.06)",
        card: "0 1px 3px 0 rgba(27, 27, 43, 0.06), 0 8px 24px -8px rgba(27, 27, 43, 0.10)",
        lift: "0 12px 32px -12px rgba(51, 38, 119, 0.35)",
        glow: "0 0 0 1px rgba(108, 86, 240, 0.15), 0 8px 24px -6px rgba(108, 86, 240, 0.35)",
      },
      backgroundImage: {
        "brand-gradient": "linear-gradient(135deg, #6c56f0 0%, #4a30b8 100%)",
        "app-gradient": "radial-gradient(circle at 15% 0%, #f0f1ff 0%, #f8f8fb 45%, #f8f8fb 100%)",
      },
      animation: {
        "fade-in": "fadeIn 0.25s ease-out",
        "fade-in-up": "fadeInUp 0.35s cubic-bezier(0.16, 1, 0.3, 1)",
        "pulse-soft": "pulseSoft 1.6s ease-in-out infinite",
      },
      keyframes: {
        fadeIn: { "0%": { opacity: 0 }, "100%": { opacity: 1 } },
        fadeInUp: {
          "0%": { opacity: 0, transform: "translateY(6px)" },
          "100%": { opacity: 1, transform: "translateY(0)" },
        },
        pulseSoft: {
          "0%, 100%": { opacity: 1 },
          "50%": { opacity: 0.45 },
        },
      },
    },
  },
  plugins: [],
};
