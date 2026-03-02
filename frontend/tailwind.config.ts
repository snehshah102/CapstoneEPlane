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
        glass: "0 10px 40px rgba(4, 9, 18, 0.35)"
      },
      backgroundImage: {
        "hero-grid":
          "radial-gradient(circle at 25% 10%, rgba(34,211,238,0.17), transparent 35%), radial-gradient(circle at 70% 5%, rgba(16,185,129,0.16), transparent 30%), linear-gradient(145deg, #060b14 0%, #0e1a2b 40%, #0b1727 100%)"
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
