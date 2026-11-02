import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";
import sonarjs from "eslint-plugin-sonarjs";

export default tseslint.config(
  { ignores: ["design", "dist", "coverage", "src/api/schema.ts"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.strict, sonarjs.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      "sonarjs/cognitive-complexity": ["error", 10],
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // The package root re-exports every icon (~3,000 files), which tsc and
      // vite then load on every build. Import each icon from its own module.
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "@phosphor-icons/react",
              message: 'Import the icon from "@phosphor-icons/react/dist/csr/<Name>" instead.',
            },
          ],
        },
      ],
    },
  },
);
