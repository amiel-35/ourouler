// Configuration plate ESLint (front). Vérifie le style et les pièges React ;
// ne change aucun comportement visible — voir CONTRIBUTING.md.
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y";
import globals from "globals";

export default tseslint.config(
  {
    ignores: ["dist/**", "node_modules/**"],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      globals: {
        ...globals.browser,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "jsx-a11y": jsxA11y,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.configs.recommended.rules,
      // L'espace insécable du séparateur de milliers français apparaît dans
      // des classes de caractères de regex (`api/formats.ts`, tests) : une
      // espace « irrégulière » y est voulue, jamais une faute de frappe.
      "no-irregular-whitespace": ["error", { skipRegExps: true }],
    },
  },
  {
    files: ["vite.config.ts"],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
  },
);
