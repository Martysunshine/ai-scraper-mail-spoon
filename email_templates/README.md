# Email templates

These are the **exact emails that get sent**. No AI writes or rewrites them —
the engine only loads the right file, fills in two placeholders, and sends.

## How a final email is built

For each organization the engine:

1. Picks the **native-language** file for the org's language (e.g. `outreach_cs.html`
   for a Czech org). If that file does not exist, it skips straight to English.
2. Always appends the **English** file (`outreach_en.html`) below the native version,
   separated by a divider.
3. Fills in the placeholders in every file used.

So a Czech organization receives: **Czech version → divider → English version**.
A Japanese organization with no `outreach_ja.html` receives **English only**.

## Naming convention

```
outreach_en.html   <- English (required — the universal fallback)
outreach_cs.html   <- Czech
outreach_fr.html   <- French
outreach_de.html   <- German
outreach_es.html   <- Spanish
outreach_<code>.html
```

`<code>` is the 2-letter language code from `official_languages_by_country.csv`
(the `Code` column). Add a file for each language you want a native version of.
Any language without its own file simply gets the English email.

## Placeholders (keep these in every file)

| Placeholder    | Replaced with                                             |
|----------------|-----------------------------------------------------------|
| `{{org_name}}` | The organization's name, e.g. `Dear {{org_name}},`        |
| `{{opt_out}}`  | The required unsubscribe / opt-out line (compliance)      |

If you remove `{{opt_out}}` and the email also contains no "unsubscribe" text,
the engine appends a standard opt-out footer automatically — but it is better to
place `{{opt_out}}` exactly where you want it.

## Subject line

The subject is **not** in these files. Set it once in `.env`:

```
EMAIL_SUBJECT=An invitation to try Infinity Faith
```

`{{org_name}}` works in the subject too, e.g.
`EMAIL_SUBJECT=An invitation for {{org_name}}`.

## Editing

Just replace the body of `outreach_en.html` with your finished, Gmail-ready HTML
(links, bold, lists — anything Gmail supports). Keep the two placeholders. Send
yourself a test first by leaving `EMAIL_MODE=draft` and reading the draft in the
panel before going live.
