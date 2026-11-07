# @yarvelle/ui

Domain-neutral React component library and design system for Yarvelle. It provides design tokens, a Tailwind CSS preset, UI primitives, and ready-made surfaces for agent apps (chat, notes, calendar, tasks, notifications, settings, profiles, and an app shell). It also includes a slot system that lets domain packs add their own UI.

`@yarvelle/ui` is released alongside the [`yarvelle-core`](https://pypi.org/project/yarvelle-core/) Python runtime, and both use the same version numbers. See the [compatibility matrix](https://github.com/yarvelle/yarvelle-core/blob/main/compat.yaml).

## Install

```bash
npm install @yarvelle/ui
# or
pnpm add @yarvelle/ui
```

### Peer dependencies

| Package     | Version                  |
| ----------- | ------------------------ |
| `react`     | `>=18.2.0 \|\| >=19.0.0` |
| `react-dom` | `>=18.2.0 \|\| >=19.0.0` |

Node.js 20 or later is required for the build tooling and the `yarvelle-ui-codegen` CLI.

## Usage

Import the stylesheet once, then wrap your app in `UiProvider`:

```tsx
import '@yarvelle/ui/styles.css';
import { UiProvider, Button } from '@yarvelle/ui';

export function App() {
  return (
    <UiProvider product={{ name: 'My App' }} storageNamespace="my-app" defaultTheme="system">
      <Button variant="primary">Get started</Button>
    </UiProvider>
  );
}
```

`UiProvider` manages the light, dark and system themes, the product name, a storage namespace for persisted UI state, and i18n messages (`locale` and `messages`).

### Tailwind CSS preset

```js
// tailwind.config.js
import yarvellePreset from '@yarvelle/ui/tailwind-preset';

export default {
  presets: [yarvellePreset],
  content: ['./src/**/*.{ts,tsx}', './node_modules/@yarvelle/ui/dist/**/*.js'],
};
```

### Entry points

| Import                           | Contents                                                      |
| -------------------------------- | ------------------------------------------------------------- |
| `@yarvelle/ui`                   | Components, provider, slots, tokens and helpers               |
| `@yarvelle/ui/tokens`            | Design tokens                                                 |
| `@yarvelle/ui/tailwind-preset`   | Tailwind CSS preset (default export)                          |
| `@yarvelle/ui/slots`             | Slot types and `SlotRenderer` for pack-contributed UI         |
| `@yarvelle/ui/lib/*`             | Utilities such as `cn`, scoped storage, API, SSE, auth, i18n  |
| `@yarvelle/ui/testing`           | Test helpers (mock profiles, chat messages, slot contributions) |
| `@yarvelle/ui/styles.css`        | Token CSS variables                                           |

The package ships as ES modules with TypeScript declarations.

### Pack UI codegen

The `yarvelle-ui-codegen` CLI generates a pack registry module (`pack-registry.generated.ts`) from the enabled packs:

```bash
npx yarvelle-ui-codegen --packs finance --pack-module finance=@acme/finance-ui --out src/pack-registry.generated.ts
```

Run `npx yarvelle-ui-codegen --help` for all options.

## Links

- Repository: https://github.com/yarvelle/yarvelle-core (package source in [`frontend/`](https://github.com/yarvelle/yarvelle-core/tree/main/frontend))
- Documentation: https://yarvelle.github.io/yarvelle-core/
- Issues: https://github.com/yarvelle/yarvelle-core/issues
- Changelog: https://github.com/yarvelle/yarvelle-core/blob/main/CHANGELOG.md
- Releases: https://github.com/yarvelle/yarvelle-core/releases
- Security reports: see [SECURITY.md](https://github.com/yarvelle/yarvelle-core/blob/main/SECURITY.md)

## License

Copyright 2026 [Spectrayan](https://spectrayan.com).

Licensed under the [PolyForm Noncommercial License 1.0.0](https://github.com/yarvelle/yarvelle-core/blob/main/LICENSE) and the [Yarvelle Core Additional Terms](https://github.com/yarvelle/yarvelle-core/blob/main/ADDITIONAL-TERMS.md). Personal and household local use only. Commercial use, hosted service offerings, rebranding, white-labeling, and redistribution of modified forks require a written commercial license from Spectrayan (licensing@spectrayan.com). "Yarvelle", "Yarvelle Core" and "Spectrayan" are trademarks of Spectrayan; see the [trademark policy](https://github.com/yarvelle/yarvelle-core/blob/main/TRADEMARKS.md). The `LICENSE`, `NOTICE`, `ADDITIONAL-TERMS.md` and `TRADEMARKS.md` files ship in this package.
