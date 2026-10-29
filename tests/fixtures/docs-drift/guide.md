# Fake SDK guide

Some intro text mentioning `roundUp` in prose, which must not count.

```ts
interface InitOptions {
  apiKey: string
  features?: {
    roundUp?: boolean            // default: true
    legacyToggle?: boolean
  }
  appearance?: {
    theme?: string
  }
}
```

* `features`. Object of feature flags.
  * `roundUp`: boolean. Rounds the basket up.
  * `legacyToggle`: boolean. Old toggle.
* `appearance`. Look and feel.
  * `theme`: string.

Toggle state, which uses the same words under another parent:

```ts
type ToggleState = {
  roundUp: { amounts: ToggleAmounts }
  key: 'carbonCredits' | 'roundUp'
}
```
