import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        bg: "hsl(var(--bg))",
        panel: "hsl(var(--panel))",
        text: "hsl(var(--text))",
        muted: "hsl(var(--muted))",
        accent: "hsl(var(--accent))",
        warn: "hsl(var(--warn))",
        ok: "hsl(var(--ok))",
        risk: "hsl(var(--risk))"
      },
      boxShadow: {
        glass: "0 14px 34px rgba(15, 23, 42, 0.06)"
      },
      backgroundImage: {
        "hero-grid":
          "radial-gradient(circle at 14% 10%, rgba(37,99,235,0.08), transparent 24%), radial-gradient(circle at 88% 12%, rgba(20,184,166,0.06), transparent 28%), linear-gradient(180deg, #f9fbff 0%, #f4f7fb 100%)"
      },
      animation: {
        "rise-in": "riseIn 0.45s ease-out both",
        ribbon: "ribbon 18s linear infinite",
        pulsegrid: "pulsegrid 3.5s ease-in-out infinite"
      },
      keyframes: {
        riseIn: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" }
        },
        ribbon: {
          "0%": { transform: "translateX(0)" },
          "100%": { transform: "translateX(-50%)" }
        },
        pulsegrid: {
          "0%, 100%": { opacity: "0.35" },
          "50%": { opacity: "0.7" }
        }
      }
    }
  },
  plugins: []
};

export default config;
