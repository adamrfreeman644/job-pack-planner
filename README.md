# Job Pack Planner — initial Byte-Me version

Local, rules-based preparation of Forms Mobile Electrical Services Job Pack XML files. No AI service is used.

## Install on Unraid

1. Copy this folder to `/mnt/user/appdata/job-pack-planner` on Byte-Me.
2. Open an Unraid terminal in that folder.
3. Run `docker compose up -d --build`.
4. Open `http://192.168.1.187:1976`.

## First use

1. Under **Forms Mobile template**, upload one of your completed Electrical Services Job Pack XML files. The app immediately empties every record value before saving it as the local master template.
2. Import one or more small Booking Alert XML files.
3. Select the booking date, enter leave-home/return-home and job arrival/departure times, then press **Save times**.
4. Press **Share prepared XML**. On Android this opens the native share sheet when supported; otherwise the file downloads.
5. Open the prepared XML in Forms Mobile and complete findings, job status, photos and signatures normally.

## Important initial-version limitation

Test generated XML with Forms Mobile and the company workflow using a non-critical copy before relying on it. Forms Mobile compatibility is the next validation milestone. Outlook auto-import, route optimisation and detected office/collection stops are planned after XML round-trip compatibility is confirmed.

All data is stored in the local `data` directory. Do not expose port 1976 directly to the internet.

## Booking collection schedule

The Outlook collection time is fixed at **19:00 Europe/London**, with manual XML import always available. Duplicate job numbers replace the earlier imported copy instead of creating duplicate timeline entries.

To enable Outlook, provide `MS_CLIENT_ID` in a `.env` file beside `docker-compose.yml`. This must be the client ID of a Microsoft Entra public-client application configured for delegated Microsoft Graph `Mail.Read`. `MS_TENANT_ID` may be supplied as well; it defaults to `organizations`. Restart the compose project and press **Connect Outlook**. Microsoft opens its normal device-login page and uses the normal company MFA process. If Microsoft returns an administrator-consent requirement, the app stops immediately and displays a warning without downloading messages.
