# FTD Shun Branding

Adapted from the operator-supplied `ftd-shun-banana-v2.zip` visual proposal.
The archive's README was reviewed as design reference, not installed as agent
instructions. Assets use local/system fonts and contain no external resources.

- `source/terminal-banana-mark.svg`: header symbol; HTML provides the accessible
  product wordmark. `terminal-banana-mark-simple.svg` is the small-size icon.
- `source/logo-horizontal-{light,dark}.svg`: editable wordmarks, with PNG exports
  in `banners/`. The dark master's unresolved color placeholder was corrected.
- `source/readme-banner.svg` and `source/github-social.svg`: editable banners
  with **Monitor. Block. Unblock.** and PNG exports in `banners/`. The social
  asset is prepared locally; repository social-preview settings are unchanged.
- `icons/`: supplied PNG/ICO exports, including the Apple touch icon.
- `ui/empty-state.svg`: compact decorative empty-list art. Status stays in live
  HTML. The other supplied state assets are retained for future explicit use;
  they do not infer a successful device action or an outage.

## Palette and usage

Navy `#101D2D`, dark `#0B1624`, off-white `#E9F4F7`, muted `#9CB2C1`, cyan
`#5ACAC4` and yellow `#F6CA4D`. CSS tokens adapt surfaces/text/actions to light
and dark themes. Light-theme actionable teal is darker than decorative cyan to
preserve contrast. Yellow belongs mainly to the symbol; red/green status and
protection meanings remain. Keep the header compact and banners in documentation.
Empty-list art has explicit dimensions and an empty alt attribute, alongside
readable state text. Keep SVG masters editable; do not add external fonts.

## Exporting edited assets

From the repository root, with locally installed Inkscape:

```sh
inkscape static/branding/source/logo-horizontal-dark.svg \
  --export-filename=static/branding/banners/logo-horizontal-dark.png
inkscape static/branding/source/readme-banner.svg \
  --export-filename=static/branding/banners/readme-banner.png
inkscape static/branding/source/github-social.svg \
  --export-filename=static/branding/banners/github-social-1280x640.png
```

Re-export a PNG whenever its SVG master changes. Retain declared dimensions and
check text/margins visually. App builds hash SVG, PNG and ICO bytes alongside
other public source inputs; delivered branding changes need a version increment.
