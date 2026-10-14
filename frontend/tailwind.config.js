/** RE-BAT AI tokens: deep navy instrument panel, lime = recommended/live, cyan = measured data. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#0A1220", 900: "#0E1726", 850: "#121D31", 800: "#16233B", 700: "#1F2E4A", 600: "#2A3B5C" },
        fog: { 100: "#E8EEF7", 300: "#B7C3D6", 400: "#8A9AB5", 500: "#66779A" },
        volt: { DEFAULT: "#B6F23A", dim: "#7FA82A", glow: "rgba(182,242,58,0.14)" },
        data: { DEFAULT: "#4FC3E0", dim: "#2E7F96" },
        amber: { DEFAULT: "#F2B33D" },
        alarm: { DEFAULT: "#F0555A" },
      },
      fontFamily: {
        display: ['"Archivo"', "system-ui", "sans-serif"],
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
      },
      fontSize: { "2xs": ["0.6875rem", "1rem"] },
    },
  },
  plugins: [],
};
