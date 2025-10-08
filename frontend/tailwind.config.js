// frontend/tailwind.config.cjs
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};

// tailwind.config.js or tailwind.config.cjs
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: { extend: {} },
  plugins: [
    require('@tailwindcss/forms'),
    // require('@tailwindcss/typography'),  // if you use it, install it too
    // require('@tailwindcss/aspect-ratio') // if you use it, install it too
  ],
};