# Email templates

These are the **exact emails that get sent**. No AI writes or rewrites them — the
engine loads the right language file, drops in the greeting, appends the
signature, and sends.

## Source of truth: `outreach_languages.md`

Every language lives in **`outreach_languages.md`**, one section per language under
a `## <code> — Name` heading. The `outreach_<code>.html` files are **generated** from
it — don't hand-edit those (they'll be overwritten). Edit the markdown, then run:

```powershell
.\.venv\Scripts\python.exe tools\build_email_templates.py
```

The generator keeps the formatting identical across all languages (bold mission
line, bullet list, clickable links) and sets `dir="rtl"` for Arabic, Hebrew and
Urdu automatically. The only placeholder you keep in the markdown is
`{organisation's name}` — the engine turns it into `{{org_name}}` and fills it per
organization.

## How a final email is built

For each organization the engine assembles:

```
[ native-language message ]   (e.g. outreach_cs.html for a Czech org)
   — divider —
[ English message ]           (outreach_en.html — always included)
[ signature ]                 (from signature.html: Kind Regards, banner, buttons)
[ opt-out footer ]            (added automatically — compliance)
```

A language with no file of its own simply gets **English + signature + opt-out**.
You don't add or manage the opt-out line — the engine always appends one.

## Signature — `signature.html`

`signature.html` is a signature *builder page*; the engine extracts the
`<table id="sig">…</table>` inside it (Kind Regards · The Infinity Faith Team ·
CTA buttons · banner) and appends it to every email. The banner is a hosted image
URL inside that table — for production, host it on your own domain for reliability.
Edit the table in `signature.html` to change the sign-off.

## Subject line

The subject is **not** in these files. Set it once in `.env`:

```
EMAIL_SUBJECT=Helping More People Discover Your Community
```

`{{org_name}}` works in the subject too, e.g. `EMAIL_SUBJECT=An invitation for {{org_name}}`.

## Test before going live

Send yourself one real email (full template + signature) to see exactly how it lands:

```powershell
.\.venv\Scripts\python.exe -m infinity_outreach.cli send-test you@example.com --lang en
```
